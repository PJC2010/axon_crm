"""Tests for api/data_health.py — the nightly platform data-health snapshot.
Fake-conn style; the scheduler is exercised unstarted, as test_retrain_toggle does."""
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

import config  # noqa: E402
from api import data_health  # noqa: E402
from api import scheduler as sched  # noqa: E402
from tests.fakeconn import Conn, first_index, sql_matching  # noqa: E402

PARCEL_COLS = ["total", "with_coords", "with_apn", "unclassified", "non_residential",
               "property_type", "year_built", "estimated_value", "owner_name",
               "last_updated_at"]


def _blocks_script():
    """One scripted answer per statement build_report runs, specific first."""
    return [
        ("LEFT JOIN hcad_parcel_centroids", (["with_apn", "matched"], [(1000, 950)])),
        ("FROM parcels GROUP BY zip",
         (["zip", "parcels", "with_coords", "unclassified", "non_residential"],
          [("77001", 500, 480, 0, 20), ("77002", 300, 100, 300, 0)])),
        ("FROM hcad_properties WHERE site_zip IS NOT NULL",
         (["zip", "hcad_rows"], [("77001", 520), ("77003", 90)])),
        ("COALESCE(geocode_source", (["source", "count"], [("hcad_centroid", 580), ("(none)", 220)])),
        ("MAX(updated_at) AS last_updated_at FROM parcels",
         (PARCEL_COLS, [(800, 580, 1000, 300, 20, 700, 650, 600, 790,
                         datetime(2026, 9, 1, tzinfo=timezone.utc))])),
        ("COUNT(site_city)", (["properties", "site_city_filled"], [(610, 600)])),
        ("MAX(loaded_at)", (["centroids", "centroids_loaded_at"],
                            [(1500000, datetime(2026, 8, 20, tzinfo=timezone.utc))])),
        ("FROM hcad_permits", (["permits"], [(Decimal("12345"),)])),
        ("FROM properties WHERE archived_at IS NULL GROUP BY account_id",
         (["account_id", "properties", "with_coords", "unclassified", "excludable"],
          [(1, 900, 890, 0, 12), (2, 40, 10, 40, 0)])),
        ("GROUP BY field, source",
         (["field", "source", "open"], [("year_built", "rentcast", 30), ("square_footage", "rentcast", 5)])),
        ("AND resolution = 'kept' GROUP BY account_id", (["account_id", "open"], [(1, 35)])),
        ("FROM parcels WHERE enrichment_flags->>'seed' = 'hcad' AND owner_occupied", (["n"], [(3,)])),
        ("POSITION(UPPER(city)", (["n"], [(0,)])),
        ("AND city IS NULL", (["n"], [(11,)])),
    ]


class TestBuildReport:
    def test_every_block_lands_with_json_safe_values(self):
        conn = Conn(_blocks_script())
        report = data_health.build_report(conn, block_timeout_ms=1234)
        assert report["blocks_failed"] == []
        assert set(data_health.BLOCK_NAMES) <= set(report)
        assert report["parcels"]["total"] == 800
        assert report["parcels"]["last_updated_at"] == "2026-09-01T00:00:00+00:00"
        assert report["apn_match"] == {"with_apn": 1000, "matched": 950}
        zips = {z["zip"]: z for z in report["zips"]}
        assert zips["77001"]["hcad_rows"] == 520 and zips["77002"]["hcad_rows"] == 0
        assert zips["77003"] == {"zip": "77003", "parcels": 0, "with_coords": 0,
                                 "unclassified": 0, "non_residential": 0, "hcad_rows": 90}
        assert report["zips"][0]["zip"] == "77001"      # biggest cache first
        assert report["hcad"]["permits"] == 12345 and isinstance(report["hcad"]["permits"], int)
        assert report["discrepancies"]["total_open"] == 35
        assert report["city_sanity"] == {
            "parcels_mail_city_leak": 3, "parcels_null_city": 11,
            "properties_mail_city_leak": 0, "properties_null_city": 11,
        }
        # Each block ran under its own cap and its own transaction.
        caps = sql_matching(conn, "set_config('statement_timeout'")
        assert len(caps) == len(data_health.BLOCK_NAMES)
        assert all(p == ("1234",) for _, p in caps)
        assert conn.rollbacks == len(data_health.BLOCK_NAMES)

    def test_a_failing_block_is_recorded_and_the_rest_still_land(self):
        conn = Conn([("COUNT(site_city)", RuntimeError("boom"))] + _blocks_script())
        report = data_health.build_report(conn, block_timeout_ms=0)
        assert report["blocks_failed"] == ["hcad"]
        assert report["hcad"] is None
        assert report["parcels"]["total"] == 800
        assert report["accounts"][0]["properties"] == 900
        assert not sql_matching(conn, "set_config")           # 0 disables the cap
        assert conn.rollbacks == len(data_health.BLOCK_NAMES)

    def test_exclude_array_is_built_from_the_rule_module(self):
        from pipeline.residential import EXCLUDE_REASONS
        sql = data_health._exclude_array_sql()
        assert all(f"'{r}'" in sql for r in EXCLUDE_REASONS) and sql.endswith("::text[]")


