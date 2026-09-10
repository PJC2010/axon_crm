"""Tests for api/routes/admin_ops.py — the Ops tab's endpoints. Fake-conn style."""
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg2.errors
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

import config  # noqa: E402
from api import scheduler as sched  # noqa: E402
from api.routes import admin_ops  # noqa: E402
from api.routes.admin_ops import (  # noqa: E402
    admin_backlog, admin_cancel_run, admin_job_runs, admin_jobs, admin_run, admin_runs,
    admin_system,
)
from tests.fakeconn import Conn, first_index, sql_matching  # noqa: E402

ADMIN = {"id": 7, "username": "pete", "account_id": 1}
NOW = datetime.now(timezone.utc)
LEDGER_COLS = ["id", "job_id", "started_at", "finished_at", "status", "error", "detail", "host",
               "duration_seconds"]


def _job(jid, func=None, trigger="cron[hour='7']"):
    """A stand-in for an APScheduler Job: pending jobs under pytest carry no
    next_run_time, which is exactly the shape the endpoint must tolerate."""
    return SimpleNamespace(id=jid, trigger=trigger, func=func or (lambda: None))


# ── Jobs ──────────────────────────────────────────────────────────────────────

class TestJobs:
    @staticmethod
    def _script(last=None, counts=None):
        two_hours = NOW - timedelta(hours=2)
        last_rows = [
            (3, "trial_expiry_daily", two_hours, two_hours, "ok", None, {"downgraded": 1}, "web-1", 4),
            (2, "stale_run_reconcile", NOW, NOW, "skipped", "a run is in progress", {}, "web-2", 0),
        ]
        return [
            ("SELECT DISTINCT ON (job_id)", last if last is not None else (LEDGER_COLS, last_rows)),
            ("GROUP BY job_id, status", counts if counts is not None else (
                ["job_id", "status", "n"],
                [("trial_expiry_daily", "ok", 6), ("trial_expiry_daily", "skipped", 1)])),
        ]

    def test_merges_the_registry_with_the_ledger(self, monkeypatch):
        monkeypatch.setattr(admin_ops.scheduler, "get_jobs", lambda: [
            _job("trial_expiry_daily", sched.run_trial_expiry_tick),
            _job("pipeline_schedule_12"),
            _job("run_301", trigger="date[2026-09-10]"),
        ])
        out = admin_jobs(db=Conn(self._script()))
        assert out["degraded"] == [] and out["instance"]
        assert out["scheduler"]["running"] is False          # never started under pytest
        assert [j["id"] for j in out["jobs"]] == [
            "stale_run_reconcile", "trial_expiry_daily", "pipeline_schedule_12", "run_301"]
        by_id = {j["id"]: j for j in out["jobs"]}
        trial = by_id["trial_expiry_daily"]
        assert trial["kind"] == "tick" and trial["tracked"] and trial["scheduled_here"]
        assert trial["trigger"] == "cron[hour='7']" and trial["next_run_time"] is None
        assert trial["last"]["status"] == "ok" and trial["last"]["detail"] == {"downgraded": 1}
        assert trial["counts_7d"] == {"ok": 6, "error": 0, "skipped": 1, "running": 0}
        # Known to the ledger only: the other instance's job.
        stale = by_id["stale_run_reconcile"]
        assert stale["scheduled_here"] is False and stale["trigger"] is None
        assert stale["last"]["status"] == "skipped" and stale["last"]["host"] == "web-2"
        assert stale["counts_7d"] == {"ok": 0, "error": 0, "skipped": 0, "running": 0}
        schedule = by_id["pipeline_schedule_12"]
        assert (schedule["kind"], schedule["ref"], schedule["tracked"]) == ("pipeline_schedule", 12, False)
        assert schedule["last"] is None
        assert (by_id["run_301"]["kind"], by_id["run_301"]["ref"]) == ("one_shot", 301)

    def test_a_cut_off_ledger_read_degrades_only_itself(self, monkeypatch):
        monkeypatch.setattr(admin_ops.scheduler, "get_jobs",
                            lambda: [_job("trial_expiry_daily", sched.run_trial_expiry_tick)])
        conn = Conn(self._script(last=psycopg2.errors.QueryCanceled()))
        out = admin_jobs(db=conn)
        assert out["degraded"] == ["ledger_last"] and conn.rollbacks == 1
        job, = out["jobs"]
        assert job["last"] is None                             # unknown, never "no runs"
        assert job["counts_7d"] == {"ok": 6, "error": 0, "skipped": 1, "running": 0}

    def test_job_history_is_paged(self):
        rows = [(9, "trial_expiry_daily", NOW, NOW, "ok", None, {}, "web-1", 2, 41)]
        conn = Conn([("FROM scheduler_job_runs WHERE job_id = %s", (LEDGER_COLS + ["_total"], rows))])
        out = admin_job_runs("trial_expiry_daily", page=2, page_size=20, db=conn)
        assert out["total"] == 41 and out["page"] == 2 and out["items"][0]["id"] == 9
        assert "_total" not in out["items"][0]
        (_, params), = sql_matching(conn, "FROM scheduler_job_runs WHERE job_id = %s")
        assert params == ("trial_expiry_daily", 20, 20)


