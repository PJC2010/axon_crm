"""The scheduler's ticks report through the job ledger (api/job_runs.py).

api/scheduler.py wraps every tick in ``job_runs.tracked``, replaces its early
returns with ``skip`` and reports its swallowed exceptions with ``failed``.
These tests drive real ticks against a scripted connection and read the row
each one leaves. The ledger's whole point is that a tick which stopped running
becomes visible, so the wiring is what has to be pinned, not just the module.
"""
import os

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

import config  # noqa: E402
from api import data_health, job_runs  # noqa: E402
from api import scheduler as sched  # noqa: E402
from api.admin_logic import classify_job_id  # noqa: E402
from tests.fakeconn import Conn, split_ledger, sql_matching  # noqa: E402

OPEN = "INSERT INTO scheduler_job_runs"
CLOSE = "UPDATE scheduler_job_runs SET finished_at"

# Every tick the API registers, by the APScheduler id it registers under.
TICK_IDS = {
    "workflow_daily_tick", "account_rescore_daily", "non_residential_sweep_daily",
    "recurring_invoices_daily", "phone_append_sweep_daily", "trial_expiry_daily",
    "unverified_digest_daily", "user_digest_daily", "geo_rescore_nightly",
    "stale_run_reconcile", "ml_retrain_nightly", data_health.JOB_ID,
}


@pytest.fixture
def fake_db(monkeypatch):
    conns = []

    def _factory(*a, **k):
        conn = Conn(_factory.script)
        conns.append(conn)
        return conn

    _factory.script = [
        ("pg_try_advisory_lock", (["ok"], [(True,)])),
        (OPEN, (["id"], [(5,)])),
    ]
    monkeypatch.setattr(sched.psycopg2, "connect", _factory)
    return type("Handle", (), {
        "conns": conns, "script": _factory.script,
        "tick_conns": property(lambda s: split_ledger(conns)[1]),
        "ledger_conns": property(lambda s: split_ledger(conns)[0]),
    })()


def _row(handle):
    """(job_id, status, error, detail) of the one run the ledger recorded."""
    opened = [p for c in handle.conns for _, p in sql_matching(c, OPEN)]
    closed = [p for c in handle.conns for _, p in sql_matching(c, CLOSE)]
    assert len(opened) == 1 and len(closed) == 1, (opened, closed)
    status, error, detail, row_id = closed[0]
    assert row_id == 5
    return opened[0][0], status, error, detail.adapted


class TestTrialExpiryTick:
    def test_ok_run_notes_its_figure(self, fake_db, monkeypatch):
        monkeypatch.setattr("api.billing.expire_stale_trials", lambda conn: 3)
        sched.run_trial_expiry_tick()
        assert _row(fake_db) == ("trial_expiry_daily", "ok", None, {"downgraded": 3})
        tick, = fake_db.tick_conns
        assert sql_matching(tick, "pg_advisory_unlock") and tick.closed

    def test_held_lock_is_a_skipped_run(self, fake_db, monkeypatch):
        fake_db.script[0] = ("pg_try_advisory_lock", (["ok"], [(False,)]))
        monkeypatch.setattr("api.billing.expire_stale_trials",
                            lambda conn: pytest.fail("must not run under a held lock"))
        sched.run_trial_expiry_tick()
        _, status, error, detail = _row(fake_db)
        assert status == "skipped" and error == "another worker holds the lock"
        assert detail == {"reason": "another worker holds the lock"}
        tick, = fake_db.tick_conns
        assert tick.closed                            # the tick's finally still ran

    def test_a_swallowed_exception_is_an_error_run(self, fake_db, monkeypatch):
        def boom(conn):
            raise RuntimeError("billing down")
        monkeypatch.setattr("api.billing.expire_stale_trials", boom)
        sched.run_trial_expiry_tick()                 # the tick still does not raise
        _, status, error, _ = _row(fake_db)
        assert status == "error" and error == "RuntimeError: billing down"
        tick, = fake_db.tick_conns
        assert sql_matching(tick, "pg_advisory_unlock") and tick.closed


