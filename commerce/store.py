"""Tenant-scoped persistence and transactional synthetic provider adapter."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from secrets import token_hex
import sqlite3

from .fixtures import PREFERENCES, RETURN_REASONS, RESOLUTIONS, seed, money


class Rejected(ValueError):
    """A request violates an ownership, state, or business predicate."""


class ProviderUnavailable(RuntimeError):
    """The selected synthetic provider is unavailable."""


@dataclass(frozen=True)
class Scope:
    tenant: str
    subject: str
    role: str


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def actor_tag(scope):
    return sha256(f"{scope.tenant}:{scope.role}:{scope.subject}".encode()).hexdigest()[:14]


class Repository:
    def __init__(self, path, today=date.today):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.today = today
        with self.read() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        with self.write() as db:
            if db.execute("SELECT COUNT(*) FROM tenants").fetchone()[0] == 0:
                seed(db, today())

    @contextmanager
    def read(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def write(self):
        with self.read() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except Exception:
                db.rollback()
                raise
            else:
                db.commit()

    def many(self, sql, params):
        with self.read() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def catalogue(self, tenant, query="", category="", brand="", maximum=None, available=False):
        search = [word.casefold() for word in query.split() if word.strip()]
        rows = self.many("SELECT * FROM products WHERE tenant=? ORDER BY sku", (tenant,))
        return [product for product in rows if
                (not category or product["category"].casefold() == category.casefold()) and
                (not brand or product["brand"].casefold() == brand.casefold()) and
                (maximum is None or product["price"] <= maximum) and
                (not available or product["stock"] > 0) and
                all(word in " ".join(str(product[key]).casefold() for key in (
                    "sku", "title", "category", "brand", "description")) for word in search)]

    def customers(self, tenant):
        return self.many("SELECT id,display FROM customers WHERE tenant=? ORDER BY id", (tenant,))

    @staticmethod
    def order_row(db, scope, reference):
        if scope.role != "customer":
            raise Rejected("A verified customer profile is required.")
        result = db.execute("SELECT * FROM orders WHERE tenant=? AND customer=? AND ref=?",
                            (scope.tenant, scope.subject, reference)).fetchone()
        if result is None:
            raise Rejected("That order is unavailable for your verified profile.")
        return result

    def owned_orders(self, scope):
        if scope.role != "customer":
            raise Rejected("A verified customer profile is required.")
        return self.many("SELECT ref,state,updated,total,currency FROM orders WHERE tenant=? AND customer=? ORDER BY ref",
                         (scope.tenant, scope.subject))

    def owned_order(self, scope, reference):
        with self.read() as db:
            result = dict(self.order_row(db, scope, reference))
            result["items"] = [dict(row) for row in db.execute(
                "SELECT line,sku,title,quantity,unit_price,personalised FROM items WHERE tenant=? AND order_ref=? ORDER BY line",
                (scope.tenant, reference))]
            result["returns"] = [dict(row) for row in db.execute(
                "SELECT ref,line,status,resolution FROM returns WHERE tenant=? AND order_ref=? ORDER BY line",
                (scope.tenant, reference))]
            return result

    def refund(self, scope, reference):
        with self.read() as db:
            self.order_row(db, scope, reference)
            return [dict(row) for row in db.execute(
                "SELECT ref,status,amount,currency,updated FROM refunds WHERE tenant=? AND order_ref=? ORDER BY ref",
                (scope.tenant, reference))]

    def official_passages(self, tenant, day=None):
        effective = (day or self.today()).isoformat()
        return self.many("SELECT * FROM knowledge WHERE tenant=? AND state='approved' AND effective<=? "
                         "AND (expires IS NULL OR expires>=?) ORDER BY source,version", (tenant, effective, effective))

    def active_policy(self, db, tenant, topic):
        effective = self.today().isoformat()
        rows = db.execute("SELECT * FROM knowledge WHERE tenant=? AND topic=? AND state='approved' "
                          "AND effective<=? AND (expires IS NULL OR expires>=?)",
                          (tenant, topic, effective, effective)).fetchall()
        if len(rows) != 1:
            raise Rejected("The current policy is ambiguous. Please contact support.")
        return rows[0]

    @staticmethod
    def cite(row):
        return {key: row[key] for key in ("source", "title", "version", "effective")}

    def current_quote(self, scope, action, fields):
        with self.read() as db:
            return self.validate_order_change(db, scope, action, fields)

    def validate_order_change(self, db, scope, action, fields):
        order = self.order_row(db, scope, fields["order"])
        topic = {"cancel_order": "cancellation", "modify_order": "changes", "request_return": "returns"}[action]
        policy = self.active_policy(db, scope.tenant, topic)
        if action in {"cancel_order", "modify_order"}:
            if order["state"] not in {"Confirmed", "Packing"}:
                raise Rejected(f"This order is {order['state'].lower()}. The store allows changes before dispatch.")
            if action == "modify_order" and fields["preference"] not in PREFERENCES:
                raise Rejected("Choose a supported delivery preference.")
            return order, policy, None
        if order["state"] != "Delivered" or not order["delivered"]:
            raise Rejected("The order must be delivered before a return can be requested.")
        item = db.execute("SELECT * FROM items WHERE tenant=? AND order_ref=? AND line=?",
                          (scope.tenant, order["ref"], fields["line"])).fetchone()
        if item is None:
            raise Rejected("Choose an item from the verified order.")
        if item["personalised"]:
            raise Rejected("The active policy excludes personalised items.")
        window = db.execute("SELECT return_days FROM tenants WHERE tenant=?", (scope.tenant,)).fetchone()[0]
        age = (self.today() - date.fromisoformat(order["delivered"])).days
        if not 0 <= age <= window:
            raise Rejected(f"The store's {window}-day return window has closed.")
        if fields["reason"] not in RETURN_REASONS or fields["resolution"] not in RESOLUTIONS:
            raise Rejected("Choose a supported reason and resolution.")
        if db.execute("SELECT ref FROM returns WHERE tenant=? AND order_ref=? AND line=?",
                      (scope.tenant, order["ref"], item["line"])).fetchone():
            raise Rejected("A return request already exists for this item.")
        return order, policy, item

    def record(self, tenant, session, event, detail="", ms=None):
        with self.write() as db:
            db.execute("INSERT INTO activity(tenant,session,event,detail,ms,time) VALUES (?,?,?,?,?,?)",
                       (tenant, session, event, detail, ms, timestamp()))

    @staticmethod
    def audit(db, scope, action, target, outcome, correlation):
        db.execute("INSERT INTO audit(tenant,actor,action,target,outcome,correlation,time) VALUES (?,?,?,?,?,?,?)",
                   (scope.tenant, actor_tag(scope), action, target, outcome, correlation, timestamp()))

    def commit(self, scope, token, action, fields, session):
        if scope.role != "customer":
            raise Rejected("A verified customer profile is required.")
        with self.write() as db:
            return self.atomic(db, scope, token, action,
                               lambda: self.apply_customer(db, scope, action, fields, session))

    def atomic(self, db, scope, token, action, execute):
        saved = db.execute("SELECT * FROM operations WHERE tenant=? AND token=?", (scope.tenant, token)).fetchone()
        if saved:
            if saved["actor"] != actor_tag(scope) or saved["operation"] != action:
                raise Rejected("This confirmation belongs to a different action.")
            return json.loads(saved["response"])
        result = execute()
        db.execute("INSERT INTO operations VALUES (?,?,?,?,?)",
                   (scope.tenant, token, actor_tag(scope), action, json.dumps(result)))
        self.audit(db, scope, action, result["reference"], result["status"], token)
        return result

    def apply_customer(self, db, scope, action, fields, session):
        tenant, today = scope.tenant, self.today().isoformat()
        if action in {"create_ticket", "request_human"}:
            return self.create_ticket(db, scope, action, fields, session)
        order, policy, item = self.validate_order_change(db, scope, action, fields)
        reference = order["ref"]
        if action == "cancel_order":
            change = db.execute("UPDATE orders SET state='Cancelled',updated=? WHERE tenant=? AND ref=? "
                                "AND customer=? AND state IN ('Confirmed','Packing')",
                                (today, tenant, reference, scope.subject))
            if change.rowcount != 1:
                raise Rejected("The order can no longer be cancelled.")
            return {"reference": reference, "status": "Cancelled", "rows": [["Provider", "Local simulated adapter"]],
                    "citation": self.cite(policy)}
        if action == "modify_order":
            db.execute("UPDATE orders SET preference=?,updated=? WHERE tenant=? AND ref=? AND customer=?",
                       (fields["preference"], today, tenant, reference, scope.subject))
            return {"reference": reference, "status": "Preference saved", "rows": [["Preference", fields["preference"]]],
                    "citation": self.cite(policy)}
        ret = "RET-" + token_hex(5).upper()
        db.execute("INSERT INTO returns VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (tenant, ret, reference, item["line"], fields["reason"], fields["resolution"], "Requested",
                    policy["source"], policy["version"], today))
        return {"reference": ret, "status": "Requested", "rows": [["Order", reference], ["Item", item["title"]],
                ["Resolution", fields["resolution"]], ["Next step", "Support will review your request."]],
                "citation": self.cite(policy)}

    def create_ticket(self, db, scope, action, fields, session):
        if action == "request_human":
            current = db.execute("SELECT ref,status FROM tickets WHERE tenant=? AND session=? AND customer=? "
                                 "AND kind='Handoff' AND status!='Resolved'", (scope.tenant, session, scope.subject)).fetchone()
            if current:
                return {"reference": current["ref"], "status": current["status"], "rows": [["Queue", "Support"]]}
        order = fields.get("order")
        if order:
            self.order_row(db, scope, order)
        ref = "TKT-" + token_hex(5).upper()
        priority = "Priority" if fields["category"] == "Payment status" else "Standard"
        db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            scope.tenant, ref, scope.subject, session, "Handoff" if action == "request_human" else "Complaint",
            fields["category"], priority, fields["summary"], order, "Open", None, timestamp()))
        return {"reference": ref, "status": "Open", "rows": [["Category", fields["category"]], ["Priority", priority]],
                "created": True}

    def customer_tickets(self, scope, reference=None):
        if scope.role != "customer":
            raise Rejected("A verified customer profile is required.")
        sql = "SELECT ref,kind,category,priority,status,created FROM tickets WHERE tenant=? AND customer=?"
        params = (scope.tenant, scope.subject)
        if reference:
            sql += " AND ref=?"
            params += (reference,)
        return self.many(sql + " ORDER BY created DESC,ref LIMIT 20", params)

    def messages(self, tenant, ticket):
        return self.many("SELECT actor,body,created FROM ticket_messages WHERE tenant=? AND ticket=? ORDER BY created,id",
                         (tenant, ticket))

    def staff_tickets(self, scope):
        if scope.role not in {"agent", "admin"}:
            raise Rejected("Staff access is required.")
        own = " AND (assigned=? OR assigned IS NULL)" if scope.role == "agent" else ""
        param = (scope.tenant, scope.subject) if own else (scope.tenant,)
        return self.many("SELECT ref,kind,category,priority,status,assigned,created FROM tickets WHERE tenant=?"
                         + own + " ORDER BY CASE status WHEN 'Open' THEN 0 WHEN 'In progress' THEN 1 ELSE 2 END,created,ref LIMIT 50", param)

    def staff_ticket(self, scope, reference):
        if scope.role not in {"agent", "admin"}:
            raise Rejected("Staff access is required.")
        rows = self.many("SELECT ref,category,priority,status,assigned,summary,order_ref FROM tickets "
                         "WHERE tenant=? AND ref=?", (scope.tenant, reference))
        if not rows or (scope.role == "agent" and rows[0]["assigned"] != scope.subject):
            raise Rejected("Claim an available ticket to view its context.")
        return {**rows[0], "messages": self.messages(scope.tenant, reference)}

    def update_ticket(self, scope, token, verb, reference, message):
        if scope.role not in {"agent", "admin"} or verb not in {"claim", "reply", "resolve"}:
            raise Rejected("Staff access and a valid action are required.")
        with self.write() as db:
            return self.atomic(db, scope, token, f"ticket_{verb}:{reference}",
                               lambda: self.apply_staff(db, scope, verb, reference, message))

    def apply_staff(self, db, scope, verb, reference, message):
        ticket = db.execute("SELECT * FROM tickets WHERE tenant=? AND ref=?",
                            (scope.tenant, reference)).fetchone()
        if not ticket or (scope.role == "agent" and ticket["assigned"] not in {None, scope.subject}):
            raise Rejected("That ticket is unavailable for your staff role.")
        if ticket["status"] == "Resolved":
            raise Rejected("This ticket has already been resolved.")
        if verb == "claim":
            if ticket["assigned"] not in {None, scope.subject}:
                raise Rejected("This ticket already has a staff assignee.")
            db.execute("UPDATE tickets SET assigned=?,status='In progress' WHERE tenant=? AND ref=?",
                       (scope.subject, scope.tenant, reference))
            return {"reference": reference, "status": "In progress"}
        if scope.role == "agent" and ticket["assigned"] != scope.subject:
            raise Rejected("Claim the ticket before updating it.")
        if verb == "reply":
            if not message.strip() or len(message) > 240:
                raise Rejected("Enter a reply of 1 to 240 characters.")
            db.execute("INSERT INTO ticket_messages VALUES (?,?,?,?,?,?)",
                       (scope.tenant, reference, token_hex(8), "Support", message, timestamp()))
            return {"reference": reference, "status": ticket["status"]}
        db.execute("UPDATE tickets SET status='Resolved' WHERE tenant=? AND ref=?", (scope.tenant, reference))
        return {"reference": reference, "status": "Resolved"}

    def analytics(self, scope):
        if scope.role != "admin":
            raise Rejected("Tenant administrator access is required.")
        with self.read() as db:
            grouped = db.execute("SELECT event,COUNT(*) count FROM activity WHERE tenant=? GROUP BY event",
                                 (scope.tenant,)).fetchall()
            counts = {row["event"]: row["count"] for row in grouped}
            latencies = sorted(row[0] for row in db.execute(
                "SELECT ms FROM activity WHERE tenant=? AND event='turn' AND ms IS NOT NULL", (scope.tenant,)))
            statuses = {row[0]: row[1] for row in db.execute(
                "SELECT status,COUNT(*) FROM tickets WHERE tenant=? GROUP BY status", (scope.tenant,))}
            intents = {row[0]: row[1] for row in db.execute(
                "SELECT detail,COUNT(*) FROM activity WHERE tenant=? AND event='intent' GROUP BY detail", (scope.tenant,))}
        used = len(latencies)
        return {"conversations": counts.get("session_start", 0), "chat_turns": used,
                "workflow_starts": counts.get("workflow_start", 0), "workflow_completions": counts.get("workflow_complete", 0),
                "fallback_turns": counts.get("fallback", 0), "handoff_created": counts.get("handoff", 0),
                "provider_errors": counts.get("provider_error", 0), "ticket_statuses": statuses, "intents": intents,
                "p95_ms": round(latencies[(95 * used + 99) // 100 - 1], 3) if used else None}


class CommerceAdapter:
    """The service boundary for order, refund and confirmed commerce requests."""

    def __init__(self, repository, offline=()):
        self.repo = repository
        self.offline = frozenset(offline)

    def available(self, scope):
        if scope.tenant in self.offline:
            raise ProviderUnavailable("The store's order provider is currently unavailable. Try again or contact support.")

    def orders(self, scope):
        self.available(scope)
        return self.repo.owned_orders(scope)

    def order(self, scope, reference):
        self.available(scope)
        return self.repo.owned_order(scope, reference)

    def refund(self, scope, reference):
        self.available(scope)
        return self.repo.refund(scope, reference)

    def quote(self, scope, action, fields):
        self.available(scope)
        return self.repo.current_quote(scope, action, fields)

    def commit(self, scope, token, action, fields, session):
        self.available(scope)
        return self.repo.commit(scope, token, action, fields, session)
