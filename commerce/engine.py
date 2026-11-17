"""Dialogue workflow shared by portable and Rasa-backed opening intent routing."""

from dataclasses import asdict, dataclass, field
import re
from secrets import token_urlsafe

from .auth import scrub
from .fixtures import ISSUE_CATEGORIES, PREFERENCES, RESOLUTIONS, RETURN_REASONS, SERVICES, money
from .nlu import NLUUnavailable
from .store import ProviderUnavailable, Rejected


ORDER = re.compile(r"\bORD[- ]?([0-9]{4})\b", re.I)
SKU = re.compile(r"\b(?:NL|TT)-[0-9]{3}\b", re.I)
CUSTOMER = re.compile(r"DEMO[0-9]{3}")
TICKET = re.compile(r"TKT-[A-F0-9]{10}")
CANCEL_DRAFT = {"cancel draft", "discard draft", "start over"}
PUBLIC = {"search_product", "compare_products", "policy_question"}
CASE_ACTIONS = {"create_ticket", "request_human"}


@dataclass
class Reply:
    event: str
    message: str
    title: str = ""
    rows: list = field(default_factory=list)
    options: list = field(default_factory=list)
    products: list = field(default_factory=list)
    citation: dict | None = None
    reference: str | None = None


class Desk:
    def __init__(self, repo, provider, knowledge, sessions, nlu):
        self.repo = repo
        self.provider = provider
        self.knowledge = knowledge
        self.sessions = sessions
        self.nlu = nlu

    def signal(self, session, event, detail="", ms=None):
        self.repo.record(session.tenant, session.tag, event, detail, ms)

    @staticmethod
    def public_products(products):
        return [{**p, "price_label": money(p["price"]), "availability": "In stock" if p["stock"] else "Out of stock"}
                for p in products]

    def send(self, session, text, shortcut):
        previous = session.draft["stage"] if session.draft else "menu"
        private = previous in {"identity", "otp", "details"}
        echo = "[Demo identity entered]" if previous == "identity" else "[Verification input]" if previous == "otp" else scrub(text)
        if previous == "details" and text.casefold() not in CANCEL_DRAFT:
            echo = "[Issue details entered]"
        if text.casefold() in CANCEL_DRAFT:
            session.draft = session.pending = None
            result = Reply("discarded", "The draft was discarded. You can choose another task.")
        else:
            try:
                result = self.route(session, text, shortcut)
            except ProviderUnavailable as problem:
                self.signal(session, "provider_error")
                result = Reply("provider_unavailable", str(problem), options=["Retry", "Cancel draft"])
                if session.draft:
                    session.draft["retry"] = "Pick an order" if previous in {"menu", "otp"} else text
            except Rejected as problem:
                stage = session.draft["stage"] if session.draft else "menu"
                if stage in {"review", "resolution"}:
                    session.draft = None
                result = Reply("rejected", str(problem), options=["Cancel draft"] if session.draft else [])
            except NLUUnavailable:
                result = Reply("nlu_unavailable", "The optional Rasa service did not reply. Try a task button or check the local Rasa process.")
        result = asdict(result)
        result.update(echo=echo, stage=session.draft["stage"] if session.draft else "menu",
                      protected=private or self.sessions.grant(session) is not None,
                      task=session.draft["action"] if session.draft else None)
        return result

    def route(self, session, text, shortcut):
        if shortcut:
            if session.draft:
                return Reply("draft_in_progress", "Finish or discard the current task before starting another.", options=["Cancel draft"])
            return self.begin(session, shortcut, "", "shortcut")
        if session.draft:
            draft = session.draft
            action, stage = draft["action"], draft["stage"]
            if stage not in {"identity", "otp"} and action not in PUBLIC:
                grant = self.sessions.grant(session)
                if not grant or grant.role != "customer":
                    session.scope = session.last_order = None
                    session.cache.clear()
                    draft["fields"].clear()
                    draft["stage"] = "identity"
                    return Reply("verification_expired", "Verification expired. Choose a demo profile to restart this task.")
            if text.casefold() == "retry" and draft.get("retry"):
                text = draft.pop("retry")
            return self.advance(session, text)
        prediction = self.nlu.parse(scrub(text))
        if prediction.intent in SERVICES:
            return self.begin(session, prediction.intent, text, self.nlu.name)
        self.signal(session, "intent", prediction.intent)
        if prediction.intent == "greet":
            session.fallback_count = 0
            return Reply("greet", "Choose a store task or tell me what you need.")
        if prediction.intent == "goodbye":
            session.fallback_count = 0
            return Reply("goodbye", "You can return to the desk whenever you need help.")
        session.fallback_count += 1
        self.signal(session, "fallback")
        hint = " I can also queue an agent." if session.fallback_count >= 2 else ""
        return Reply("fallback", "I can help with this store's products, orders and support policies." + hint,
                     options=["Talk to an agent"] if hint else [])

    def begin(self, session, action, text, source):
        self.signal(session, "workflow_start", action)
        self.signal(session, "intent", action)
        session.fallback_count = 0
        draft = {"action": action, "stage": "start", "fields": {}, "token": token_urlsafe(20), "source": source}
        session.draft = draft
        fields = draft["fields"]
        if action == "policy_question":
            if text:
                return self.policy(session, text)
            draft["stage"] = "question"
            return Reply("ask_policy", "Ask a question about this store's shipping, returns, warranty, or other policies.",
                         options=["What are the shipping charges?", "How many days is the return window?"])
        if action == "search_product":
            if text:
                skus = SKU.findall(text)
                value = skus[0] if skus else re.sub(
                    r"\b(?:please|could|you|me|my|show|find|search|product|products|for|a|an|the|looking|am|i|do|have|in|store|any|want|need|catalogue|catalog|which|list|available)\b",
                    " ", text.casefold()).strip(" ?.!-")
                return self.search(session, value)
            draft["stage"] = "search"
            return Reply("ask_search", "Enter a product name, category, or SKU.", options=["Show all"])
        if action == "compare_products":
            skus = [sku.upper() for sku in SKU.findall(text)]
            if len(skus) == 2:
                return self.compare(session, skus)
            draft["stage"] = "compare"
            options = [p["sku"] for p in self.repo.catalogue(session.tenant)]
            return Reply("ask_compare", "Enter two SKUs, separated by a comma.", options=[", ".join(options[:2])])
        match = ORDER.search(text)
        if match:
            fields["candidate"] = "ORD-" + match[1]
        elif re.search(r"\b(?:that|this) order\b", text, re.I) and session.last_order:
            fields["candidate"] = session.last_order
        grant = self.sessions.grant(session)
        if not grant or grant.role != "customer":
            draft["stage"] = "identity"
            return Reply("ask_identity", "Use a demo profile to verify before opening account records.",
                         options=[p["id"] for p in self.repo.customers(session.tenant)])
        return self.open_protected(session, grant)

    def done(self, session, reply):
        self.signal(session, "workflow_complete", session.draft["action"])
        session.draft = None
        return reply

    def search(self, session, value):
        matches = self.repo.catalogue(session.tenant, "" if value.casefold() == "show all" else value)
        if not matches:
            session.draft["stage"] = "search"
            return Reply("no_products", "No matches in this store. Try a shorter name or enter a SKU.", options=["Show all", "Cancel draft"])
        return self.done(session, Reply("products_found", f"{len(matches)} product{'s' if len(matches) != 1 else ''} in this store.",
                                        products=self.public_products(matches)))

    def compare(self, session, skus):
        items = [p for p in self.repo.catalogue(session.tenant) if p["sku"] in set(skus)]
        if len(items) != 2:
            session.draft["stage"] = "compare"
            return Reply("compare_invalid", "Enter two different SKUs from the active store.")
        return self.done(session, Reply("comparison_ready", "Compare listed prices, features, and availability.",
                                        products=self.public_products(items)))

    def policy(self, session, question):
        data = self.knowledge.answer(session.tenant, question)
        if data is None:
            session.draft = None
            self.signal(session, "policy_abstain")
            return Reply("policy_abstain", "I could not find a clear answer in this store's current policies. Try a more specific question or ask an agent.",
                         options=["Talk to an agent"])
        return self.done(session, Reply("policy_answer", data["passage"], "Store policy", citation=data["citation"]))

    def open_protected(self, session, grant):
        draft = session.draft
        fields, action = draft["fields"], draft["action"]
        if action in CASE_ACTIONS:
            draft["stage"] = "category"
            return Reply("ask_category", "Choose the issue category for the support queue.", options=list(ISSUE_CATEGORIES))
        if action == "ticket_status":
            draft["stage"] = "ticket"
            tickets = self.repo.customer_tickets(grant)
            return Reply("ask_ticket", "Enter or choose your ticket reference.", options=[t["ref"] for t in tickets])
        draft["stage"] = "order"
        if fields.get("candidate"):
            result = self.use_order(session, grant, fields["candidate"])
            fields.pop("candidate", None)
            return result
        orders = self.provider.orders(grant)
        if len(orders) == 1:
            return self.use_order(session, grant, orders[0]["ref"])
        return Reply("ask_order", "Choose one of your orders or enter its reference.",
                     options=[order["ref"] for order in orders])

    def use_order(self, session, grant, reference):
        draft = session.draft
        action, fields = draft["action"], draft["fields"]
        order = self.provider.order(grant, reference)
        fields["order"], session.last_order = reference, reference
        if action == "track_order":
            rows = [["Status", order["state"]], ["Updated", order["updated"]], ["Total", money(order["total"])],
                    ["Delivery preference", order["preference"]]]
            if order["tracking"]:
                rows += [["Carrier", order["carrier"]], ["Tracking ID", order["tracking"]]]
            rows += [[f"Item {item['line']}", f"{item['title']} × {item['quantity']}"] for item in order["items"]]
            rows += [[ret["ref"], f"{ret['resolution']} · {ret['status']}"] for ret in order["returns"]]
            return self.done(session, Reply("order_tracked", "Here is the latest record from the store.", reference, rows, reference=reference))
        if action == "refund_status":
            refunds = self.provider.refund(grant, reference)
            rows = [[row["ref"], f"{row['status']} · {money(row['amount'])} · {row['updated']}"] for row in refunds]
            if not rows:
                session.draft = None
                return Reply("refund_missing", "The provider has no refund record for this order.", reference)
            return self.done(session, Reply("refund_read", "Here is the provider's recorded refund status.", reference, rows, reference=reference))
        if action == "cancel_order":
            return self.review(session, grant)
        if action == "modify_order":
            draft["stage"] = "preference"
            return Reply("ask_preference", "Which delivery preference should the store use?", options=list(PREFERENCES))
        draft["stage"] = "line"
        return Reply("ask_item", "Choose the order line for your request.",
                     options=[item["line"] + " · " + item["title"] for item in order["items"]])

    def review(self, session, grant):
        draft = session.draft
        action, fields = draft["action"], draft["fields"]
        citation = None
        if action in CASE_ACTIONS:
            rows = [["Category", fields["category"]], ["Summary", fields["summary"]]]
            if fields.get("order"):
                rows.append(["Related order", fields["order"]])
        else:
            order, policy, item = self.provider.quote(grant, action, fields)
            citation = self.repo.cite(policy)
            rows = [["Order", order["ref"]], ["Current status", order["state"]]]
            if action == "cancel_order":
                rows.append(["After confirmation", "Cancelled in the simulated provider"])
            elif action == "modify_order":
                rows.append(["New preference", fields["preference"]])
            else:
                rows.extend([["Item", item["title"]], ["Reason", fields["reason"]], ["Resolution", fields["resolution"]]])
        draft["stage"] = "review"
        return Reply("review", "Check the details, then confirm or discard this request.", SERVICES[action], rows,
                     ["Confirm", "Cancel draft"], citation=citation)

    @staticmethod
    def choice(text, choices):
        return next((choice for choice in choices if choice.casefold() == text.casefold()), None)

    def advance(self, session, text):
        draft = session.draft
        action, stage, fields = draft["action"], draft["stage"], draft["fields"]
        value = text.strip()
        if stage == "search":
            return self.search(session, value)
        if stage == "compare":
            return self.compare(session, [x.upper() for x in SKU.findall(value)])
        if stage == "question":
            return self.policy(session, value)
        if stage == "identity":
            ident = value.upper()
            if not CUSTOMER.fullmatch(ident):
                return Reply("invalid_identity_format", "Use a demo customer ID in the form DEMO101.")
            result = self.sessions.issue(session, ident if any(c["id"] == ident for c in self.repo.customers(session.tenant)) else None)
            if result == "issued":
                fields["identity"] = ident
                draft["stage"] = "otp"
                return Reply("code_issued", "Open the demo inbox. A matching profile receives a code for this session.", options=["Resend code"])
            return Reply("code_" + result, "Wait before asking for another verification code.")
        if stage == "otp":
            if value.casefold() == "resend code":
                matching = fields["identity"] if any(c["id"] == fields["identity"] for c in self.repo.customers(session.tenant)) else None
                result = self.sessions.issue(session, matching)
                return Reply("code_" + result, "Check the demo inbox for a current code.")
            result = self.sessions.verify(session, value)
            if result != "verified":
                return Reply("code_" + result, "Enter the valid six-digit code for this session. Request a new code if it expired.", options=["Resend code", "Cancel draft"])
            fields.pop("identity", None)
            session.cache.clear()
            return self.open_protected(session, self.sessions.grant(session))
        grant = self.sessions.grant(session)
        if stage == "order":
            match = ORDER.fullmatch(value)
            if value == "Pick an order":
                return self.open_protected(session, grant)
            if not match:
                return Reply("invalid_order", "Use an order reference such as ORD-2401, or view your order list.", options=["Pick an order"])
            return self.use_order(session, grant, "ORD-" + match[1])
        if stage == "line":
            line = value.split(" · ", 1)[0].zfill(2)
            order = self.provider.order(grant, fields["order"])
            if line not in {item["line"] for item in order["items"]}:
                return Reply("invalid_line", "Choose an item from the order shown above.")
            fields["line"] = line
            draft["stage"] = "reason"
            return Reply("ask_reason", "What is the reason for returning the item?", options=list(RETURN_REASONS))
        if stage == "details":
            if not 8 <= len(value) <= 240:
                return Reply("invalid_details", "Describe the issue in 8 to 240 characters.")
            fields["summary"] = scrub(value)
            if session.last_order:
                fields["order"] = session.last_order
            return self.review(session, grant)
        if stage == "ticket":
            reference = value.upper()
            items = self.repo.customer_tickets(grant, reference) if TICKET.fullmatch(reference) else []
            if not items:
                return Reply("ticket_missing", "That ticket is unavailable for your verified profile.")
            ticket = items[0]
            rows = [["Status", ticket["status"]], ["Category", ticket["category"]]]
            rows += [[note["actor"], note["body"]] for note in self.repo.messages(grant.tenant, reference)]
            return self.done(session, Reply("ticket_read", "Here is the saved ticket and any staff updates.", reference, rows, reference=reference))
        choices = {"preference": PREFERENCES, "reason": RETURN_REASONS, "resolution": RESOLUTIONS, "category": ISSUE_CATEGORIES}
        if stage in choices:
            selected = self.choice(value, choices[stage])
            if selected is None:
                return Reply("invalid_choice", "Choose a listed option.", options=list(choices[stage]))
            fields[stage] = selected
            if stage == "reason":
                draft["stage"] = "resolution"
                return Reply("ask_resolution", "Which resolution would you prefer?", options=list(RESOLUTIONS))
            if stage == "category":
                draft["stage"] = "details"
                return Reply("ask_details", "Describe the issue in a short fictional message.")
            return self.review(session, grant)
        if stage == "review":
            if value.casefold() != "confirm":
                return Reply("confirm_required", "Use Confirm to send this review, or Cancel draft to discard it.", options=["Confirm", "Cancel draft"])
            result = (self.repo if action in CASE_ACTIONS else self.provider).commit(
                grant, draft["token"], action, fields, session.tag)
            if action == "request_human" and result.get("created"):
                self.signal(session, "handoff")
            return self.done(session, Reply("confirmed", "The store recorded the confirmed request.", result["reference"],
                                            [["Status", result["status"]], *result["rows"]],
                                            citation=result.get("citation"), reference=result["reference"]))
        raise Rejected("The draft is unavailable. Discard it and choose a new task.")
