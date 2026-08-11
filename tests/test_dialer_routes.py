"""Tests for the power dialer's authenticated half (api/routes/dialer.py):
the Voice-token mint, the A-first queue, and disposition logging.

Route functions are called directly with a fake conn + user dict (same style
as tests/test_calls_activate.py) — no DB, no Twilio REST.
"""
import pytest
from fastapi import HTTPException

import api.routes.dialer as dialer_route
from api import dialer_logic


USER = {"id": 9, "account_id": 3, "role": "owner"}

QUEUE_COLS = (
    "id", "contact_name", "owner_name", "address", "city", "zip",
    "contact_phone", "contact_phone_alt", "contact_email",
    "best_time_to_call", "preferred_contact_method", "vertical",
    "status", "lead_score", "score_grade", "estimated_job_value",
    "last_call_at", "last_disposition", "last_outcome",
)

def _queue_row(id_, grade, score, status="new"):
    return (id_, f"Lead {id_}", None, f"{id_} Main St", "Humble", "77396",
            "(713) 555-0142", None, None, None, None, "roofing",
            status, score, grade, 12000, None, None, None)

LEAD_ROW = ("new", "Jane Doe", "JANE DOE", "(713) 555-0142", "713-555-0199")


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self._cols = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def description(self):
        return [(c,) for c in self._cols]

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        c = self.conn
        c.executed.append((sql, list(params) if params is not None else None))
        self._rows, self._cols = [], ()

        if sql.startswith("SELECT COUNT(*) FROM properties p"):
            self._rows = [(len(c.queue_rows),)]
        elif sql.startswith("SELECT p.id, p.contact_name"):
            self._cols = QUEUE_COLS
            self._rows = list(c.queue_rows)
        elif sql.startswith("SELECT COUNT(*) AS calls_today"):
            self._rows = [(c.calls_today, c.connects_today)]
        elif sql.startswith("SELECT status, contact_name, owner_name"):
            self._rows = [c.lead_row] if c.lead_row else []
        elif sql.startswith("UPDATE calls SET disposition"):
            self._rows = [(10,)] if c.call_row_exists else []
        elif sql.startswith("INSERT INTO calls"):
            self._rows = [(11,)]
        elif sql.startswith("INSERT INTO tasks"):
            self._rows = [(33,)]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, *, queue_rows=(), lead_row=LEAD_ROW, call_row_exists=True,
                 calls_today=0, connects_today=0):
        self.queue_rows = list(queue_rows)
        self.lead_row = lead_row
        self.call_row_exists = call_row_exists
        self.calls_today = calls_today
        self.connects_today = connects_today
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def no_quota(monkeypatch):
    monkeypatch.setattr(dialer_route, "get_scoring_limit", lambda *a: None)
    surfaced = []
    monkeypatch.setattr(dialer_route, "emit_surfaced",
                        lambda db, ids, acct, **k: surfaced.append(list(ids)))
    monkeypatch.setattr(dialer_route, "dialer_configured", lambda: False)
    return surfaced


@pytest.fixture
def emitted(monkeypatch):
    events = []
    monkeypatch.setattr(dialer_route, "emit_event",
                        lambda db, lead, acct, event, **k: events.append((lead, event, k)))
    return events


# ── POST /dialer/token ────────────────────────────────────────────────────────

def test_token_503_when_unconfigured(monkeypatch):
    monkeypatch.setattr(dialer_route, "dialer_configured", lambda: False)
    with pytest.raises(HTTPException) as exc:
        dialer_route.mint_voice_token(current_user=USER)
    assert exc.value.status_code == 503


