"""Bound demo sessions, one-time verification and tenant staff roles."""

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import hmac
import re
from secrets import randbelow, token_bytes, token_urlsafe
from threading import Lock, RLock
from time import monotonic

from .store import Scope, actor_tag


OTP_TTL = 300
GRANT_TTL = 600
IDLE_TTL = 1800
STAFF = {"agent": ("agent", "2411"), "agent2": ("agent", "2412"), "admin": ("admin", "2419")}


def scrub(text):
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email]", text)
    return re.sub(r"(?<!\w)\+?\d(?:[ ().-]*\d){5,}(?!\w)", "[number]", text)


@dataclass
class Session:
    key: str
    tenant: str
    touched: float
    tag: str = field(default_factory=lambda: token_urlsafe(10))
    scope: Scope | None = None
    verified_until: float = 0
    pending: dict | None = None
    draft: dict | None = None
    last_order: str | None = None
    fallback_count: int = 0
    locked_until: float = 0
    failures: int = 0
    last_issue: float = -1e9
    recent_issues: list = field(default_factory=list)
    staff_failures: int = 0
    staff_lock: float = 0
    closed: bool = False
    cache: OrderedDict = field(default_factory=OrderedDict)
    last_reply: tuple | None = None
    guard: object = field(default_factory=RLock)


class Sessions:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.secret = token_bytes(32)
        self.table = {}
        self.guard = Lock()

    def new(self, tenant):
        now = self.clock()
        with self.guard:
            expired = [k for k, value in self.table.items() if now - value.touched >= IDLE_TTL]
            for key in expired:
                self.table.pop(key)
            if len(self.table) >= 500:
                raise OverflowError("Too many active demo sessions. Try again later.")
            session = Session(token_urlsafe(32), tenant, now)
            self.table[session.key] = session
        return session

    def get(self, key):
        with self.guard:
            session = self.table.get(key)
            if session and not session.closed and self.clock() - session.touched < IDLE_TTL:
                session.touched = self.clock()
                return session
        return None

    def drop(self, session):
        if session:
            with session.guard:
                session.closed = True
                session.scope = session.draft = session.pending = None
                session.cache.clear()
                session.last_reply = None
                with self.guard:
                    self.table.pop(session.key, None)

    def grant(self, session):
        if session.closed or session.scope is None or self.clock() >= session.verified_until:
            return None
        return session.scope

    def digest(self, session, challenge, code):
        return hmac.digest(self.secret, f"{session.tenant}:{session.key}:{challenge}:{code}".encode(), hashlib.sha256)

    def issue(self, session, matching):
        now = self.clock()
        if now < session.locked_until:
            return "locked"
        if now - session.last_issue < 12:
            return "cooldown"
        session.recent_issues[:] = [when for when in session.recent_issues if now - when < OTP_TTL]
        if len(session.recent_issues) >= 4:
            return "issue_limit"
        session.recent_issues.append(now)
        nonce, code = token_urlsafe(10), f"{randbelow(1_000_000):06}"
        session.pending = {"nonce": nonce, "digest": self.digest(session, nonce, code), "issued": now,
                           "customer": matching, "demo_code": code if matching else None}
        session.last_issue = now
        return "issued"

    def inbox(self, session):
        pending = session.pending
        if pending is None:
            return {"code": None, "seconds": 0}
        seconds = max(0, int(OTP_TTL - (self.clock() - pending["issued"])))
        return {"code": pending["demo_code"] if seconds else None, "seconds": seconds}

    def verify(self, session, code):
        pending = session.pending
        now = self.clock()
        if now < session.locked_until:
            return "locked"
        if pending is None or now - pending["issued"] >= OTP_TTL:
            return "expired"
        if not re.fullmatch(r"[0-9]{6}", code):
            return "format"
        if hmac.compare_digest(self.digest(session, pending["nonce"], code), pending["digest"]) and pending["customer"]:
            session.scope = Scope(session.tenant, pending["customer"], "customer")
            session.pending = None
            session.failures = 0
            session.verified_until = now + GRANT_TTL
            return "verified"
        session.failures += 1
        if session.failures >= 3:
            session.pending = None
            session.locked_until = now + OTP_TTL
            session.failures = 0
            return "locked"
        return "wrong"

    def staff(self, session, user, pin):
        now = self.clock()
        if now < session.staff_lock:
            raise ValueError("Staff sign-in is temporarily locked for this session.")
        local = user.removeprefix(session.tenant + ".") if user.startswith(session.tenant + ".") else ""
        role, expected = STAFF.get(local, (None, "xxxx"))
        if not hmac.compare_digest(pin.encode(), expected.encode()) or role is None:
            session.staff_failures += 1
            if session.staff_failures >= 5:
                session.staff_lock = now + 300
                session.staff_failures = 0
            raise ValueError("Use the staff demo credential for the active store.")
        session.scope = Scope(session.tenant, user, role)
        session.verified_until = now + GRANT_TTL
        session.staff_failures = 0
        session.draft = session.pending = session.last_order = None
        session.cache.clear()
        session.last_reply = None
        return {"role": role, "label": user, "tag": actor_tag(session.scope)}
