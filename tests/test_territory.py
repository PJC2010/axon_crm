"""Per-plan territory limit (api/territory.py): pure helpers, the guard wiring
on the schedule/run endpoints, the downgrade trim, and the fire-time backstop.
Follows tests/test_quota_route_guards.py's pattern-matched fake connection —
no database, no FastAPI app."""
from datetime import datetime

import pytest
from fastapi import HTTPException

from api import territory
from api.routes import pipeline as pipeline_route
from api.routes.pipeline import RunCreate, ScheduleCreate, ScheduleUpdate
from api.scoring_quota import _OWN_BOOK_SOURCES, engine_book_sql

OWNER = {"id": 9, "account_id": 3, "role": "owner"}


class _Cursor:
    """Pattern-matched fake cursor: canned rows keyed by a SQL substring."""
    def __init__(self, conn):
        self._conn = conn
        self._rows = []

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self._conn.executed.append(s)
        self._rows = []
        for frag, rows in self._conn.script:
            if frag in s:
                self._rows = rows() if callable(rows) else rows
                return
        raise AssertionError(f"unscripted SQL: {s[:90]}")

    @property
    def description(self):
        rows = self._rows
        if rows and isinstance(rows[0], dict):
            return [(k,) for k in rows[0].keys()]
        return []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def fetchall(self):
        rows = self._rows
        if rows and isinstance(rows[0], dict):
            return [tuple(r.values()) for r in rows]
        return list(rows)


class _Conn:
    def __init__(self, script):
        self.script = script          # list of (sql_substring, rows)
        self.executed = []
        self.commits = 0

    def cursor(self, *a, **k): return _Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): pass


def _boom():
    raise RuntimeError("db down")


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_new_zips_dedups_and_ignores_held_and_empty():
    assert territory.new_zips(["77005", "77005", "77002", "", None],
                              {"77002"}) == ["77005"]


def test_zips_to_keep_oldest_first_with_null_created_at_last():
    t1, t2 = datetime(2026, 1, 1), datetime(2026, 2, 1)
    schedules = [
        {"zip": "77010", "created_at": None},       # NULLs sort last
        {"zip": "77002", "created_at": t2},
        {"zip": "77001", "created_at": t1},
        {"zip": "77002", "created_at": t1},          # per-zip min wins
    ]
    assert territory.zips_to_keep(schedules, 1) == {"77001"}
    assert territory.zips_to_keep(schedules, 2) == {"77001", "77002"}
    assert territory.zips_to_keep(schedules, 3) == {"77001", "77002", "77010"}
    assert territory.zips_to_keep(schedules, 0) == set()


def test_zips_to_keep_two_null_created_ats_tiebreak_on_zip():
    schedules = [{"zip": "77020", "created_at": None},
                 {"zip": "77010", "created_at": None}]
    assert territory.zips_to_keep(schedules, 1) == {"77010"}


def test_engine_book_sql_stays_in_lockstep_with_the_quota_rule():
    # The SQL provenance rule is generated from the quota's own-book set —
    # every source must appear, plus the escaped website_ prefix family, so
    # the two rules can't drift apart.
    sql = engine_book_sql()
    for source in _OWN_BOOK_SOURCES:
        assert f"'{source}'" in sql
    assert "NOT LIKE 'website\\_%%'" in sql
    assert "lead_source IS NULL" in sql
    prefixed = engine_book_sql("p.")
    assert "p.lead_source IS NULL" in prefixed


# ── POST /pipeline-schedules ──────────────────────────────────────────────────

def test_create_schedule_new_zip_at_cap_refuses(monkeypatch):
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", [("77002",)]),                             # used_territories
        ("SELECT DISTINCT zip FROM pipeline_schedules", [("77002",)]),
    ])
    with pytest.raises(HTTPException) as exc:
        pipeline_route.create_schedule(ScheduleCreate(zip="77005"),
                                       current_user=OWNER, db=conn, _mod=OWNER)
    assert exc.value.status_code == 403
    assert exc.value.detail["territory"] is True
    assert exc.value.detail["upgrade"] is True
    assert exc.value.detail["limit"] == 1
    assert not any("INSERT INTO pipeline_schedules" in s for s in conn.executed)


