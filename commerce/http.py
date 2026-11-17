"""Loopback browser gateway with same-origin JSON and opaque session cookies."""

from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from time import perf_counter
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from .auth import scrub
from .fixtures import SERVICES, STORES, money
from .engine import TICKET
from .store import ProviderUnavailable, Rejected


COOKIE = "commerce_demo"


class HttpProblem(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def make_server(root, desk, port, host="127.0.0.1"):
    repo, sessions = desk.repo, desk.sessions
    assets = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/static/style.css": ("style.css", "text/css; charset=utf-8"),
        "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def write_response(self, payload, status, kind, session=None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if session:
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower() == "https" else ""
                self.send_header("Set-Cookie", f"{COOKIE}={session.key}; Path=/; HttpOnly; SameSite=Strict{secure}")
            self.end_headers()
            self.wfile.write(payload)

        def json(self, payload, status=200, session=None):
            self.write_response(json.dumps(payload, ensure_ascii=False).encode(), status, "application/json; charset=utf-8", session)

        def current(self):
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            return sessions.get(cookie[COOKIE].value) if COOKIE in cookie else None

        def body(self):
            length = self.headers.get("Content-Length", "0")
            if not length.isdecimal() or len(length) > 5 or not 0 < int(length) <= 8192:
                raise HttpProblem(413, "Invalid request body length.")
            if self.headers.get_content_type() != "application/json":
                raise HttpProblem(415, "Send a JSON request.")
            data = json.loads(self.rfile.read(int(length)))
            if not isinstance(data, dict):
                raise HttpProblem(400, "Expected a JSON object.")
            return data

        def guard(self):
            # Render terminates TLS at its edge and forwards the original scheme in
            # X-Forwarded-Proto. The browser Origin must still match this host/scheme.
            host = self.headers.get("Host", "")
            if not host or any(char in host for char in "\r\n /\\"):
                raise HttpProblem(400, "A valid host header is required.")
            forwarded = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip().lower()
            scheme = "https" if forwarded == "https" else "http"
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"{scheme}://{host}":
                raise HttpProblem(403, "Cross-origin requests are unavailable.")
            if self.headers.get("Sec-Fetch-Site") == "cross-site" and self.command == "POST":
                raise HttpProblem(403, "Cross-origin requests are unavailable.")

        def snapshot(self, session):
            scope = sessions.grant(session)
            reply = None
            if session.last_reply:
                saved_reply, required = session.last_reply
                if required is None or required == scope:
                    reply = saved_reply
            return {"tenant": session.tenant, "stores": [dict(id=tenant, name=values["name"], specialty=values["specialty"])
                                                          for tenant, values in STORES.items()],
                    "services": SERVICES, "profiles": repo.customers(session.tenant),
                    "role": scope.role if scope else "guest", "user": scope.subject if scope else None,
                    "model": desk.nlu.name, "stage": session.draft["stage"] if session.draft else "menu", "reply": reply}

        def switch(self, session, tenant):
            if not isinstance(tenant, str) or tenant not in STORES:
                raise HttpProblem(400, "Choose one of the two demo stores.")
            fresh = sessions.new(tenant)
            sessions.drop(session)
            desk.signal(fresh, "session_start")
            self.json(self.snapshot(fresh), session=fresh)

        def handle_request(self):
            self.guard()
            url = urlsplit(self.path)
            route = url.path
            if self.command == "GET" and route in assets:
                file, kind = assets[route]
                return self.write_response((root / "static" / file).read_bytes(), 200, kind)
            if self.command == "GET" and route == "/api/health":
                return self.json({"status": "ready", "mode": "synthetic demo", "model": desk.nlu.name})
            session = self.current()
            if route == "/api/session":
                if self.command == "POST":
                    return self.switch(session, self.body().get("tenant"))
                if not session:
                    return self.switch(None, "nook")
                with session.guard:
                    if session.closed:
                        raise HttpProblem(401, "Reload to open a demo session.")
                    return self.json(self.snapshot(session))
            if not session:
                raise HttpProblem(401, "Open a demo session first.")
            with session.guard:
                if session.closed:
                    raise HttpProblem(401, "Reload to open a demo session.")
                if self.command == "POST":
                    return self.post(route, session, self.body())
                return self.get(route, session, parse_qs(url.query, max_num_fields=12))

        def get(self, route, session, query):
            scope = sessions.grant(session)
            if route == "/api/catalogue":
                def param(key):
                    return query.get(key, [""])[0][:120]
                maximum = param("max")
                if maximum and (not maximum.isascii() or not maximum.isdecimal() or len(maximum) > 6):
                    raise HttpProblem(400, "Enter a whole-rupee maximum from 0 to 999999.")
                products = repo.catalogue(session.tenant, param("q"), param("category"), param("brand"),
                                          int(maximum) * 100 if maximum else None, param("available") == "1")
                return self.json({"products": desk.public_products(products)})
            if route == "/api/inbox":
                return self.json(sessions.inbox(session))
            if route == "/api/orders":
                self.need(scope, "customer")
                return self.json({"orders": [{**order, "total_label": money(order["total"])} for order in desk.provider.orders(scope)]})
            if route == "/api/staff/queue":
                self.need(scope, "agent", "admin")
                return self.json({"tickets": repo.staff_tickets(scope)})
            if route == "/api/staff/ticket":
                self.need(scope, "agent", "admin")
                return self.json(repo.staff_ticket(scope, query.get("ref", [""])[0][:24]))
            if route == "/api/staff/metrics":
                self.need(scope, "admin")
                return self.json(repo.analytics(scope))
            raise HttpProblem(404, "That API route is unavailable.")

        @staticmethod
        def need(scope, *roles):
            if not scope or scope.role not in roles:
                raise HttpProblem(403, "This resource requires the appropriate verified role.")

        @staticmethod
        def request_id(data):
            try:
                return UUID(str(data.get("request_id"))).hex
            except (AttributeError, ValueError) as error:
                raise HttpProblem(400, "Supply a valid request ID.") from error

        def post(self, route, session, data):
            if route == "/api/staff/login":
                user, pin = data.get("user"), data.get("pin")
                if not isinstance(user, str) or not isinstance(pin, str) or len(user) > 32 or len(pin) != 4:
                    raise HttpProblem(400, "Enter the staff ID and four-digit demo PIN.")
                try:
                    sessions.staff(session, user.strip(), pin)
                except ValueError as error:
                    raise HttpProblem(403, str(error)) from error
                return self.json(self.snapshot(session))
            if route == "/api/staff/action":
                role = sessions.grant(session)
                self.need(role, "agent", "admin")
                reference, verb, message = data.get("reference"), data.get("action"), data.get("message", "")
                if not isinstance(reference, str) or not TICKET.fullmatch(reference) or not isinstance(verb, str) or not isinstance(message, str):
                    raise HttpProblem(400, "Enter a ticket reference, action and message.")
                return self.json(repo.update_ticket(role, self.request_id(data), verb, reference, scrub(message)))
            if route != "/api/chat":
                raise HttpProblem(404, "That API route is unavailable.")
            text, shortcut = data.get("text"), data.get("shortcut")
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 400:
                raise HttpProblem(400, "Send 1 to 400 characters of text.")
            if shortcut is not None and (not isinstance(shortcut, str) or SERVICES.get(shortcut) != text.strip()):
                raise HttpProblem(400, "Choose a known task label.")
            request = self.request_id(data)
            text = text.strip()
            scope = sessions.grant(session)
            # Preserve a one-way match for retries without retaining raw verification inputs.
            request_digest = sessions.digest(session, request, json.dumps([text, shortcut], ensure_ascii=False))
            saved = session.cache.get(request)
            if saved:
                previous, response, required = saved
                if previous != request_digest:
                    raise HttpProblem(409, "This request ID was already used with different input.")
                if required is not None and required != scope:
                    raise HttpProblem(403, "Verification is required to reopen that response.")
                return self.json({**response, "replayed": True})
            start = perf_counter()
            response = desk.send(session, text, shortcut)
            ms = round((perf_counter() - start) * 1000, 3)
            desk.signal(session, "turn", response["event"], ms)
            required = sessions.grant(session) if response.pop("protected") else None
            response.update(server_ms=ms, verified=bool(required and required.role == "customer"))
            session.cache[request] = (request_digest, response, required)
            session.last_reply = (response, required)
            if len(session.cache) > 64:
                session.cache.popitem(last=False)
            self.json(response)

        def safe(self):
            try:
                self.handle_request()
            except HttpProblem as problem:
                self.json({"error": problem.message}, problem.code)
            except ProviderUnavailable as problem:
                self.json({"error": str(problem)}, 503)
            except Rejected as problem:
                self.json({"error": str(problem)}, 409)
            except (UnicodeError, ValueError, TypeError):
                self.json({"error": "The request is malformed."}, 400)
            except OverflowError as problem:
                self.json({"error": str(problem)}, 503)
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = do_POST = safe

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