def test_token_carries_identity_and_voice_grant(monkeypatch):
    monkeypatch.setattr(dialer_route, "dialer_configured", lambda: True)
    monkeypatch.setattr("config.TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setattr("config.TWILIO_API_KEY_SID", "SK" + "0" * 32)
    monkeypatch.setattr("config.TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setattr("config.TWILIO_TWIML_APP_SID", "AP" + "0" * 32)

    out = dialer_route.mint_voice_token(current_user=USER)
    assert out["identity"] == "axon-3-9"
    assert out["ttl_seconds"] == 3600

    from jose import jwt as jose_jwt
    claims = jose_jwt.get_unverified_claims(out["token"])
    assert claims["grants"]["identity"] == "axon-3-9"
    assert claims["grants"]["voice"]["outgoing"]["application_sid"] == "AP" + "0" * 32
    assert "incoming" not in claims["grants"]["voice"]  # outgoing-only


# ── GET /dialer/queue ─────────────────────────────────────────────────────────

def test_queue_scoping_ordering_and_stats(no_quota):
    conn = FakeConn(queue_rows=[_queue_row(1, "A", 92), _queue_row(2, "B", 61)],
                    calls_today=5, connects_today=2)
    out = dialer_route.get_queue(grade=None, statuses="new,contacted",
                                 cooldown_hours=4, limit=25,
                                 current_user=USER, db=conn)

    assert [r["id"] for r in out["items"]] == [1, 2]
    assert out["total"] == 2
    assert out["masked_count"] == 0
    assert out["stats"] == {"calls_today": 5, "connects_today": 2}
    assert out["voice_dialing"] is False

    main_sql, main_params = next((s, p) for s, p in conn.executed
                                 if s.startswith("SELECT p.id"))
    # Account scoping + eligibility guards + A-first ordering, one statement.
    assert "p.account_id = %s" in main_sql
    assert "p.do_not_call = FALSE" in main_sql
    assert "p.archived_at IS NULL" in main_sql
    assert "ORDER BY p.score_grade ASC NULLS LAST, p.lead_score DESC NULLS LAST" in main_sql
    assert main_params[0] == 3 and main_params[-1] == 25

    stats_sql, stats_params = next((s, p) for s, p in conn.executed
                                   if "calls_today" in s)
    assert "direction = 'outbound'" in stats_sql
    assert stats_params == [list(dialer_logic.CONNECT_DISPOSITIONS), 3, 9]


def test_queue_grade_filter_propagates(no_quota):
    conn = FakeConn()
    dialer_route.get_queue(grade="A", statuses="new,contacted", cooldown_hours=4,
                           limit=25, current_user=USER, db=conn)
    sql, params = next((s, p) for s, p in conn.executed if s.startswith("SELECT p.id"))
    assert "p.score_grade = %s" in sql and "A" in params


def test_queue_bad_status_is_400(no_quota):
    with pytest.raises(HTTPException) as exc:
        dialer_route.get_queue(grade=None, statuses="new,prospect", cooldown_hours=4,
                               limit=25, current_user=USER, db=FakeConn())
    assert exc.value.status_code == 400


def test_queue_drops_quota_masked_rows(monkeypatch):
    monkeypatch.setattr(dialer_route, "dialer_configured", lambda: False)
    monkeypatch.setattr(dialer_route, "get_scoring_limit", lambda *a: 1)

    def fake_apply_quota(db, account_id, rows, limit):
        # Mask everything past the first row, the way scoring_quota does.
        out = [dict(r, quota_masked=True) if i >= limit else r
               for i, r in enumerate(rows)]
        return out, {"limit": limit, "used": limit, "remaining": 0}

    monkeypatch.setattr(dialer_route.scoring_quota, "apply_quota", fake_apply_quota)
    surfaced = []
    monkeypatch.setattr(dialer_route, "emit_surfaced",
                        lambda db, ids, acct, **k: surfaced.append(list(ids)))

    conn = FakeConn(queue_rows=[_queue_row(1, "A", 92), _queue_row(2, "A", 88)])
    out = dialer_route.get_queue(grade=None, statuses="new", cooldown_hours=0,
                                 limit=25, current_user=USER, db=conn)

    # The masked lead is dropped (its phone is withheld), counted, and never
    # marked as surfaced — the rep never saw it.
    assert [r["id"] for r in out["items"]] == [1]
    assert out["masked_count"] == 1
    assert out["scoring_quota"]["remaining"] == 0
    assert surfaced == [[1]]


# ── POST /dialer/dispositions ─────────────────────────────────────────────────

def _body(**kw):
    return dialer_route.DispositionCreate(**{"lead_id": 42, "disposition": "no_answer", **kw})


def test_invalid_disposition_is_400(emitted):
    with pytest.raises(HTTPException) as exc:
        dialer_route.log_disposition(
            dialer_route.DispositionCreate(lead_id=42, disposition="ghosted"),
            current_user=USER, db=FakeConn())
    assert exc.value.status_code == 400


def test_unknown_lead_is_404(emitted):
    with pytest.raises(HTTPException) as exc:
        dialer_route.log_disposition(_body(), current_user=USER, db=FakeConn(lead_row=None))
    assert exc.value.status_code == 404


def test_browser_mode_annotates_existing_call(emitted):
    conn = FakeConn()
    out = dialer_route.log_disposition(_body(call_sid="CA900", notes="left vm"),
                                       current_user=USER, db=conn)

    sql, params = next((s, p) for s, p in conn.executed
                       if s.startswith("UPDATE calls SET disposition"))
    # Scoped by sid AND account AND lead — a forged sid can't cross tenants.
    assert "call_sid = %s AND account_id = %s AND property_id = %s" in sql
    assert params == ["no_answer", 9, "CA900", 3, 42]

    sql, params = next((s, p) for s, p in conn.executed
                       if s.startswith("UPDATE contact_history"))
    assert params == ["No answer", "left vm", "CA900"]

    assert out["ok"] is True and out["call_id"] == 10
    assert out["lead_status"] == "new"  # no_answer moves nothing
    assert emitted == [(42, "contact_attempted",
                        {"actor_user_id": 9, "channel": "call",
                         "metadata": {"call_sid": "CA900", "disposition": "no_answer",
                                      "direction": "outbound"}})]


def test_browser_mode_unknown_sid_is_404(emitted):
    conn = FakeConn(call_row_exists=False)
    with pytest.raises(HTTPException) as exc:
        dialer_route.log_disposition(_body(call_sid="CA-forged"),
                                     current_user=USER, db=conn)
    assert exc.value.status_code == 404
    assert conn.commits == 0


def test_manual_mode_creates_call_and_history(emitted):
    conn = FakeConn()
    out = dialer_route.log_disposition(_body(disposition="voicemail"),
                                       current_user=USER, db=conn)

    sql, params = next((s, p) for s, p in conn.executed
                       if s.startswith("INSERT INTO calls"))
    assert "'outbound'" in sql and "'completed'" in sql
    assert params[0] == 3 and params[1] == 42
    assert params[2].startswith("manual-")
    assert params[3] == "(713) 555-0142"      # primary number was dialed
    assert params[4] == "no_answer" and params[5] == "voicemail"

    sql, params = next((s, p) for s, p in conn.executed
                       if s.startswith("INSERT INTO contact_history"))
    assert params[1] == "Outbound call — no answer"
    assert params[2] == "Left message"
    assert out["call_id"] == 11


def test_manual_mode_alt_phone(emitted):
    conn = FakeConn()
    dialer_route.log_disposition(_body(phone_choice="alt"), current_user=USER, db=conn)
    _, params = next((s, p) for s, p in conn.executed if s.startswith("INSERT INTO calls"))
    assert params[3] == "713-555-0199"


def test_callback_creates_task(emitted, monkeypatch):
    applied = []
    monkeypatch.setattr("api.lead_logic.apply_status_change",
                        lambda db, lead, status, user, acct: applied.append((lead, status)) or ({}, []))
    conn = FakeConn()
    out = dialer_route.log_disposition(
        _body(disposition="callback", call_sid="CA900"), current_user=USER, db=conn)

    sql, params = next((s, p) for s, p in conn.executed
                       if s.startswith("INSERT INTO tasks"))
    assert "COALESCE(%s, CURRENT_DATE + 1)" in sql and "'high'" in sql
    assert params[2] == "Callback requested — Jane Doe"
    assert out["task_id"] == 33
    # A connect on a 'new' lead advances it to contacted, post-commit.
    assert applied == [(42, "contacted")]
    assert out["lead_status"] == "contacted"


def test_do_not_call_flags_lead_and_suppresses(emitted):
    conn = FakeConn()
    out = dialer_route.log_disposition(
        _body(disposition="do_not_call", call_sid="CA900"), current_user=USER, db=conn)

    sql, params = next((s, p) for s, p in conn.executed
                       if s.startswith("UPDATE properties SET do_not_call"))
    assert params == [42, 3]
    assert out["do_not_call"] is True
    assert [e[1] for e in emitted] == ["contact_attempted", "suppressed"]


def test_not_interested_closes_lead(emitted, monkeypatch):
    applied = []
    monkeypatch.setattr("api.lead_logic.apply_status_change",
                        lambda db, lead, status, user, acct: applied.append((lead, status)) or ({}, []))
    conn = FakeConn()
    out = dialer_route.log_disposition(
        _body(disposition="not_interested", call_sid="CA900"),
        current_user=USER, db=conn)
    assert applied == [(42, "not_interested")]
    assert out["lead_status"] == "not_interested"
