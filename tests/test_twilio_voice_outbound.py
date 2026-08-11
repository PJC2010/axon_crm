"""Tests for the power dialer's public webhooks (api/routes/twilio_voice.py):
the outbound TwiML endpoint the TwiML App calls, and its <Dial action> status
callback.

The security promise being tested: the browser supplies only a lead_id — the
webhook re-verifies the token identity against the users table and resolves
the phone from that account's own lead, so a forged identity, cross-tenant
lead, or do-not-call lead gets a spoken reject (2xx TwiML, zero side effects),
never a dial. Same harness as tests/test_twilio_voice.py — FakeConn records
SQL, RequestValidator stubbed, no real Twilio.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.twilio_voice as tv
from api.deps import get_db


USER_ROW = (3, True)                        # account_id, is_active
LEAD_ROW = ("(713) 555-0142", "713-555-0199", False)  # phone, alt, do_not_call
TRACKING_ROW = (7, "+18325550100")          # id, phone_number

FORM = {"CallSid": "CA900", "From": "client:axon-3-9", "lead_id": "42",
        "phone_choice": "primary"}

STATUS_FORM = {"CallSid": "CA900", "DialCallStatus": "no-answer",
               "DialCallDuration": ""}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.conn.executed.append((sql, params))
        if sql.startswith("SELECT account_id, is_active FROM users"):
            self._rows = [self.conn.user_row] if self.conn.user_row else []
        elif sql.startswith("SELECT contact_phone, contact_phone_alt, do_not_call FROM properties"):
            self._rows = [self.conn.lead_row] if self.conn.lead_row else []
        elif sql.startswith("SELECT id, phone_number FROM tracking_numbers"):
            self._rows = [TRACKING_ROW] if self.conn.tracking else []
        elif sql.startswith("INSERT INTO calls"):
            self._rows = [] if self.conn.call_exists else [(1,)]
        elif sql.startswith("UPDATE calls SET status = 'completed'"):
            self._rows = [(3, 42)] if self.conn.update_hits else []
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, *, user_row=USER_ROW, lead_row=LEAD_ROW, tracking=True,
                 call_exists=False, update_hits=True):
        self.user_row = user_row
        self.lead_row = lead_row
        self.tracking = tracking
        self.call_exists = call_exists
        self.update_hits = update_hits
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeValidator:
    result = True

    def __init__(self, token):
        pass

    def validate(self, url, params, signature):
        return FakeValidator.result


def make_client(conn):
    app = FastAPI()
    app.include_router(tv.public_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: conn
    return TestClient(app)


def _setup(monkeypatch, *, configured=True):
    monkeypatch.setattr(tv, "dialer_configured", lambda: configured)
    FakeValidator.result = True
    monkeypatch.setattr("twilio.request_validator.RequestValidator", FakeValidator)
    # Sentinel: neither webhook may emit feedback events — that is the
    # disposition endpoint's job.
    emitted = []
    monkeypatch.setattr(tv, "emit_event", lambda *a, **k: emitted.append((a, k)))
    return emitted


def _sqls(conn, prefix):
    return [s for s, _ in conn.executed if s.startswith(prefix)]


# ── POST /public/twilio/voice/outbound — guards ───────────────────────────────

def test_unconfigured_is_403(monkeypatch):
    _setup(monkeypatch, configured=False)
    resp = make_client(FakeConn()).post("/api/public/twilio/voice/outbound", data=FORM)
    assert resp.status_code == 403


def test_bad_signature_is_403(monkeypatch):
    _setup(monkeypatch)
    FakeValidator.result = False
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    assert resp.status_code == 403
    assert conn.executed == []


def _assert_rejected(conn, resp):
    # Business-level refusal: 200 spoken TwiML, no dial, no writes.
    assert resp.status_code == 200
    assert "<Say>" in resp.text and "<Dial" not in resp.text
    assert _sqls(conn, "INSERT") == []


def test_unparseable_identity_rejects(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound",
                                  data={**FORM, "From": "client:evil"})
    _assert_rejected(conn, resp)


def test_non_numeric_lead_id_rejects(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound",
                                  data={**FORM, "lead_id": "42; DROP"})
    _assert_rejected(conn, resp)


def test_identity_account_mismatch_rejects(monkeypatch):
    # Token says account 3 but the user actually belongs to account 8.
    _setup(monkeypatch)
    conn = FakeConn(user_row=(8, True))
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    _assert_rejected(conn, resp)


def test_inactive_user_rejects(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(user_row=(3, False))
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    _assert_rejected(conn, resp)


def test_unknown_lead_rejects(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(lead_row=None)
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    _assert_rejected(conn, resp)
    # The lead lookup itself was account-scoped.
    (sql, params), = [(s, p) for s, p in conn.executed if "FROM properties" in s]
    assert "account_id = %s" in sql and params == (42, 3)


def test_do_not_call_lead_rejects(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(lead_row=("(713) 555-0142", None, True))
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    _assert_rejected(conn, resp)
    assert "do not call" in resp.text.lower()


def test_undialable_phone_rejects(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(lead_row=("555-0142", None, False))  # 7 digits — not dialable
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    _assert_rejected(conn, resp)


def test_no_caller_id_rejects(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr("config.TWILIO_FROM_NUMBER", "")
    conn = FakeConn(tracking=False)
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    _assert_rejected(conn, resp)


# ── POST /public/twilio/voice/outbound — happy paths ──────────────────────────

def test_dials_lead_and_logs_call(monkeypatch):
    emitted = _setup(monkeypatch)
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)

    assert resp.status_code == 200
    assert 'callerId="+18325550100"' in resp.text
    assert "<Number>+17135550142</Number>" in resp.text
    assert "outbound-status" in resp.text  # the Dial action callback

    (sql, params), = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO calls")]
    assert "'outbound'" in sql and "ON CONFLICT (call_sid) DO NOTHING" in sql
    assert params == (3, 42, 7, "CA900", "+18325550100", "8325550100",
                      "+17135550142", 9)

    (sql, params), = [(s, p) for s, p in conn.executed
                      if s.startswith("INSERT INTO contact_history")]
    assert "'Outbound call'" in sql and "'outbound'" in sql
    assert params == (42, "CA900", 9)
    assert conn.commits == 1
    assert emitted == []


def test_alt_phone_choice(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound",
                                  data={**FORM, "phone_choice": "alt"})
    assert "<Number>+17135550199</Number>" in resp.text


def test_platform_number_fallback_when_no_tracking_number(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr("config.TWILIO_FROM_NUMBER", "(346) 601-6971")
    conn = FakeConn(tracking=False)
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)
    assert 'callerId="+13466016971"' in resp.text
    (_, params), = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO calls")]
    assert params[2] is None  # no tracking_number_id


def test_retry_is_idempotent(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(call_exists=True)
    resp = make_client(conn).post("/api/public/twilio/voice/outbound", data=FORM)

    assert resp.status_code == 200
    assert "<Number>+17135550142</Number>" in resp.text  # same TwiML re-served
    assert _sqls(conn, "INSERT INTO contact_history") == []
    assert conn.rollbacks == 1 and conn.commits == 0


def test_no_callsid_still_dials_without_logging(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound",
                                  data={**FORM, "CallSid": ""})
    assert "<Dial" in resp.text
    assert _sqls(conn, "INSERT") == []


# ── POST /public/twilio/voice/outbound-status ─────────────────────────────────

def test_status_callback_completes_call(monkeypatch):
    emitted = _setup(monkeypatch)
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound-status",
                                  data=STATUS_FORM)

    assert resp.status_code == 200 and "<Hangup" in resp.text
    (sql, params), = [(s, p) for s, p in conn.executed if s.startswith("UPDATE calls")]
    assert "status <> 'completed'" in sql
    assert params == ("no_answer", None, "CA900")

    (sql, params), = [(s, p) for s, p in conn.executed
                      if s.startswith("UPDATE contact_history")]
    # The mechanical verdict only fills a gap — COALESCE keeps a human
    # disposition that already landed.
    assert "COALESCE(outcome, %s)" in sql
    assert params == ("Outbound call — no answer", "No answer", "CA900")

    # The inbound speed-to-lead plays must NOT fire for calls the rep placed:
    # no missed-call task, no call_event auto-text, no feedback event.
    assert _sqls(conn, "INSERT INTO tasks") == []
    assert _sqls(conn, "SELECT phone_number FROM tracking_numbers") == []
    assert emitted == []


def test_status_callback_answered_keeps_history_outcome_null(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn()
    make_client(conn).post("/api/public/twilio/voice/outbound-status",
                           data={"CallSid": "CA900", "DialCallStatus": "completed",
                                 "DialCallDuration": "134"})
    (sql, params), = [(s, p) for s, p in conn.executed if s.startswith("UPDATE calls")]
    assert params == ("answered", 134, "CA900")
    (_, params), = [(s, p) for s, p in conn.executed
                    if s.startswith("UPDATE contact_history")]
    # Answered-but-undisposed stays open for the rep's verdict.
    assert params == ("Outbound call — answered (2m 14s)", None, "CA900")


def test_duplicate_status_callback_is_noop(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(update_hits=False)
    resp = make_client(conn).post("/api/public/twilio/voice/outbound-status",
                                  data=STATUS_FORM)
    assert resp.status_code == 200 and "<Hangup" in resp.text
    assert _sqls(conn, "UPDATE contact_history") == []
    assert conn.rollbacks == 1 and conn.commits == 0


def test_status_callback_bad_signature_is_403(monkeypatch):
    _setup(monkeypatch)
    FakeValidator.result = False
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/voice/outbound-status",
                                  data=STATUS_FORM)
    assert resp.status_code == 403
    assert conn.executed == []
