"""Tests for the inbound Twilio voice webhook (api/routes/twilio_voice.py),
focused on the Versium reverse phone append: an unknown caller's lead should
gain address/name/email, once per caller, without ever blocking the forward.

Same harness as tests/test_twilio_inbound.py — FakeConn records SQL, no real
Twilio (RequestValidator stubbed) and no real Versium (append monkeypatched).
"""
import psycopg2.extras
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.twilio_voice as tv
import pipeline.contact
from api.deps import get_db


TRACKING_ROW = (7, 3, "+15550001111")  # id, account_id, forward_to

# lead_row shape for the append helper's SELECT:
# (address, city, state, zip, contact_name, contact_email, enrichment_flags)
NEW_LEAD_ROW = (None, None, None, None, "Caller (713) 555-0142", None,
                {"source": "call_tracking"})

VERSIUM_HIT = {
    "contact_name": "Greta Fisher",
    "contact_email": "g@example.com",
    "address": "123 Main St",
    "city": "Humble",
    "state": "TX",
    "zip": "77396",
}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.conn.executed.append((sql, params))
        if sql.startswith("SELECT id, account_id, forward_to FROM tracking_numbers"):
            self._rows = [TRACKING_ROW] if self.conn.tracking else []
        elif sql.startswith("SELECT p.id FROM properties"):
            self._rows = [(42,)] if self.conn.match else []
        elif sql.startswith("INSERT INTO calls"):
            self._rows = [(1,)]
        elif sql.startswith("INSERT INTO properties"):
            self._rows = [(99,)]
        elif sql.startswith("SELECT address, city, state, zip, contact_name"):
            self._rows = [self.conn.lead_row] if self.conn.lead_row else []
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, match=False, tracking=True, lead_row=NEW_LEAD_ROW):
        self.match = match
        self.tracking = tracking
        self.lead_row = lead_row
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


FORM = {"CallSid": "CA123", "From": "+17135550142", "To": "+18325550100",
        "CallerName": ""}


def make_client(conn):
    app = FastAPI()
    app.include_router(tv.public_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: conn
    return TestClient(app)


def _setup(monkeypatch, *, provider="versium", append=VERSIUM_HIT):
    monkeypatch.setattr(tv, "voice_configured", lambda: True)
    monkeypatch.setattr(tv, "PHONE_APPEND_PROVIDER", provider)
    monkeypatch.setattr(tv, "PHONE_APPEND_API_KEY", "test-key" if provider else "")
    FakeValidator.result = True
    monkeypatch.setattr("twilio.request_validator.RequestValidator", FakeValidator)
    calls = []
    def fake_append(digits):
        calls.append(digits)
        if isinstance(append, Exception):
            raise append
        return append
    # The route calls the provider-agnostic dispatcher, so that's the seam to
    # stub — PHONE_APPEND_PROVIDERS captures the real functions at import time.
    monkeypatch.setattr(pipeline.contact, "phone_append", fake_append)
    return calls


def _property_updates(conn):
    return [(s, p) for s, p in conn.executed if s.startswith("UPDATE properties")]


def _flag_param(params):
    (flag,) = [p for p in params if isinstance(p, psycopg2.extras.Json)]
    return flag.adapted


# ── New lead from an unknown caller ──────────────────────────────────────────

def test_unknown_caller_lead_gets_address_append(monkeypatch):
    calls = _setup(monkeypatch)
    conn = FakeConn(match=False)
    resp = make_client(conn).post("/api/public/twilio/voice", data=FORM)

    assert resp.status_code == 200
    assert "<Dial" in resp.text  # the call still forwards
    assert calls == ["7135550142"]

    (sql, params), = _property_updates(conn)
    for col in ("address = %s", "city = %s", "state = %s", "zip = %s",
                    "contact_email = %s", "contact_name = %s"):
        assert col in sql
    for value in ("123 Main St", "Humble", "TX", "77396",
                  "g@example.com", "Greta Fisher"):
        assert value in params
    # Attempt is flagged so a repeat call never re-spends; existing flags kept.
    flags = _flag_param(params)
    assert flags["phone_append"] == "versium"
    assert flags["source"] == "call_tracking"
    assert params[-2:] == (99, 3)  # the new lead id, the tracking number's account


def test_no_match_still_flags_the_attempt(monkeypatch):
    _setup(monkeypatch, append=None)
    conn = FakeConn(match=False)
    resp = make_client(conn).post("/api/public/twilio/voice", data=FORM)

    assert resp.status_code == 200
    (sql, params), = _property_updates(conn)
    assert "address = %s" not in sql  # nothing found — but the query was paid for
    assert _flag_param(params)["phone_append"] == "versium"


# ── Matched (existing) leads ──────────────────────────────────────────────────

def test_matched_lead_with_address_skips_append(monkeypatch):
    calls = _setup(monkeypatch)
    conn = FakeConn(match=True, lead_row=("1 Main St", "Humble", "TX", "77396",
                                          "Jane Doe", None, {}))
    resp = make_client(conn).post("/api/public/twilio/voice", data=FORM)

    assert resp.status_code == 200
    assert calls == []
    assert _property_updates(conn) == []


def test_matched_lead_without_address_gets_one_attempt(monkeypatch):
    calls = _setup(monkeypatch)
    conn = FakeConn(match=True, lead_row=(None, None, None, None,
                                          "Jane Doe", None, {}))
    resp = make_client(conn).post("/api/public/twilio/voice", data=FORM)

    assert resp.status_code == 200
    assert calls == ["7135550142"]
    (sql, params), = _property_updates(conn)
    assert "address = %s" in sql
    # A real name already on the lead is never overwritten.
    assert "contact_name = %s" not in sql
    assert "Greta Fisher" not in params


def test_matched_lead_already_flagged_skips_append(monkeypatch):
    calls = _setup(monkeypatch)
    conn = FakeConn(match=True, lead_row=(None, None, None, None, "Jane Doe",
                                          None, {"phone_append": "versium"}))
    resp = make_client(conn).post("/api/public/twilio/voice", data=FORM)

    assert resp.status_code == 200
    assert calls == []
    assert _property_updates(conn) == []


# ── Guards ────────────────────────────────────────────────────────────────────

def test_unconfigured_provider_skips_append(monkeypatch):
    calls = _setup(monkeypatch, provider="")
    conn = FakeConn(match=False)
    resp = make_client(conn).post("/api/public/twilio/voice", data=FORM)

    assert resp.status_code == 200
    assert "<Dial" in resp.text
    assert calls == []
    assert _property_updates(conn) == []


def test_append_failure_still_forwards_call(monkeypatch):
    _setup(monkeypatch, append=RuntimeError("versium down"))
    conn = FakeConn(match=False)
    resp = make_client(conn).post("/api/public/twilio/voice", data=FORM)

    assert resp.status_code == 200
    assert "<Dial" in resp.text
    assert conn.rollbacks >= 1