def test_create_schedule_held_zip_passes(monkeypatch):
    import api.scheduler as scheduler
    monkeypatch.setattr(scheduler, "add_schedule_job", lambda row: None)
    row = {"id": 12, "zip": "77002", "vertical": None, "day_of_week": "monday",
           "hour": 6, "is_active": True, "account_id": 3}
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", [("77002",)]),
        ("SELECT DISTINCT zip FROM pipeline_schedules", [("77002",)]),
        ("INSERT INTO pipeline_schedules", [row]),
    ])
    out = pipeline_route.create_schedule(ScheduleCreate(zip="77002"),
                                         current_user=OWNER, db=conn, _mod=OWNER)
    assert out["zip"] == "77002"


def test_create_schedule_second_active_schedule_same_zip_is_free(monkeypatch):
    # The scheduling guard counts distinct ZIPs, not schedule rows.
    import api.scheduler as scheduler
    monkeypatch.setattr(scheduler, "add_schedule_job", lambda row: None)
    row = {"id": 13, "zip": "77002", "is_active": True, "account_id": 3}
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", [("77002",)]),
        ("SELECT DISTINCT zip FROM pipeline_schedules", [("77002",)]),
        ("INSERT INTO pipeline_schedules", [row]),
    ])
    out = pipeline_route.create_schedule(ScheduleCreate(zip="77002", hour=18),
                                         current_user=OWNER, db=conn, _mod=OWNER)
    assert out["id"] == 13


def test_create_schedule_no_plan_row_is_unlimited(monkeypatch):
    import api.scheduler as scheduler
    monkeypatch.setattr(scheduler, "add_schedule_job", lambda row: None)
    row = {"id": 14, "zip": "10001", "is_active": True, "account_id": 3}
    conn = _Conn([
        ("FROM account_plans", []),                          # un-provisioned
        ("INSERT INTO pipeline_schedules", [row]),
    ])
    out = pipeline_route.create_schedule(ScheduleCreate(zip="10001"),
                                         current_user=OWNER, db=conn, _mod=OWNER)
    assert out["id"] == 14
    # No measurement queries on an unlimited account.
    assert not any("UNION" in s for s in conn.executed)


def test_create_schedule_counting_failure_fails_open(monkeypatch):
    # A territory guard must never take schedule creation down with it.
    import api.scheduler as scheduler
    monkeypatch.setattr(scheduler, "add_schedule_job", lambda row: None)
    row = {"id": 15, "zip": "77005", "is_active": True, "account_id": 3}
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", _boom),
        ("SELECT DISTINCT zip FROM pipeline_schedules", _boom),
        ("INSERT INTO pipeline_schedules", [row]),
    ])
    out = pipeline_route.create_schedule(ScheduleCreate(zip="77005"),
                                         current_user=OWNER, db=conn, _mod=OWNER)
    assert out["id"] == 15


# ── PATCH /pipeline-schedules/{id} (reactivation) ─────────────────────────────

def test_reactivating_new_zip_at_cap_refuses():
    conn = _Conn([
        ("SELECT zip, is_active FROM pipeline_schedules", [("77005", False)]),
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", [("77002",)]),
        ("SELECT DISTINCT zip FROM pipeline_schedules", [("77002",)]),
    ])
    with pytest.raises(HTTPException) as exc:
        pipeline_route.update_schedule(41, ScheduleUpdate(is_active=True),
                                       current_user=OWNER, db=conn, _mod=OWNER)
    assert exc.value.status_code == 403
    assert exc.value.detail["territory"] is True
    assert not any("UPDATE pipeline_schedules" in s for s in conn.executed)


def test_reactivating_within_limits_passes(monkeypatch):
    import api.scheduler as scheduler
    monkeypatch.setattr(scheduler, "add_schedule_job", lambda row: None)
    monkeypatch.setattr(scheduler, "remove_schedule_job", lambda sid: None)
    row = {"id": 41, "zip": "77002", "is_active": True, "account_id": 3,
           "day_of_week": "monday", "hour": 6}
    conn = _Conn([
        ("SELECT zip, is_active FROM pipeline_schedules", [("77002", False)]),
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", [("77002",)]),
        ("SELECT DISTINCT zip FROM pipeline_schedules", []),  # nothing else scheduled
        ("UPDATE pipeline_schedules SET", [row]),
    ])
    out = pipeline_route.update_schedule(41, ScheduleUpdate(is_active=True),
                                         current_user=OWNER, db=conn, _mod=OWNER)
    assert out["is_active"] is True


