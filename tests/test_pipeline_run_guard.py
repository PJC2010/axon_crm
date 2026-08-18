"""Tests for the pipeline-run guards in api/scheduler.py.

Three defects motivated these, all observed in production: runs that hung for 19
hours and 7 days with nothing to stop them, two web instances each running their
own in-process scheduler over the same jobs, and `pipeline_runs` rows left at
`running` forever by a redeploy. Plus the reason the runs were slow in the first
place — the neighborhood benchmark rewriting the whole account on every per-ZIP
run, which step 6.75 must now scope to the run's ZIP.

Fake-conn style — no live DB.
"""
import time

import pytest

import config
from api import scheduler as sched


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((" ".join(sql.split()), params))
        self.rowcount = self._conn.rowcount

    def fetchone(self):
        last = self._conn.executed[-1][0]
        if "pg_try_advisory_lock" in last:
            return (self._conn.lock_granted,)
        return self._conn.default_row


class _FakeConn:
    def __init__(self, lock_granted=True, rowcount=0, default_row=(0, 0, 0, 0)):
        self.lock_granted = lock_granted
        self.rowcount = rowcount
        self.default_row = default_row
        self.executed = []
        self.commits = 0
        self.closed = False

    def cursor(self, *a, **k):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def fake_db(monkeypatch):
    """Hand every psycopg2.connect() in the scheduler the same fake connection."""
    conns = []

    def _factory(*a, **k):
        conn = _FakeConn(**_factory.kwargs)
        conns.append(conn)
        return conn

    _factory.kwargs = {}
    monkeypatch.setattr(sched.psycopg2, "connect", _factory)
    return type("Handle", (), {"conns": conns, "configure": lambda s, **kw: _factory.kwargs.update(kw)})()


def _sql(conn, needle):
    return [(s, p) for s, p in conn.executed if needle in s]


# ── Single-writer advisory lock ──────────────────────────────────────────────

class TestRunLock:
    def test_loser_fails_fast_without_running_a_step(self, fake_db, monkeypatch):
        # Two web instances share these jobs. The second must not queue behind
        # the first in a thread pool the whole app depends on.
        fake_db.configure(lock_granted=False)
        boom = lambda *a, **k: pytest.fail("a step ran without holding the lock")
        monkeypatch.setattr("pipeline.seed.seed", boom)

        sched._run_pipeline(7, "77073", None, 5)

        conn = fake_db.conns[0]
        status = _sql(conn, "UPDATE pipeline_runs SET status")
        assert len(status) == 1
        assert status[0][1][0] == "failed"
        assert status[0][1][1].adapted == {"error": "another_run_in_progress"}
        # Never claimed to be running, and the connection is not leaked.
        assert not _sql(conn, "status = 'running'")
        assert conn.closed

    def test_winner_releases_the_lock_even_when_the_run_dies(self, fake_db, monkeypatch):
        monkeypatch.setattr("pipeline.seed.seed",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        sched._run_pipeline(8, "77073", None, 5)
        conn = fake_db.conns[0]
        assert _sql(conn, "pg_advisory_unlock")
        assert conn.closed

    def test_lock_key_is_unique_among_the_tick_locks(self):
        keys = [sched.WORKFLOW_TICK_LOCK_KEY, sched.ACCOUNT_RESCORE_LOCK_KEY,
                sched.RECURRING_INVOICE_LOCK_KEY, sched.GEO_RESCORE_LOCK_KEY,
                sched.TRIAL_EXPIRY_LOCK_KEY, sched.UNVERIFIED_DIGEST_LOCK_KEY,
                sched.USER_DIGEST_LOCK_KEY, sched.PHONE_APPEND_SWEEP_LOCK_KEY,
                sched.PIPELINE_RUN_LOCK_KEY]
        assert len(set(keys)) == len(keys)


# ── Watchdog ─────────────────────────────────────────────────────────────────

class TestWatchdog:
    def test_expiry_cancels_the_run_and_marks_the_row(self, fake_db, monkeypatch):
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 0.01)
        done = __import__("threading").Event()
        timer = sched._start_run_watchdog(99, done)
        try:
            deadline = time.time() + 5
            while not fake_db.conns and time.time() < deadline:
                time.sleep(0.01)
            assert sched.is_cancelled(99)          # cooperative stop requested
            assert 99 in sched._timed_out
            conn = fake_db.conns[0]
            sql, params = _sql(conn, "UPDATE pipeline_runs SET status")[0]
            assert "status = 'cancelled'" in sql
            # Conditional so a run that finished in the meantime is not clobbered.
            assert "AND status = 'running'" in sql
            assert params[0].adapted["error"] == "timeout"
            assert conn.closed
        finally:
            timer.cancel()
            sched._timed_out.discard(99)
            sched._clear_cancel(99)

    def test_finished_run_is_left_alone(self, fake_db, monkeypatch):
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 0.01)
        done = __import__("threading").Event()
        done.set()                                  # the run already completed
        timer = sched._start_run_watchdog(98, done)
        time.sleep(0.1)
        timer.cancel()
        assert not fake_db.conns
        assert not sched.is_cancelled(98)

    def test_zero_disables_it(self, monkeypatch):
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 0)
        assert sched._start_run_watchdog(97, __import__("threading").Event()) is None

    def test_timeout_reports_itself_as_timeout_not_user_cancel(self, fake_db, monkeypatch):
        # The between-steps cancel path must distinguish the watchdog from a user
        # pressing cancel, or the run history blames the wrong actor.
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 3600)
        sched._timed_out.add(11)
        sched.request_cancel(11)
        try:
            monkeypatch.setattr("pipeline.seed.seed", lambda *a, **k: 0)
            sched._run_pipeline(11, "77073", None, 5)
            conn = fake_db.conns[0]
            cancelled = [p for s, p in _sql(conn, "UPDATE pipeline_runs SET status")
                         if p[0] == "cancelled"]
            assert cancelled and cancelled[0][1].adapted["error"] == "timeout"
        finally:
            sched._timed_out.discard(11)
            sched._clear_cancel(11)