# ── Runs ──────────────────────────────────────────────────────────────────────

class TestRuns:
    COLS = ["id", "account_id", "account_name", "zip", "vertical", "status", "triggered_by",
            "schedule_id", "created_at", "started_at", "finished_at", "duration_seconds",
            "error", "properties_scored", "_total"]

    @staticmethod
    def _call(conn, **kw):
        args = dict(status=None, account_id=None, triggered_by=None, zip_code=None,
                    page=1, page_size=50, db=conn)
        args.update(kw)
        return admin_runs(**args)

    def test_lists_every_org_newest_first_with_filters_bound(self):
        rows = [(50, 2, "Blue Sky", "77396", "roofing", "running", "schedule", 4,
                 NOW, NOW, None, None, None, None, 1)]
        conn = Conn([("FROM pipeline_runs r LEFT JOIN accounts a", (self.COLS, rows))])
        out = self._call(conn, status="running", account_id=2, triggered_by="schedule",
                         zip_code="77396", page=3, page_size=10)
        assert out["total"] == 1 and out["items"][0]["account_name"] == "Blue Sky"
        assert "_total" not in out["items"][0]
        (sql, params), = sql_matching(conn, "FROM pipeline_runs r LEFT JOIN accounts a")
        assert ("WHERE r.status = %s AND r.account_id = %s AND r.triggered_by = %s "
                "AND r.zip = %s") in sql
        assert "ORDER BY r.created_at DESC, r.id DESC" in sql
        assert params == ("running", 2, "schedule", "77396", 10, 20)

    def test_unknown_status_is_a_400(self):
        with pytest.raises(HTTPException) as exc:
            self._call(Conn(), status="paused")
        assert exc.value.status_code == 400 and "queued" in exc.value.detail

    def test_past_the_end_page_counts_for_real(self):
        conn = Conn([("FROM pipeline_runs r LEFT JOIN accounts a", (self.COLS, [])),
                     ("SELECT COUNT(*) FROM pipeline_runs r", (["n"], [(7,)]))])
        out = self._call(conn, page=4)
        assert out == {"items": [], "total": 7, "page": 4, "page_size": 50}

    def test_detail_404s(self):
        conn = Conn([("SELECT r.*, a.name AS account_name", (["id"], []))])
        with pytest.raises(HTTPException) as exc:
            admin_run(99, db=conn)
        assert exc.value.status_code == 404

    def test_detail_returns_the_full_row(self):
        conn = Conn([("SELECT r.*, a.name AS account_name",
                      (["id", "result_json", "account_name"], [(9, {"summary": {}}, "Acme")]))])
        assert admin_run(9, db=conn) == {"id": 9, "result_json": {"summary": {}},
                                         "account_name": "Acme"}


