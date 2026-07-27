"""Tests for the two-way SMS conversation endpoints (api/routes/messaging.py):
the per-lead thread, the mark-seen write, and the account-wide unread summary
that feeds the header message bell. Fake-conn style — no live DB."""
import pytest
from fastapi import HTTPException

from api.routes import messaging as messaging_route


# ── fake DB ─────────────────────────────────────────────────────────────────────

class _Cursor:
    """Queued responses: a list of dicts/tuples per execute (SELECT), or an int
    (UPDATE rowcount)."""
    def __init__(self, conn):
        self._conn = conn
        self._current = []
        self.rowcount = 0

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=None):
        self._conn.executed.append((" ".join(sql.split()), params))
        resp = self._conn.responses.pop(0) if self._conn.responses else []
        if isinstance(resp, int):
            self._current, self.rowcount = [], resp
        else:
            self._current, self.rowcount = resp, 0

    @property
    def description(self):
        rows = self._current
        return [(k,) for k in rows[0].keys()] if rows and isinstance(rows[0], dict) else []

    def fetchall(self):
        rows = self._current
        return [tuple(r.values()) for r in rows] if rows and isinstance(rows[0], dict) else list(rows)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _Conn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.commits = 0
    def cursor(self): return _Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): pass


USER = {"id": 9, "account_id": 3, "role": "member"}

LEAD_OK = [[(42,)]]            # properties ownership probe
LEAD_MISSING = [[]]


# ── GET /leads/{id}/conversation ────────────────────────────────────────────────

class TestGetConversation:
    def _rows(self):
        return [
            {"id": 1, "direction": "outbound", "body": "Hi, quote ready",
             "created_at": "2026-07-20T10:00:00", "seen_at": None},
            {"id": 2, "direction": "inbound", "body": "Great, Tuesday?",
             "created_at": "2026-07-20T10:05:00", "seen_at": None},
        ]

    def test_returns_thread_and_scopes_to_account_and_lead(self):
        conn = _Conn([*LEAD_OK, self._rows()])
        out = messaging_route.get_conversation(42, user=USER, db=conn)

        assert [m["direction"] for m in out] == ["outbound", "inbound"]
        assert out[1]["body"] == "Great, Tuesday?"

        probe_sql, probe_params = conn.executed[0]
        assert "account_id" in probe_sql and probe_params == (42, 3)

        thread_sql, thread_params = conn.executed[1]
        assert "channel = 'sms'" in thread_sql
        assert "ORDER BY created_at ASC" in thread_sql   # chat order, oldest first
        assert thread_params == (42,)

    def test_unknown_lead_404s(self):
        conn = _Conn(LEAD_MISSING)
        with pytest.raises(HTTPException) as exc:
            messaging_route.get_conversation(42, user=USER, db=conn)
        assert exc.value.status_code == 404
        assert len(conn.executed) == 1                   # never touches history


# ── POST /leads/{id}/conversation/seen ──────────────────────────────────────────

class TestMarkConversationSeen:
    def test_marks_inbound_rows_and_commits(self):
        conn = _Conn([*LEAD_OK, 2])                      # 2 rows updated
        out = messaging_route.mark_conversation_seen(42, user=USER, db=conn)

        assert out == {"marked": 2}
        assert conn.commits == 1
        sql, params = conn.executed[1]
        assert sql.startswith("UPDATE contact_history SET seen_at = NOW()")
        assert "direction = 'inbound'" in sql            # outbound rows untouched
        assert "seen_at IS NULL" in sql                  # idempotent re-marks
        assert params == (42,)

    def test_unknown_lead_404s(self):
        conn = _Conn(LEAD_MISSING)
        with pytest.raises(HTTPException) as exc:
            messaging_route.mark_conversation_seen(42, user=USER, db=conn)
        assert exc.value.status_code == 404
        assert conn.commits == 0


# ── GET /unread-messages ────────────────────────────────────────────────────────

class TestUnreadMessages:
    def test_aggregates_count_across_leads(self):
        rows = [
            {"lead_id": 42, "contact_name": "Jane Doe", "address": "1 Main St",
             "unseen": 2, "last_body": "Tuesday works", "last_at": "2026-07-20T10:05:00"},
            {"lead_id": 43, "contact_name": "+17135550142", "address": None,
             "unseen": 1, "last_body": "STOP?", "last_at": "2026-07-20T09:00:00"},
        ]
        conn = _Conn([rows])
        out = messaging_route.unread_messages(user=USER, db=conn)

        assert out["count"] == 3
        assert [r["lead_id"] for r in out["leads"]] == [42, 43]

        sql, params = conn.executed[0]
        assert "p.account_id" in sql and params == (3,)  # tenant-scoped
        assert "p.archived_at IS NULL" in sql            # archived leads don't badge
        assert "ch.seen_at IS NULL" in sql
        assert "ch.direction = 'inbound'" in sql

    def test_empty_when_nothing_unread(self):
        conn = _Conn([[]])
        out = messaging_route.unread_messages(user=USER, db=conn)
        assert out == {"count": 0, "leads": []}