def test_deactivating_never_hits_the_guard(monkeypatch):
    import api.scheduler as scheduler
    monkeypatch.setattr(scheduler, "add_schedule_job", lambda row: None)
    monkeypatch.setattr(scheduler, "remove_schedule_job", lambda sid: None)
    row = {"id": 41, "zip": "77002", "is_active": False, "account_id": 3}
    conn = _Conn([("UPDATE pipeline_schedules SET", [row])])
    out = pipeline_route.update_schedule(41, ScheduleUpdate(is_active=False),
                                         current_user=OWNER, db=conn, _mod=OWNER)
    assert out["is_active"] is False
    assert not any("account_plans" in s for s in conn.executed)


# ── POST /pipeline/run ────────────────────────────────────────────────────────

def _quiet_run_plumbing(monkeypatch):
    import api.ratelimit as ratelimit
    import api.scheduler as scheduler
    monkeypatch.setattr(ratelimit.pipeline_run_limiter, "check", lambda key: None)
    monkeypatch.setattr(scheduler, "enqueue_run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "enqueue_region_run", lambda *a, **k: None)


def test_manual_run_of_held_zip_always_allowed(monkeypatch):
    _quiet_run_plumbing(monkeypatch)
    run = {"id": 100, "zip": "77002", "status": "queued", "account_id": 3}
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", [("77002",)]),
        ("INSERT INTO pipeline_runs", [run]),
    ])
    out = pipeline_route.trigger_run(RunCreate(zip="77002"),
                                     current_user=OWNER, db=conn, _mod=OWNER)
    assert out["id"] == 100


def test_manual_run_of_new_zip_at_cap_refuses(monkeypatch):
    _quiet_run_plumbing(monkeypatch)
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("UNION", [("77002",)]),
    ])
    with pytest.raises(HTTPException) as exc:
        pipeline_route.trigger_run(RunCreate(zip="77005"),
                                   current_user=OWNER, db=conn, _mod=OWNER)
    assert exc.value.status_code == 403
    assert exc.value.detail["territory"] is True
    assert not any("INSERT INTO pipeline_runs" in s for s in conn.executed)


def test_region_run_checks_the_whole_fanout(monkeypatch):
    _quiet_run_plumbing(monkeypatch)
    import pipeline.hcad_store as hcad_store
    monkeypatch.setattr(hcad_store, "region_zips",
                        lambda region_id: ["77001", "77002", "77003"])
    conn = _Conn([
        ("FROM account_plans", [("growth", 3)]),
        ("UNION", [("77002", ), ("77010",)]),   # 2 held + 2 new from the region
    ])
    with pytest.raises(HTTPException) as exc:
        pipeline_route.trigger_run(RunCreate(region_id="near-northside"),
                                   current_user=OWNER, db=conn, _mod=OWNER)
    assert exc.value.status_code == 403


def test_region_run_resolution_failure_fails_open(monkeypatch):
    _quiet_run_plumbing(monkeypatch)
    import pipeline.hcad_store as hcad_store
    def _no_region(region_id):
        raise RuntimeError("no local HCAD data")
    monkeypatch.setattr(hcad_store, "region_zips", _no_region)
    run = {"id": 101, "zip": "region:near-northside", "status": "queued"}
    conn = _Conn([("INSERT INTO pipeline_runs", [run])])
    out = pipeline_route.trigger_run(RunCreate(region_id="near-northside"),
                                     current_user=OWNER, db=conn, _mod=OWNER)
    assert out["id"] == 101


# ── fire-time backstop + downgrade trim ───────────────────────────────────────

def test_schedule_may_fire_only_for_oldest_n_zips():
    t1, t2 = datetime(2026, 1, 1), datetime(2026, 2, 1)
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("SELECT zip, created_at FROM pipeline_schedules",
         [("77002", t1), ("77005", t2)]),
    ])
    assert territory.schedule_may_fire(conn, 3, "77002") == (True, None)
    assert territory.schedule_may_fire(conn, 3, "77005") == (False, "territory_limit")


def test_schedule_may_fire_degrades_open():
    conn = _Conn([("FROM account_plans", _boom)])
    assert territory.schedule_may_fire(conn, 3, "77002") == (True, None)


def test_trim_deactivates_over_limit_schedules(monkeypatch):
    import api.scheduler as scheduler
    removed = []
    monkeypatch.setattr(scheduler, "remove_schedule_job", removed.append)
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("WITH zip_rank", [(5,), (7,)]),
    ])
    assert territory.trim_schedules_to_limit(conn, 3) == [5, 7]
    assert removed == [5, 7]


def test_trim_is_a_noop_on_unlimited_plans():
    conn = _Conn([("FROM account_plans", [("pro", None)])])
    assert territory.trim_schedules_to_limit(conn, 3) == []
    assert not any("UPDATE" in s for s in conn.executed)