class TestCancel:
    @staticmethod
    def _script(status="running", updated=True):
        script = [("SELECT id, account_id, zip, status FROM pipeline_runs",
                   (["id", "account_id", "zip", "status"], [(9, 2, "77396", status)]))]
        if updated:
            script.append(("UPDATE pipeline_runs SET status = 'cancelled'", (None, [(1,)])))
        return script

    def test_404_when_missing(self):
        conn = Conn([("SELECT id, account_id, zip, status FROM pipeline_runs",
                      (["id", "account_id", "zip", "status"], []))])
        with pytest.raises(HTTPException) as exc:
            admin_cancel_run(9, admin=ADMIN, db=conn)
        assert exc.value.status_code == 404

    def test_400_when_already_finished(self, monkeypatch):
        asked = []
        monkeypatch.setattr(admin_ops, "request_cancel", asked.append)
        with pytest.raises(HTTPException) as exc:
            admin_cancel_run(9, admin=ADMIN, db=Conn(self._script(status="done")))
        assert exc.value.status_code == 400 and exc.value.detail == "Run is already done"
        assert asked == []

    def test_flags_the_run_flips_the_row_and_audits_before_commit(self, monkeypatch):
        asked = []
        monkeypatch.setattr(admin_ops, "request_cancel", asked.append)
        conn = Conn(self._script())
        out = admin_cancel_run(9, admin=ADMIN, db=conn)
        assert out == {"ok": True, "run_id": 9, "status": "cancelled",
                       "previous_status": "running"}
        assert asked == [9]
        (sql, params), = sql_matching(conn, "UPDATE pipeline_runs SET status = 'cancelled'")
        assert "WHERE id = %s AND status IN ('queued', 'running')" in sql
        assert params[0].adapted == {"error": "cancelled by platform admin"} and params[1] == 9
        (_, audit), = sql_matching(conn, "INSERT INTO admin_audit_log")
        assert audit[2] == "run.cancel" and audit[3] == "pipeline_run" and audit[4] == "9"
        assert audit[5].adapted == {"account_id": 2, "zip": "77396", "previous_status": "running"}
        assert first_index(conn, "INSERT INTO admin_audit_log") < first_index(conn, "COMMIT")
        assert conn.commits == 1 and conn.rollbacks == 0

    def test_409_when_the_run_finished_in_between(self, monkeypatch):
        monkeypatch.setattr(admin_ops, "request_cancel", lambda rid: None)
        conn = Conn(self._script(updated=False))
        with pytest.raises(HTTPException) as exc:
            admin_cancel_run(9, admin=ADMIN, db=conn)
        assert exc.value.status_code == 409
        assert conn.rollbacks == 1 and conn.commits == 0
        assert not sql_matching(conn, "INSERT INTO admin_audit_log")


# ── Backlog ───────────────────────────────────────────────────────────────────

class TestBacklog:
    @staticmethod
    def _script(webhooks=None):
        return [
            ("FROM geocode_queue GROUP BY status",
             (["status", "n", "oldest"], [("queued", 12, NOW), ("failed", 2, NOW)])),
            ("GROUP BY last_error", (["last_error", "n"], [("no match", 2)])),
            ("FROM pipeline_runs WHERE status IN ('queued', 'running')",
             (["queued", "running", "queued_stale", "running_stale", "oldest_active_at"],
              [(3, 1, 1, 0, NOW)])),
            ("FROM user_tokens WHERE purpose = 'verify_email'",
             (["live", "expired_unused"], [(4, 20)])),
            ("FROM stripe_webhook_events", webhooks or (
                ["received", "error", "error_7d", "oldest_received_at", "last_received_at"],
                [(1, 5, 2, NOW, NOW)])),
            ("FROM workflow_rule_firings", (["fired_24h", "accounts_24h"], [(30, 4)])),
        ]

    def test_every_block_answers(self, monkeypatch):
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 1800)
        conn = Conn(self._script())
        out = admin_backlog(db=conn)
        assert out["degraded"] == []
        assert out["runs"]["queued_stale"] == 1 and out["stale_after_seconds"] == 1800
        (_, params), = sql_matching(conn, "FROM pipeline_runs WHERE status IN ('queued', 'running')")
        assert params == (1800,)                        # the reconcile's own rule
        assert out["geocode_queue"]["failed"] == 2       # the Data tab's reader, shared
        assert out["geocode_queue"]["top_errors"] == [{"last_error": "no match", "n": 2}]
        assert out["verify_tokens"] == {"live": 4, "expired_unused": 20}
        assert out["stripe_webhooks"]["error_7d"] == 2
        assert out["workflow_firings"] == {"fired_24h": 30, "accounts_24h": 4}

    def test_disabled_watchdog_means_a_day(self, monkeypatch):
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 0)
        assert admin_backlog(db=Conn(self._script()))["stale_after_seconds"] == 86400

    def test_a_cut_off_block_degrades_only_itself(self):
        conn = Conn(self._script(webhooks=psycopg2.errors.QueryCanceled()))
        out = admin_backlog(db=conn)
        assert out["degraded"] == ["stripe_webhooks"] and out["stripe_webhooks"] is None
        assert conn.rollbacks == 1 and out["runs"]["queued"] == 3


