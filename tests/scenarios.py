"""Isolated local HTTP scenarios with fixture-controlled time and recorded receipts."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import uuid4

from commerce.auth import Sessions
from commerce.engine import Desk
from commerce.fixtures import SERVICES
from commerce.http import make_server
from commerce.knowledge import Knowledge
from commerce.nlu import PortableNLU, RasaNLU
from commerce.store import CommerceAdapter, Repository, Scope

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "commerce_intents.json"
DATE = date(2026, 11, 15)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class Client:
    def __init__(self, base, timings, traces):
        self.base, self.timings, self.traces = base, timings, traces
        self.cookies = CookieJar()
        self.open = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies)).open

    def request(self, path, payload=None, code=200, headers=None):
        spec = {"Origin": self.base, **(headers or {})}
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            spec["Content-Type"] = "application/json"
        request = Request(self.base + path, data, spec)
        try:
            response = self.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            assert response.code == code, (path, response.code, body[:400])
            return json.loads(body) if "json" in response.headers.get_content_type() else body

    def session(self, tenant=None):
        return self.request("/api/session", {"tenant": tenant} if tenant else None)

    def chat(self, text, shortcut=None, event=None, key=None, code=200):
        start = perf_counter()
        reply = self.request("/api/chat", {"text": text, "shortcut": shortcut,
                             "request_id": key or str(uuid4())}, code)
        if code == 200:
            self.timings.append({"event": reply["event"], "ms": round((perf_counter() - start) * 1000, 3)})
            trace = {key: reply[key] for key in ("echo", "event", "message", "title", "rows", "citation", "reference")}
            self.traces.append(trace)
        if event:
            assert reply["event"] == event, (text, event, reply)
        return reply

    def task(self, intent, event=None):
        return self.chat(SERVICES[intent], intent, event)

    def code(self):
        return self.request("/api/inbox")["code"]

    def verify(self, customer="DEMO101", final="ask_order"):
        self.chat(customer, event="code_issued")
        code = self.code()
        assert code and len(code) == 6
        answer = self.chat(code, event=final)
        assert code not in answer["echo"] and self.code() is None
        return answer

    def staff(self, role, pin, code=200):
        return self.request("/api/staff/login", {"user": role, "pin": pin}, code)

    def staff_action(self, action, ref, message="", code=200):
        return self.request("/api/staff/action", {"action": action, "reference": ref, "message": message,
                                                 "request_id": str(uuid4())}, code)


class Scenario:
    def __init__(self, db, offline=(), nlu=None):
        self.clock = Clock()
        self.repo = Repository(db, today=lambda: DATE)
        self.desk = Desk(self.repo, CommerceAdapter(self.repo, offline), Knowledge(self.repo),
                         Sessions(self.clock), nlu or PortableNLU(MODEL))
        self.timings, self.traces = [], []

    def client(self, tenant="nook"):
        client = Client(self.base, self.timings, self.traces)
        client.session(tenant)
        return client

    def scalar(self, query, *parameters):
        with self.repo.read() as db:
            return db.execute(query, parameters).fetchone()[0]

    @contextmanager
    def start(self):
        with make_server(ROOT, self.desk, 0) as server:
            self.base = f"http://127.0.0.1:{server.server_port}"
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            try:
                yield self
            finally:
                server.shutdown()
                thread.join()


def bootstrap(s):
    c = s.client()
    assert b"CommerceAI" in c.request("/") and b"function" in c.request("/static/app.js")
    assert c.request("/api/health")["status"] == "ready"
    cookie = next(iter(c.cookies))
    assert cookie.name == "commerce_demo" and cookie.has_nonstandard_attr("HttpOnly")
    c.request("/api/session", {"tenant": "nook"}, code=403, headers={"Origin": "https://invalid.example"})
    return "Browser assets and an HTTP-only session loaded. A foreign origin was refused."


def catalogue(s):
    c = s.client()
    p = c.request("/api/catalogue?category=Desk&brand=Nook%20Studio&max=900&available=1")["products"]
    assert [item["sku"] for item in p] == ["NL-102", "NL-103"]
    c.request("/api/catalogue?max=-1", code=400)
    c.session("trail")
    assert c.request("/api/catalogue?q=NL-101")["products"] == []
    assert len(c.request("/api/catalogue?available=1")["products"]) == 5
    return "Brand, category, whole-rupee price and availability filters respected the current store."


def compare(s):
    c = s.client()
    c.task("compare_products", "ask_compare")
    c.chat("NL-101, TT-101", event="compare_invalid")
    answer = c.chat("NL-101, NL-102", event="comparison_ready")
    assert {row["price"] for row in answer["products"]} == {179900, 79900}
    c.task("search_product", "ask_search")
    assert c.chat("desk lamp", event="products_found")["products"][0]["sku"] == "NL-101"
    return "Search returned an exact catalogue record. Comparison rejected a foreign SKU."


def tracked(s):
    c = s.client()
    c.chat("Where is my order", event="ask_identity")
    c.verify()
    answer = c.chat("ORD-2402", event="order_tracked")
    assert ["Status", "Dispatched"] in answer["rows"]
    assert ["Tracking ID", "NOOK-SHIP-2402"] in answer["rows"]
    assert ["Item 01", "Dune Desk Mat × 1"] in answer["rows"]
    return "A typed opening led to verification, then an owned shipment snapshot."


def cross_customer(s):
    c = s.client()
    c.request("/api/orders", code=403)
    c.task("track_order", "ask_identity")
    c.verify()
    assert "ORD-2405" not in {row["ref"] for row in c.request("/api/orders")["orders"]}
    c.chat("ORD-2405", event="rejected")
    assert not c.chat("ORD-9999", event="rejected")["rows"]
    return "Anonymous orders were denied. Both foreign and nonexistent references produced ownership-safe messages."


def switch(s):
    c = s.client()
    c.task("track_order", "ask_identity")
    c.verify()
    assert ["Item 01", "Arc Desk Lamp × 1"] in c.chat("ORD-2401", event="order_tracked")["rows"]
    old = next(iter(c.cookies)).value
    c.session("trail")
    c.request("/api/orders", code=403)
    foreign = Client(c.base, [], [])
    foreign.request("/api/orders", code=401, headers={"Cookie": "commerce_demo=" + old})
    c.task("track_order", "ask_identity")
    c.verify()
    assert ["Item 01", "Ridge Daypack × 1"] in c.chat("ORD-2401", event="order_tracked")["rows"]
    return "Switching stores revoked the former cookie and required verification. A colliding reference returned tenant-specific items."


def otp(s):
    c, other = s.client(), s.client()
    c.task("track_order", "ask_identity")
    c.chat("DEMO999", event="code_issued")
    assert c.code() is None
    c.chat("Cancel draft", event="discarded")
    s.clock.now += 13
    c.task("track_order", "ask_identity")
    c.chat("DEMO101", event="code_issued")
    old = c.code()
    assert old and other.code() is None
    c.chat("Resend code", event="code_cooldown")
    c.chat("abc", event="code_format")
    s.clock.now += 301
    c.chat(old, event="code_expired")
    c.chat("Resend code", event="code_issued")
    wrong = "111111" if c.code() != "111111" else "222222"
    c.chat(wrong, event="code_wrong")
    c.chat(wrong, event="code_wrong")
    c.chat(wrong, event="code_locked")
    c.chat("Resend code", event="code_locked")
    return "Challenge secrecy, cooldown, malformed input, expiry and three-wrong-code lock all held."


def collect_cancel(c, order="ORD-2401"):
    c.task("cancel_order", "ask_identity")
    c.verify()
    return c.chat(order, event="review")


def expired(s):
    c = s.client()
    collect_cancel(c)
    key = str(uuid4())
    c.chat("still checking", event="confirm_required", key=key)
    s.clock.now += 601
    c.chat("still checking", key=key, code=403)
    assert c.session()["reply"] is None
    c.chat("Confirm", event="verification_expired")
    assert s.scalar("SELECT state FROM orders WHERE tenant='nook' AND ref='ORD-2401'") == "Packing"
    return "The expired grant blocked cached protected data and a pending write."


def cancellation(s):
    c = s.client()
    review = collect_cancel(c)
    assert review["citation"]["source"] == "NOOK-CANCELLATION"
    c.chat("yes I suppose", event="confirm_required")
    key = str(uuid4())
    one = c.chat("Confirm", event="confirmed", key=key)
    assert ["Status", "Cancelled"] in one["rows"]
    assert c.chat("Confirm", event="confirmed", key=key)["replayed"]
    c.chat("Change", key=key, code=409)
    assert s.scalar("SELECT COUNT(*) FROM operations") == 1
    assert s.scalar("SELECT COUNT(*) FROM audit") == 1
    assert s.scalar("SELECT state FROM orders WHERE tenant='trail' AND ref='ORD-2401'") == "Packing"
    return "Confirmation changed one owned provider row. Retry replayed it and conflicting content was rejected."


def cancel_locked(s):
    c = s.client()
    c.task("cancel_order", "ask_identity")
    c.verify()
    c.chat("ORD-2402", event="rejected")
    c.chat("ORD-2401", event="review")
    c.chat("Cancel draft", event="discarded")
    assert s.scalar("SELECT COUNT(*) FROM operations") == 0
    return "Dispatched orders were ineligible and discarding a draft wrote no operation."


def race(s):
    one, two = s.client(), s.client()
    collect_cancel(one)
    collect_cancel(two)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = {response["event"] for response in pool.map(lambda c: c.chat("Confirm"), [one, two])}
    assert results == {"confirmed", "rejected"}
    assert s.scalar("SELECT COUNT(*) FROM operations") == 1 and s.scalar("SELECT COUNT(*) FROM audit") == 1
    return "Two independently verified drafts competed. Exactly one confirmation committed."


def modify(s):
    c = s.client()
    c.task("modify_order", "ask_identity")
    c.verify()
    c.chat("ORD-2407", event="ask_preference")
    c.chat("Shipping to a new address", event="invalid_choice")
    c.chat("Call on arrival", event="review")
    c.chat("Confirm", event="confirmed")
    assert s.scalar("SELECT preference FROM orders WHERE tenant='nook' AND ref='ORD-2407'") == "Call on arrival"
    return "The selected preference persisted after review. Arbitrary address text was refused."


def start_return(c, ref, item="01", expected="review"):
    c.task("request_return", "ask_identity")
    c.verify()
    c.chat(ref, event="ask_item")
    c.chat(item, event="ask_reason")
    c.chat("Damaged", event="ask_resolution")
    return c.chat("Replacement", event=expected)


def returned(s):
    c = s.client()
    start_return(c, "ORD-2403")
    answer = c.chat("Confirm", event="confirmed")
    ref = answer["reference"]
    assert ref.startswith("RET-") and answer["citation"]["version"] == "3.2"
    c.task("track_order", "ask_order")
    tracking = c.chat("ORD-2403", event="order_tracked")
    assert [ref, "Replacement · Requested"] in tracking["rows"]
    assert s.scalar("SELECT version FROM returns WHERE tenant='nook' AND ref=?", ref) == "3.2"
    return "The replacement case included its policy version and reappeared in the owned order."


def return_window(s):
    a, b = s.client("nook"), s.client("trail")
    assert "14-day" in start_return(a, "ORD-2409", expected="rejected")["message"]
    start_return(b, "ORD-2409")
    b.chat("Confirm", event="confirmed")
    assert s.scalar("SELECT tenant FROM returns") == "trail"
    return "The same 20-day-old order was rejected by the 14-day store and accepted by the 30-day store."


def exclusions(s):
    c = s.client()
    assert "personalised" in start_return(c, "ORD-2403", "02", "rejected")["message"]
    assert s.scalar("SELECT COUNT(*) FROM returns") == 0
    return "The active policy refused the engraved line and created no return."


def refund(s):
    a, b = s.client("nook"), s.client("trail")
    for c, expected in [(a, "Processed · ₹399.00"), (b, "In review · ₹649.00")]:
        c.task("refund_status", "ask_identity")
        c.verify()
        assert expected in c.chat("ORD-2404", event="refund_read")["rows"][0][1]
        c.task("refund_status", "ask_order")
        c.chat("ORD-2401", event="refund_missing")
    assert s.scalar("SELECT COUNT(*) FROM operations") == 0
    return "Refund reads followed tenant-owned orders and caused no financial or provider mutation."


def provider_offline(s):
    a, b = s.client("nook"), s.client("trail")
    a.task("track_order", "ask_identity")
    a.verify(final="provider_unavailable")
    a.chat("Retry", event="provider_unavailable")
    b.task("track_order", "ask_identity")
    b.verify()
    b.chat("ORD-2401", event="order_tracked")
    return "The affected tenant received an unavailable reply and retry. The other store remained responsive."


def cite_policy(s):
    for tenant, expected in (("nook", "14 calendar days"), ("trail", "30 calendar days")):
        c = s.client(tenant)
        c.task("policy_question", "ask_policy")
        reply = c.chat("How many days is the return window?", event="policy_answer")
        assert expected in reply["message"] and reply["citation"]["source"] == tenant.upper() + "-RETURNS"
        assert reply["citation"]["version"] == "3.2"
    return "Both tenants answered the same question from different current evidence."


def conflict(s):
    c = s.client()
    c.task("policy_question", "ask_policy")
    c.chat("Who discovered Neptune?", event="policy_abstain")
    with s.repo.write() as db:
        db.execute("INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?,?,?)", ("nook", "NOOK-CONFLICT", "returns",
                   "Conflicting revision", "1.0", "2025-01-01", None, "approved", "return window days return",
                   "Return window is 50 days."))
    c.task("policy_question", "ask_policy")
    assert c.chat("How many days is the return window?", event="policy_abstain")["citation"] is None
    return "Unknown and conflicting evidence produced an abstention and an agent option."


def new_ticket(c, action="request_human"):
    c.task(action, "ask_identity")
    c.verify(final="ask_category")
    c.chat("Delivery", event="ask_details")
    c.chat("The fictional parcel needs a follow-up at example@example.com.", event="review")
    return c.chat("Confirm", event="confirmed")["reference"]


def support(s):
    customer, agent, other = s.client(), s.client(), s.client("trail")
    ref = new_ticket(customer, "create_ticket")
    agent.staff("nook.agent", "2411")
    agent.request(f"/api/staff/ticket?ref={ref}", code=409)
    agent.staff_action("claim", ref)
    assert "[email]" in agent.request(f"/api/staff/ticket?ref={ref}")["summary"]
    agent.staff_action("reply", ref, "We checked your demo parcel.")
    agent.staff_action("resolve", ref)
    customer.task("ticket_status", "ask_ticket")
    answer = customer.chat(ref, event="ticket_read")
    assert ["Status", "Resolved"] in answer["rows"] and ["Support", "We checked your demo parcel."] in answer["rows"]
    other.staff("trail.admin", "2419")
    other.request(f"/api/staff/ticket?ref={ref}", code=409)
    other.staff_action("resolve", ref, code=409)
    return "Customer and assigned agent shared a redacted case. A foreign admin could neither read nor mutate it."


def dedup_handoff(s):
    c = s.client()
    ref = new_ticket(c)
    c.task("request_human", "ask_category")
    c.chat("Other", event="ask_details")
    c.chat("Follow up with the same support agent.", event="review")
    assert c.chat("Confirm", event="confirmed")["reference"] == ref
    assert s.scalar("SELECT COUNT(*) FROM tickets") == 1
    assert s.scalar("SELECT COUNT(*) FROM activity WHERE event='handoff'") == 1
    return "A repeated handoff linked the same open case and counted one new escalation."


def staff_roles(s):
    c, peer, customer = s.client(), s.client(), s.client()
    ref = new_ticket(customer)
    c.staff("trail.agent", "2411", 403)
    c.staff("nook.agent", "2411")
    c.staff_action("claim", ref)
    c.request("/api/staff/metrics", code=403)
    peer.staff("nook.agent2", "2412")
    assert peer.request("/api/staff/queue")["tickets"] == []
    peer.staff_action("resolve", ref, code=409)
    assert s.scalar("SELECT status FROM tickets WHERE ref=?", ref) == "In progress"
    return "Tenant and role checks excluded a foreign credential, and another agent could not update the assigned ticket."


def metrics(s):
    a, b = s.client(), s.client("trail")
    new_ticket(a)
    a.staff("nook.admin", "2419")
    report = a.request("/api/staff/metrics")
    assert report["chat_turns"] == 6 and report["workflow_completions"] == report["workflow_starts"] == 1
    assert report["handoff_created"] == 1 and report["p95_ms"] > 0
    b.staff("trail.admin", "2419")
    assert b.request("/api/staff/metrics")["chat_turns"] == 0
    return "Admin analytics published the activity counts and denominator for only the active tenant."


def persistence(s):
    c = s.client()
    collect_cancel(c, "ORD-2407")
    c.chat("Confirm", event="confirmed")
    renewed = Scenario(s.repo.path)
    with renewed.start():
        new = renewed.client()
        new.task("track_order", "ask_identity")
        new.verify()
        assert ["Status", "Cancelled"] in new.chat("ORD-2407", event="order_tracked")["rows"]
    return "A separate HTTP server and fresh browser session read the saved cancellation."


def audit(s):
    c = s.client()
    ref = new_ticket(c)
    with s.repo.read() as db:
        row = dict(db.execute("SELECT * FROM audit WHERE target=?", (ref,)).fetchone())
        assert "DEMO101" not in str(row) and "example.com" not in str(row) and row["correlation"]
        try:
            db.execute("UPDATE audit SET outcome='altered' WHERE target=?", (ref,))
        except Exception as exc:
            assert "append only" in str(exc)
        else:
            raise AssertionError("audit was mutable")
    return "Auditing stored pseudonym, target and correlation, and the database rejected in-place edits."


def context(s):
    c = s.client()
    c.task("track_order", "ask_identity")
    c.verify()
    c.chat("ORD-2404", event="order_tracked")
    assert c.chat("Check my refund status on that order", event="refund_read")["reference"] == "ORD-2404"
    c.session("nook")
    c.chat("Check my refund status on that order", event="ask_identity")
    assert c.verify()["stage"] == "order"
    return "The remembered order resolved only inside its verified session. Reset removed that context."


def fallback(s):
    c = s.client()
    c.chat("🪐", event="fallback")
    assert "Talk to an agent" in c.chat("🌧", event="fallback")["options"]
    assert s.scalar("SELECT COUNT(*) FROM operations") == 0
    return "Repeated unrelated inputs offered human support without opening a case automatically."


def stub_contract(path):
    seen = []

    class Stub(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/model/parse"
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            raw = b'{"intent":{"name":"track_order","confidence":0.97}}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    scenario = None
    with ThreadingHTTPServer(("127.0.0.1", 0), Stub) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
        try:
            scenario = Scenario(path, nlu=RasaNLU(f"http://127.0.0.1:{server.server_port}/model/parse"))
            with scenario.start():
                client = scenario.client()
                client.chat("Track an order for example@example.com", event="ask_identity")
                client.verify()
                client.chat("ORD-2401", event="order_tracked")
            assert seen == [{"text": "Track an order for [email]"}], seen
        finally:
            server.shutdown()
            thread.join()
    return scenario, "The local parse stub received one redacted opening turn. Verification and order fields stayed local."


CASES = [
    ("Interface", "Browser bootstrap and origin guard", bootstrap),
    ("Catalogue", "Facets and store-specific search", catalogue),
    ("Catalogue", "Product search and comparison", compare),
    ("Orders", "Typed track request and shipment record", tracked),
    ("Isolation", "Anonymous and other-customer order denial", cross_customer),
    ("Isolation", "Tenant switch and colliding order reference", switch),
    ("Verification", "OTP scope, cooldown, expiry and lock", otp),
    ("Verification", "Expired verified grant and saved reply", expired),
    ("Orders", "Confirmed cancellation and replay", cancellation),
    ("Orders", "Dispatched order and discarded draft", cancel_locked),
    ("Orders", "Concurrent cancellation confirmation", race),
    ("Orders", "Delivery preference validation", modify),
    ("After-sales", "Replacement intake and status", returned),
    ("After-sales", "Different return windows across stores", return_window),
    ("After-sales", "Personalised line exclusion", exclusions),
    ("After-sales", "Provider refund status is read-only", refund),
    ("Orders", "Provider outage and retry", provider_offline),
    ("Knowledge", "Tenant citations for the same policy question", cite_policy),
    ("Knowledge", "Missing and conflicting policy evidence", conflict),
    ("Support", "Agent claim, reply, resolution and tenant denial", support),
    ("Support", "Duplicate human handoff", dedup_handoff),
    ("Support", "Staff role and assignment checks", staff_roles),
    ("Analytics", "Scoped counters and p95", metrics),
    ("Audit", "Pseudonymous append-only audit", audit),
    ("Orders", "Restart persistence", persistence),
    ("Interface", "Verified order follow-up and reset", context),
    ("Interface", "Repeated fallback recovery", fallback),
    ("Interface", "Rasa parse adapter contract", stub_contract),
]


def run_case(group, name, execute):
    with TemporaryDirectory(prefix="commerce-eval-") as directory:
        db = Path(directory) / "demo.sqlite3"
        scenario = None
        try:
            if execute is stub_contract:
                scenario, observed = execute(db)
            else:
                scenario = Scenario(db, ["nook"] if execute is provider_offline else ())
                with scenario.start():
                    observed = execute(scenario)
            status = "PASS"
        except Exception as problem:
            status, observed = "FAIL", f"{type(problem).__name__}: {problem}"
        return {"group": group, "name": name, "status": status, "observed": observed,
                "timings": scenario.timings if scenario else [], "transcript": scenario.traces if scenario else []}


def run_cases():
    return [run_case(*case) for case in CASES]
