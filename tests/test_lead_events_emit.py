"""Tests for server-side auto-emission of lead events (api/lead_events_emit.py)
and its wiring into apply_status_change. Covers the status→event map, first-only
volume control, tenant scoping, best-effort degradation, and that a stage move
mirrors into the outcome log. Fake-conn style, no live DB."""
import pytest

from api import lead_events_emit as emit
from api.lead_events_emit import (
    STATUS_EVENT_MAP, emit_event, emit_stage_event, emit_surfaced, emit_viewed,
)


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self._conn.raise_on_execute:
            raise RuntimeError("boom")
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    @property
    def rowcount(self):
        return len(self._current)

    @property
    def description(self):
        rows = self._current
        if rows and isinstance(rows[0], dict):
            return [(k,) for k in rows[0].keys()]
        return []

    def fetchone(self):
        rows = self._current
        if not rows:
            return None
        r = rows[0]
        return tuple(r.values()) if isinstance(r, dict) else r


class _FakeConn:
    def __init__(self, responses=None, raise_on_execute=False):
        self.responses = list(responses or [])
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.raise_on_execute = raise_on_execute

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# ── STATUS_EVENT_MAP ──────────────────────────────────────────────────────────

class TestStatusEventMap:
    def test_maps_only_signal_bearing_statuses(self):
        assert STATUS_EVENT_MAP == {
            "contacted": "contacted", "quote_sent": "quote_sent",
            "won": "won", "converted": "won", "lost": "lost",
        }

    def test_noise_statuses_absent(self):
        for s in ("new", "qualified", "not_interested"):
            assert s not in STATUS_EVENT_MAP

    def test_every_mapped_event_is_a_valid_event_type(self):
        from api.models import LEAD_EVENT_TYPES
        assert set(STATUS_EVENT_MAP.values()) <= set(LEAD_EVENT_TYPES)


# ── emit_event ────────────────────────────────────────────────────────────────

class TestEmitEvent:
    def test_inserts_and_commits(self):
        conn = _FakeConn(responses=[[]])
        ok = emit_event(conn, 7, 3, "contacted", actor_user_id=9,
                        channel="call", metadata={"loss_reason": "price"})
        assert ok is True and conn.commits == 1
        sql, params = conn.executed[0]
        assert "INSERT INTO lead_events" in sql
        assert params[:5] == [7, 3, "contacted", "call", 9]
        assert params[5].adapted == {"loss_reason": "price"}   # psycopg2 Json wrapper

    def test_null_metadata_is_sql_null(self):
        conn = _FakeConn(responses=[[]])
        emit_event(conn, 7, 3, "viewed")
        _, params = conn.executed[0]
        assert params[5] is None

    def test_best_effort_swallows_and_rolls_back(self):
        conn = _FakeConn(raise_on_execute=True)
        assert emit_event(conn, 7, 3, "won") is False
        assert conn.rollbacks == 1 and conn.commits == 0


# ── emit_stage_event ──────────────────────────────────────────────────────────

class TestEmitStageEvent:
    def test_no_op_when_status_unchanged(self):
        conn = _FakeConn()
        assert emit_stage_event(conn, 7, 3, "won", "won") is None
        assert conn.executed == []

    def test_no_op_for_unmapped_status(self):
        conn = _FakeConn()
        assert emit_stage_event(conn, 7, 3, "qualified", "new") is None
        assert conn.executed == []

    def test_emits_mapped_event_on_change(self):
        conn = _FakeConn(responses=[[]])
        assert emit_stage_event(conn, 7, 3, "contacted", "new", actor_user_id=9) == "contacted"
        _, params = conn.executed[0]
        assert params[:3] == [7, 3, "contacted"] and params[4] == 9

    def test_converted_maps_to_won(self):
        conn = _FakeConn(responses=[[]])
        assert emit_stage_event(conn, 7, 3, "converted", "quote_sent") == "won"
        _, params = conn.executed[0]
        assert params[2] == "won"


# ── emit_surfaced (first-only, tenant-scoped, bulk) ───────────────────────────

class TestEmitSurfaced:
    def test_first_only_scoped_bulk_insert(self):
        conn = _FakeConn(responses=[[{"x": 1}, {"x": 2}]])   # rowcount 2
        n = emit_surfaced(conn, [7, 8, 8, None], 3, actor_user_id=9)
        assert n == 2
        sql, params = conn.executed[0]
        assert "INSERT INTO lead_events" in sql
        assert "NOT EXISTS" in sql and "'surfaced'" in sql
        assert "p.account_id = %s" in sql          # tenant-scoped
        assert params == [3, 9, 3, [7, 8, 8]]      # None dropped, ints coerced, dupes kept

    def test_empty_ids_no_query(self):
        conn = _FakeConn()
        assert emit_surfaced(conn, [None, None], 3) == 0
        assert conn.executed == []

    def test_best_effort(self):
        conn = _FakeConn(raise_on_execute=True)
        assert emit_surfaced(conn, [7], 3) == 0
        assert conn.rollbacks == 1


# ── emit_viewed (first-only, tenant-scoped) ───────────────────────────────────

class TestEmitViewed:
    def test_first_only_insert(self):
        conn = _FakeConn(responses=[[{"x": 1}]])
        assert emit_viewed(conn, 7, 3, actor_user_id=9) == 1
        sql, params = conn.executed[0]
        assert "NOT EXISTS" in sql and "'viewed'" in sql
        assert params == [7, 3, 9, 7, 3]

    def test_second_view_writes_nothing(self):
        conn = _FakeConn(responses=[[]])   # NOT EXISTS matches nothing → 0 rows
        assert emit_viewed(conn, 7, 3) == 0


# ── Wiring: apply_status_change mirrors the transition into the log ───────────

class _StatusChangeConn:
    """Serves the SELECT status / UPDATE RETURNING * / INSERT transition that
    apply_status_change runs, in order."""
    def __init__(self, row):
        self._responses = [
            [{"status": "new"}],   # SELECT current status → old_status 'new'
            [row],                 # UPDATE ... RETURNING *
            [],                    # INSERT stage_transitions
        ]
        self.committed = False

    def cursor(self):
        return _FakeCursor(_Bridge(self._responses))

    def commit(self):
        self.committed = True


class _Bridge:
    """Adapts the response queue to _FakeCursor's interface."""
    def __init__(self, responses):
        self.responses = responses
        self.executed = []
        self.raise_on_execute = False


def test_apply_status_change_emits_stage_event(monkeypatch):
    calls = []
    monkeypatch.setattr("api.lead_logic.emit_stage_event",
                        lambda *a, **k: calls.append((a, k)))
    # Isolate the downstream workflow machinery — not under test here.
    monkeypatch.setattr("api.workflow_engine.execute_status_change_rules",
                        lambda *a, **k: [])

    from api.lead_logic import apply_status_change
    row = {"id": 5, "account_id": 3, "status": "contacted"}
    result, _ = apply_status_change(_StatusChangeConn(row), 5, "contacted", user_id=9, account_id=3)

    assert result["id"] == 5
    assert len(calls) == 1
    args, kwargs = calls[0]
    # (conn, lead_id, account_id, new_status, old_status)
    assert args[1:] == (5, 3, "contacted", "new")
    assert kwargs["actor_user_id"] == 9