# ── System ────────────────────────────────────────────────────────────────────

class TestSystem:
    def test_reports_pending_migrations_and_the_environment(self, monkeypatch, tmp_path):
        for name in ("0001_init.sql", "0087_data_health_snapshots.sql",
                     "0088_scheduler_job_runs.sql"):
            (tmp_path / name).write_text("-- x")
        monkeypatch.setattr(admin_ops, "MIGRATIONS_DIR", tmp_path)
        monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
        monkeypatch.setenv("RENDER_SERVICE_NAME", "axon-api")
        monkeypatch.setattr(config, "RUN_MAX_SECONDS", 3600)
        old = NOW - timedelta(days=400)
        conn = Conn([
            # A database migrated under the old 3-digit names still recognises
            # the renamed file (db/migrate.py::_canonical).
            ("FROM schema_migrations", (["filename", "applied_at"],
                                        [("0087_data_health_snapshots.sql", NOW),
                                         ("001_init.sql", old)])),
            ("server_version", (["v"], [("16.4",)])),
        ])
        out = admin_system(db=conn)
        assert out["degraded"] == []
        assert out["migrations"] == {
            "on_disk": 3, "applied": 2, "pending": ["0088_scheduler_job_runs.sql"],
            "latest_applied": {"filename": "0087_data_health_snapshots.sql", "applied_at": NOW},
        }
        assert out["app"]["commit"] == "abc123" and out["app"]["service"] == "axon-api"
        assert out["app"]["postgres"] == "16.4" and out["app"]["host"]
        assert out["db"]["statement_timeout_ms"] == config.DB_STATEMENT_TIMEOUT_MS
        assert out["scheduler"]["run_max_seconds"] == 3600
        assert isinstance(out["scheduler"]["jobs"], int) and out["scheduler"]["running"] is False

    def test_no_secret_reaches_the_payload(self, monkeypatch, tmp_path):
        monkeypatch.setattr(admin_ops, "MIGRATIONS_DIR", tmp_path)
        monkeypatch.setattr(config, "DATABASE_URL", "postgresql://axon:hunter2@db/axon")
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_hunter2")
        out = admin_system(db=Conn([("FROM schema_migrations", (["filename", "applied_at"], [])),
                                    ("server_version", (["v"], [("16.4",)]))]))
        assert "hunter2" not in json.dumps(out, default=str)

    def test_a_cut_off_catalog_read_leaves_migrations_unknown(self, monkeypatch, tmp_path):
        (tmp_path / "0001_init.sql").write_text("-- x")
        monkeypatch.setattr(admin_ops, "MIGRATIONS_DIR", tmp_path)
        conn = Conn([("FROM schema_migrations", psycopg2.errors.QueryCanceled()),
                     ("server_version", (["v"], [("16.4",)]))])
        out = admin_system(db=conn)
        assert out["degraded"] == ["migrations"] and conn.rollbacks == 1
        assert out["migrations"] == {"on_disk": 1, "applied": None, "pending": None,
                                     "latest_applied": None}
        assert out["app"]["postgres"] == "16.4"