class TestConfigGatedTicks:
    def test_disabled_phone_sweep_is_a_skipped_run(self, fake_db, monkeypatch):
        monkeypatch.setattr(config, "PHONE_APPEND_SWEEP_MAX", 0)
        sched.run_phone_append_sweep_tick()
        job_id, status, error, _ = _row(fake_db)
        assert job_id == "phone_append_sweep_daily" and status == "skipped"
        assert error == "PHONE_APPEND_SWEEP_MAX=0"
        assert fake_db.tick_conns == []               # never connected — still ledgered

    def test_unconfigured_digest_is_a_skipped_run(self, fake_db, monkeypatch):
        monkeypatch.setattr("api.notifications.admin_alerts_configured", lambda: False)
        sched.run_unverified_signup_digest()
        job_id, status, error, _ = _row(fake_db)
        assert job_id == "unverified_digest_daily" and status == "skipped"
        assert error == "admin alerts not configured"
        assert fake_db.tick_conns == []


class TestReconcileTick:
    def test_ledger_hygiene_rides_the_reconcile(self, fake_db):
        sched.reconcile_stale_runs()
        tick, = fake_db.tick_conns
        (stale_sql, _), = sql_matching(tick, "UPDATE scheduler_job_runs SET status = 'error'")
        assert "status = 'running' AND started_at < NOW() - INTERVAL '6 hours'" in stale_sql
        (prune_sql, _), = sql_matching(tick, "DELETE FROM scheduler_job_runs")
        assert "INTERVAL '90 days'" in prune_sql
        job_id, status, _, detail = _row(fake_db)
        assert job_id == "stale_run_reconcile" and status == "ok"
        assert detail == {"reconciled": 0, "stale_job_rows": 0, "pruned_job_rows": 0}

    def test_held_lock_skips_and_still_returns_zero(self, fake_db):
        fake_db.script[0] = ("pg_try_advisory_lock", (["ok"], [(False,)]))
        assert sched.reconcile_stale_runs() == 0
        assert _row(fake_db)[1] == "skipped"


class TestRegistration:
    def test_every_registered_tick_is_tracked_under_its_own_id(self, fake_db, monkeypatch):
        # A tick registered under one id but ledgered under another would show
        # as "never ran" on the Jobs table forever.
        monkeypatch.setattr(config, "ML_RETRAIN_ENABLED", True)
        before = {j.id for j in sched.scheduler.get_jobs()}
        try:
            for register in (
                sched.schedule_retraining, sched.schedule_workflow_tick,
                sched.schedule_account_rescore, sched.schedule_non_residential_sweep,
                sched.schedule_recurring_invoices, sched.schedule_phone_append_sweep,
                sched.schedule_trial_expiry, sched.schedule_unverified_digest,
                sched.schedule_user_digest, sched.schedule_geo_rescore,
                sched.schedule_stale_run_reconcile,      # also runs the reconcile once
                data_health.schedule_data_health_snapshot,
            ):
                register()
            jobs = {j.id: j for j in sched.scheduler.get_jobs()}
            assert TICK_IDS <= set(jobs)
            for jid in TICK_IDS:
                assert classify_job_id(jid, job_runs.TRACKED_JOB_IDS) == ("tick", None), jid
                assert getattr(jobs[jid].func, "__job_id__", None) == jid, jid
            ticks = {jid for jid in jobs
                     if classify_job_id(jid, job_runs.TRACKED_JOB_IDS)[0] == "tick"}
            assert ticks == TICK_IDS
        finally:
            for j in sched.scheduler.get_jobs():
                if j.id not in before:
                    sched.scheduler.remove_job(j.id)

    def test_the_manual_snapshot_id_is_tracked_but_never_a_cron(self):
        assert data_health.MANUAL_JOB_ID in job_runs.TRACKED_JOB_IDS
        assert data_health.MANUAL_JOB_ID not in TICK_IDS
