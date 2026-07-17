"""Tests for the lead outcome-event log (api/routes/lead_events.py): account
scoping, event-type validation, server-set actor, and the migration↔code
event-type contract. Fake-conn style, no live DB."""
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models import LEAD_EVENT_TYPES, LeadEventCreate
from api.routes.lead_events import add_lead_event, list_lead_events


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    @property
    def description(self):
        rows = self._current
        if rows and isinstance(rows[0], dict):
            return [(k,) for k in rows[0].keys()]
        return []

    def fetchall(self):
        rows = self._current
        if rows and isinstance(rows[0], dict):
            return [tuple(r.values()) for r in rows]
        return list(rows)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _FakeConn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass


USER = {"id": 9, "account_id": 3, "role": "rep"}

_LEAD_FOUND = [(101,)]   # _assert_lead SELECT hit


def _event_row(**over):
    row = {"id": 55, "property_id": 101, "account_id": 3, "event_type": "won",
           "channel": None, "actor_user_id": 9,
           "occurred_at": datetime(2026, 7, 17, 12, 0), "metadata": None}
    row.update(over)
    return row


class TestAddLeadEvent:
    def test_inserts_scoped_row_with_server_set_actor(self):
        conn = _FakeConn([_LEAD_FOUND, [_event_row(channel="call",
                                                   metadata={"quote_amount": 8500})]])
        body = LeadEventCreate(event_type="won", channel="call",
                               metadata={"quote_amount": 8500})
        result = add_lead_event(101, body, db=conn, current_user=USER)

        assert_sql, assert_params = conn.executed[0]
        assert "FROM properties" in assert_sql and assert_params == [101, 3]

        insert_sql, params = conn.executed[1]
        assert "INSERT INTO lead_events" in insert_sql
        assert params[:3] == [101, 3, "won"]
        assert params[3] == "call"
        assert params[4] == 9                             # actor is the caller, not client input
        assert params[5].adapted == {"quote_amount": 8500}
        assert result.event_type == "won"
        assert result.metadata == {"quote_amount": 8500}

    def test_null_metadata_stays_sql_null(self):
        conn = _FakeConn([_LEAD_FOUND, [_event_row()]])
        add_lead_event(101, LeadEventCreate(event_type="viewed"), db=conn, current_user=USER)
        _, params = conn.executed[1]
        assert params[5] is None                          # not jsonb 'null'

    def test_rejects_unknown_event_type_before_touching_db(self):
        conn = _FakeConn([])
        with pytest.raises(HTTPException) as exc:
            add_lead_event(101, LeadEventCreate(event_type="converted"),
                           db=conn, current_user=USER)
        assert exc.value.status_code == 400
        assert conn.executed == []

    def test_lead_outside_account_404(self):
        conn = _FakeConn([[]])
        with pytest.raises(HTTPException) as exc:
            add_lead_event(101, LeadEventCreate(event_type="won"), db=conn, current_user=USER)
        assert exc.value.status_code == 404


class TestListLeadEvents:
    def test_scopes_by_account_and_orders_oldest_first(self):
        conn = _FakeConn([_LEAD_FOUND, [_event_row(), _event_row(id=56, event_type="lost")]])
        result = list_lead_events(101, db=conn, user=USER)
        sql, params = conn.executed[1]
        assert "account_id = %s" in sql
        assert "ORDER BY occurred_at ASC" in sql
        assert params == [101, 3]
        assert [e.event_type for e in result] == ["won", "lost"]

    def test_lead_outside_account_404(self):
        conn = _FakeConn([[]])
        with pytest.raises(HTTPException) as exc:
            list_lead_events(101, db=conn, user=USER)
        assert exc.value.status_code == 404


class TestEventTypeContract:
    def test_constant_matches_migration_check(self):
        """LEAD_EVENT_TYPES must stay in lockstep with the CHECK constraint in
        migration 0058 — a type accepted by the API but rejected by Postgres
        would 500 on insert."""
        sql = (Path(__file__).parent.parent
               / "db" / "migrations" / "0058_scoring_feedback_loop.sql").read_text()
        check_block = sql.split("event_type IN (", 1)[1].split("))", 1)[0]
        migration_types = {t.strip().strip("'") for t in
                           (line.split("--")[0].strip().rstrip(",")
                            for line in check_block.splitlines())
                           if t.strip().strip("'")}
        assert migration_types == set(LEAD_EVENT_TYPES)
