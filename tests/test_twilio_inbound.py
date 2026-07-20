"""
Tests for the inbound Twilio SMS webhook (api/routes/twilio_inbound.py) — no
database (FakeConn) and no real Twilio (the RequestValidator is stubbed where
the route lazily imports it).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.twilio_inbound as ti
from api.deps import get_db
from api.routes.twilio_inbound import normalize_phone, EMPTY_TWIML


# ── normalize_phone ───────────────────────────────────────────────────────────

def test_normalize_phone_variants():
    assert normalize_phone("+1 (713) 555-0142") == "7135550142"
    assert normalize_phone("7135550142") == "7135550142"
    assert normalize_phone("17135550142") == "7135550142"
    assert normalize_phone("+17135550142") == "7135550142"
    assert normalize_phone("555-0142") == "5550142"      # 7 digits still usable
    assert normalize_phone("12345") == ""                # too short to be a phone
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""


# ── Webhook route ─────────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.conn.executed.append((sql, params))
        if sql.startswith("SELECT id, account_id FROM tracking_numbers"):
            self._rows = [(7, 3)] if self.conn.tracking else []
        elif sql.startswith("SELECT p.id FROM properties"):
            self._rows = [(42,)] if self.conn.match else []
        elif sql.startswith("INSERT INTO properties"):
            self._rows = [(99,)]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, match=True, tracking=False):
        self.match = match
        self.tracking = tracking
        self.executed = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class FakeValidator:
    result = True

    def __init__(self, token):
        pass

    def validate(self, url, params, signature):
        return FakeValidator.result


def make_client(conn):
    app = FastAPI()
    app.include_router(ti.public_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: conn
    return TestClient(app)


FORM = {"From": "+17135550142", "To": "+18325550100",
        "Body": "Yes, next Tuesday works", "MessageSid": "SM123"}


def _setup(monkeypatch, *, configured=True, valid_sig=True):
    monkeypatch.setattr(ti, "sms_configured", lambda: configured)
    if not configured:
        monkeypatch.setattr(ti, "TWILIO_ACCOUNT_SID", "")
    FakeValidator.result = valid_sig
    monkeypatch.setattr("twilio.request_validator.RequestValidator", FakeValidator)


def test_unconfigured_returns_403(monkeypatch):
    _setup(monkeypatch, configured=False)
    resp = make_client(FakeConn()).post("/api/public/twilio/sms", data=FORM)
    assert resp.status_code == 403


def test_invalid_signature_returns_403(monkeypatch):
    _setup(monkeypatch, valid_sig=False)
    conn = FakeConn()
    resp = make_client(conn).post("/api/public/twilio/sms", data=FORM)
    assert resp.status_code == 403
    assert conn.executed == []


def test_matched_message_is_logged_as_inbound(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(match=True)
    resp = make_client(conn).post("/api/public/twilio/sms", data=FORM)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/xml")
    assert resp.text == EMPTY_TWIML

    inserts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO contact_history")]
    (sql, params), = inserts
    assert "'inbound'" in sql
    # Twilio retries deliveries — the MessageSid dedupe rides ON CONFLICT.
    assert "ON CONFLICT (external_id) DO NOTHING" in sql
    assert params == (42, "Yes, next Tuesday works", "SM123")


def test_unmatched_sender_still_returns_empty_twiml(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(match=False)
    resp = make_client(conn).post("/api/public/twilio/sms", data=FORM)
    assert resp.status_code == 200
    assert resp.text == EMPTY_TWIML
    assert not any(s.startswith("INSERT") for s, _ in conn.executed)


# ── Tracking-number tenancy (SMS to a per-account number) ─────────────────────

def test_tracking_number_scopes_match_to_account(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(match=True, tracking=True)
    resp = make_client(conn).post("/api/public/twilio/sms", data=FORM)

    assert resp.status_code == 200
    matches = [(s, p) for s, p in conn.executed if s.startswith("SELECT p.id FROM properties")]
    (sql, params), = matches
    assert "p.account_id" in sql and params["account_id"] == 3
    # Known sender: no lead insert, just the history row against record 42.
    assert not any(s.startswith("INSERT INTO properties") for s, _ in conn.executed)
    (hist,) = [p for s, p in conn.executed if s.startswith("INSERT INTO contact_history")]
    assert hist[0] == 42


def test_unknown_sender_on_tracking_number_becomes_lead(monkeypatch):
    _setup(monkeypatch)
    conn = FakeConn(match=False, tracking=True)
    resp = make_client(conn).post("/api/public/twilio/sms", data=FORM)

    assert resp.status_code == 200
    assert resp.text == EMPTY_TWIML
    (lead_sql, lead_params), = [(s, p) for s, p in conn.executed
                                if s.startswith("INSERT INTO properties")]
    assert lead_params[0] == 3                      # the tracking number's account
    assert lead_params[2] == "+17135550142"         # contact_phone
    assert lead_params[4] == "inbound_sms"          # lead_source
    (hist,) = [p for s, p in conn.executed if s.startswith("INSERT INTO contact_history")]
    assert hist == (99, "Yes, next Tuesday works", "SM123")