# ── Stale-row reconciliation ─────────────────────────────────────────────────

class TestReconcileStaleRuns:
    def test_marks_old_running_rows_failed(self, fake_db, monkeypatch):
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 3600)
        fake_db.configure(rowcount=2)
        # The fake returns rowcount=2 for each of the two sweeps (running +
        # orphaned queued), so the total is 4.
        assert sched.reconcile_stale_runs() == 4
        conn = fake_db.conns[0]
        updates = _sql(conn, "UPDATE pipeline_runs SET status = 'failed'")
        sql, params = updates[0]
        assert "WHERE status = 'running'" in sql
        # Age gate: backfill sweeps share this table and do not take the run
        # lock, so a sweep still inside its budget must not be killed.
        assert "make_interval(secs => %s)" in sql
        assert params[1] == 3600
        assert params[0].adapted == {"error": "stale (process restarted)"}
        # Second sweep: rows orphaned at `queued` by a restart between the
        # INSERT and the in-memory APScheduler job starting.
        queued_sql, queued_params = updates[1]
        assert "WHERE status = 'queued'" in queued_sql
        assert "make_interval(hours => 1)" in queued_sql
        assert queued_params[0].adapted == {"error": "stale (never started — process restarted)"}
        assert _sql(conn, "pg_advisory_unlock")
        assert conn.closed

    def test_skips_while_a_run_holds_the_lock(self, fake_db):
        fake_db.configure(lock_granted=False, rowcount=9)
        assert sched.reconcile_stale_runs() == 0
        conn = fake_db.conns[0]
        assert not _sql(conn, "UPDATE pipeline_runs")
        assert conn.closed

    def test_never_waits_zero_seconds(self, fake_db, monkeypatch):
        # RUN_MAX_SECONDS=0 disables the watchdog; it must not turn the sweep
        # into "fail every running row right now".
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 0)
        sched.reconcile_stale_runs()
        _, params = _sql(fake_db.conns[0], "UPDATE pipeline_runs SET status = 'failed'")[0]
        assert params[1] >= 1


# ── Step 6.75 is scoped ──────────────────────────────────────────────────────

class TestNeighborhoodStepIsScoped:
    def test_run_recomputes_only_its_own_zip(self, fake_db, monkeypatch):
        calls = []
        monkeypatch.setattr("pipeline.neighborhood.recompute_neighborhood_values",
                            lambda conn, acct, zips=None: calls.append((acct, zips)) or 3)
        for target, fn in [
            ("pipeline.seed.seed", lambda *a, **k: 1),
            ("pipeline.census.enrich_census", lambda *a, **k: 1),
            ("pipeline.geocode.enrich_geocode", lambda *a, **k: 1),
            ("pipeline.hcad_enrichment.enrich_hcad", lambda *a, **k: 1),
            ("pipeline.permits.enrich_permits", lambda *a, **k: 1),
            ("pipeline.storm.enrich_storm", lambda *a, **k: 0),
            ("pipeline.parcels.promote", lambda *a, **k: 1),
            ("pipeline.scorer.score_zip", lambda *a, **k: 1),
            ("pipeline.signals.detect_signals", lambda *a, **k: {}),
            ("pipeline.coverage.fill_rates", lambda *a, **k: {}),
        ]:
            monkeypatch.setattr(target, fn)

        sched._run_pipeline(12, "77073", "roofing", 5,
                            skip={"property", "contact", "demographics"})

        assert calls == [(5, ["77073"])]
        conn = fake_db.conns[0]
        assert [p[0] for _, p in _sql(conn, "UPDATE pipeline_runs SET status")][-1] == "done"

    def test_rescore_after_a_zip_scoped_backfill_stays_scoped(self, monkeypatch):
        calls = []
        monkeypatch.setattr("pipeline.neighborhood.recompute_neighborhood_values",
                            lambda conn, acct, zips=None: calls.append(zips) or 0)
        monkeypatch.setattr("pipeline.scorer.score_zip", lambda *a, **k: 4)
        assert sched._rescore_account(_FakeConn(), 5, "77073") == 4
        assert calls == [["77073"]]

    def test_whole_account_backfill_still_recomputes_account_wide(self, monkeypatch):
        calls = []
        monkeypatch.setattr("pipeline.neighborhood.recompute_neighborhood_values",
                            lambda conn, acct, zips=None: calls.append(zips) or 0)
        monkeypatch.setattr("pipeline.scorer.score_zip", lambda *a, **k: 1)

        class _Conn(_FakeConn):
            def cursor(self, *a, **k):
                cur = _FakeCursor(self)
                cur.fetchall = lambda: [("77073",), ("77090",)]
                return cur

        assert sched._rescore_account(_Conn(), 5, None) == 2
        assert calls == [None]