@pytest.fixture
def fake_db(monkeypatch):
    """Hand psycopg2.connect() in the module the scripted fake."""
    conns = []

    def _factory(*a, **k):
        conn = Conn(_factory.script)
        conns.append(conn)
        return conn

    _factory.script = [
        ("pg_try_advisory_lock", (["ok"], [(True,)])),
        ("INSERT INTO data_health_snapshots", (["id"], [(42,)])),
    ]
    monkeypatch.setattr(data_health.psycopg2, "connect", _factory)
    return type("Handle", (), {"conns": conns, "script": _factory.script})()


class TestRunSnapshot:
    def test_happy_path_writes_ok_row_prunes_and_unlocks(self, fake_db, monkeypatch):
        monkeypatch.setattr(data_health, "build_report", lambda conn, **kw: {
            "blocks_failed": [], "duration_seconds": 0.2, "parcels": {"total": 1}})
        assert data_health.run_snapshot("admin") == 42
        conn, = fake_db.conns
        (_, ins_params), = sql_matching(conn, "INSERT INTO data_health_snapshots")
        assert ins_params[0] == "admin"
        (_, upd), = sql_matching(conn, "UPDATE data_health_snapshots SET finished_at")
        assert upd[0] == "ok" and upd[1].adapted["parcels"] == {"total": 1}
        assert upd[2] is None and upd[3] == 42
        (_, del_params), = sql_matching(conn, "DELETE FROM data_health_snapshots")
        assert del_params == (data_health.KEEP_SNAPSHOTS,)
        assert sql_matching(conn, "pg_advisory_unlock") and conn.closed
        # The running row is committed before the scans, so the page can show it.
        assert (first_index(conn, "INSERT INTO data_health_snapshots")
                < first_index(conn, "COMMIT")
                < first_index(conn, "UPDATE data_health_snapshots"))

    def test_partial_when_a_block_failed(self, fake_db, monkeypatch):
        monkeypatch.setattr(data_health, "build_report",
                            lambda conn, **kw: {"blocks_failed": ["hcad"], "duration_seconds": 0.2})
        data_health.run_snapshot()
        (_, params), = sql_matching(fake_db.conns[0], "UPDATE data_health_snapshots SET finished_at")
        assert params[0] == "partial"

    def test_error_when_the_report_itself_blows_up(self, fake_db, monkeypatch):
        def boom(conn, **kw):
            raise RuntimeError("db gone")
        monkeypatch.setattr(data_health, "build_report", boom)
        assert data_health.run_snapshot() == 42
        (_, params), = sql_matching(fake_db.conns[0], "UPDATE data_health_snapshots SET finished_at")
        assert params[0] == "error" and params[2] == "RuntimeError: db gone"

    def test_lock_held_means_skip(self, fake_db):
        fake_db.script[0] = ("pg_try_advisory_lock", (["ok"], [(False,)]))
        assert data_health.run_snapshot() is None
        conn, = fake_db.conns
        assert not sql_matching(conn, "INSERT INTO data_health_snapshots") and conn.closed


class TestScheduling:
    @staticmethod
    def _clear():
        for jid in (data_health.JOB_ID, data_health.MANUAL_JOB_ID):
            if sched.scheduler.get_job(jid):
                sched.scheduler.remove_job(jid)

    def test_nightly_job_registers_at_the_free_slot(self, monkeypatch):
        monkeypatch.setattr(config, "WORKFLOW_TICK_HOUR", 7)
        self._clear()
        try:
            data_health.schedule_data_health_snapshot()
            job = sched.scheduler.get_job(data_health.JOB_ID)
            assert job is not None and job.func is data_health.run_snapshot
            fields = {f.name: str(f) for f in job.trigger.fields}
            assert fields["hour"] == "7" and fields["minute"] == "35"
        finally:
            self._clear()

    def test_refresh_enqueues_a_one_shot_admin_run(self):
        self._clear()
        try:
            data_health.enqueue_snapshot()
            job = sched.scheduler.get_job(data_health.MANUAL_JOB_ID)
            assert job is not None and job.kwargs == {"triggered_by": "admin"}
        finally:
            self._clear()

    def test_lock_key_is_unique_among_the_tick_locks(self):
        keys = [sched.WORKFLOW_TICK_LOCK_KEY, sched.ACCOUNT_RESCORE_LOCK_KEY,
                sched.RECURRING_INVOICE_LOCK_KEY, sched.GEO_RESCORE_LOCK_KEY,
                sched.TRIAL_EXPIRY_LOCK_KEY, sched.UNVERIFIED_DIGEST_LOCK_KEY,
                sched.USER_DIGEST_LOCK_KEY, sched.PHONE_APPEND_SWEEP_LOCK_KEY,
                sched.PIPELINE_RUN_LOCK_KEY, sched.NON_RESIDENTIAL_SWEEP_LOCK_KEY]
        assert data_health.LOCK_KEY not in keys
