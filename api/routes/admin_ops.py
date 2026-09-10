"""Platform operations — scheduler jobs, pipeline runs, backlog, system. Deliberately CROSS-TENANT.

The same reviewed exemption from the account_id-scoping rule as
api/routes/admin.py (CLAUDE.md): this router serves the platform operator, is
included in api/main.py with the router-wide require_platform_admin guard, and
tests/test_router_gating.py asserts that guard for every router serving /admin.
No endpoint here may declare a query param named ``token``.

GET  /admin/jobs                    — every APScheduler job on this instance + its ledger history
GET  /admin/jobs/{job_id}/runs      — one job's ledger rows (scheduler_job_runs, migration 0088)
GET  /admin/runs                    — cross-tenant pipeline runs feed
GET  /admin/runs/{id}               — one run, full result_json
POST /admin/runs/{id}/cancel        — cooperative cancel (audit: run.cancel)
GET  /admin/backlog                 — queues and stale work
GET  /admin/system                  — build, instance, migrations, timeouts, scheduler

Two-instance deploy: APScheduler's registry (and so ``next_run_time`` and the
cancel flag) is per process. The jobs payload names the instance it describes;
the ledger's ``host`` column says which instance actually ran a tick.
"""
import logging
import os
import platform
import socket
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from psycopg2.extras import Json

import config as cfg
from api import job_runs
from api.admin_audit import record_admin_action
from api.admin_logic import (
    RUN_STATUSES, clamp_page, merge_jobs, pending_migrations, runs_where,
    stale_run_threshold, validate_run_cancel,
)
from api.deps import (
    dict_fetchall, dict_fetchone, get_db, require_platform_admin, soft_query,
)
from api.routes.admin import _finish_page
from api.routes.admin_data import geocode_queue_block
from api.scheduler import request_cancel, scheduler

log = logging.getLogger(__name__)
router = APIRouter()

# Read from disk, never through db/migrate.py: that module reads DATABASE_URL at
# import time and is a script, not a request-safe import.
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

_JOB_RUN_COLS = (
    "id, job_id, started_at, finished_at, status, error, detail, host, "
    "EXTRACT(EPOCH FROM (finished_at - started_at))::int AS duration_seconds"
)


# ── Jobs ──────────────────────────────────────────────────────────────────────

@router.get("/admin/jobs")
def admin_jobs(db: PGConn = Depends(get_db)):
    degraded: list[str] = []

    def _q(name, fn, fallback):
        value, timed_out = soft_query(db, fn, fallback)
        if timed_out:
            degraded.append(name)
        return value

    # Under pytest the scheduler is never started and a pending job has no
    # next_run_time yet — getattr, not attribute access.
    registered = [{
        "id": j.id,
        "trigger": str(j.trigger),
        "next_run_time": getattr(j, "next_run_time", None),
        "func_job_id": getattr(j.func, "__job_id__", None),
    } for j in scheduler.get_jobs()]

    def _last(cur):
        cur.execute(
            f"SELECT DISTINCT ON (job_id) {_JOB_RUN_COLS} FROM scheduler_job_runs "
            "ORDER BY job_id, started_at DESC, id DESC"
        )
        return dict_fetchall(cur)

    def _counts(cur):
        cur.execute(
            "SELECT job_id, status, COUNT(*) AS n FROM scheduler_job_runs "
            "WHERE started_at > NOW() - INTERVAL '7 days' GROUP BY job_id, status"
        )
        return dict_fetchall(cur)

    last_rows = _q("ledger_last", _last, None)
    count_rows = _q("ledger_counts", _counts, None)
    return {
        "instance": socket.gethostname(),
        "scheduler": {"running": scheduler.running, "state": scheduler.state},
        "jobs": merge_jobs(registered, last_rows, count_rows, job_runs.TRACKED_JOB_IDS),
        "degraded": degraded,
    }


@router.get("/admin/jobs/{job_id}/runs")
def admin_job_runs(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    page, page_size = clamp_page(page, page_size)
    with db.cursor() as cur:
        cur.execute(
            f"SELECT {_JOB_RUN_COLS}, COUNT(*) OVER () AS _total FROM scheduler_job_runs "
            "WHERE job_id = %s ORDER BY started_at DESC, id DESC LIMIT %s OFFSET %s",
            (job_id, page_size, (page - 1) * page_size),
        )
        rows = dict_fetchall(cur)
        return _finish_page(cur, rows, page, page_size,
                            "SELECT COUNT(*) FROM scheduler_job_runs WHERE job_id = %s",
                            (job_id,))


# ── Pipeline runs ─────────────────────────────────────────────────────────────

@router.get("/admin/runs")
def admin_runs(
    status: str | None = Query(None),
    account_id: int | None = Query(None),
    triggered_by: str | None = Query(None, max_length=40),
    zip_code: str | None = Query(None, alias="zip", max_length=40),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    """Every org's runs, newest first — what is queued or running right now
    across the platform, and what failed. Region runs carry ``zip`` as
    ``region:<id>`` and backfill sweeps as ``backfill`` (api/territory.py)."""
    if status and status not in RUN_STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"status must be one of: {', '.join(RUN_STATUSES)}.")
    page, page_size = clamp_page(page, page_size)
    where_sql, params = runs_where(status=status, account_id=account_id,
                                   triggered_by=triggered_by, zip_code=zip_code)
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT r.id, r.account_id, a.name AS account_name, r.zip, r.vertical, r.status,
                   r.triggered_by, r.schedule_id, r.created_at, r.started_at, r.finished_at,
                   EXTRACT(EPOCH FROM (r.finished_at - r.started_at))::int AS duration_seconds,
                   r.result_json->>'error' AS error,
                   (r.result_json->'summary'->>'properties_scored')::int AS properties_scored,
                   COUNT(*) OVER () AS _total
            FROM pipeline_runs r LEFT JOIN accounts a ON a.id = r.account_id
            {where_sql}
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        rows = dict_fetchall(cur)
        return _finish_page(cur, rows, page, page_size,
                            f"SELECT COUNT(*) FROM pipeline_runs r {where_sql}", tuple(params))


@router.get("/admin/runs/{run_id}")
def admin_run(run_id: int, db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT r.*, a.name AS account_name FROM pipeline_runs r "
            "LEFT JOIN accounts a ON a.id = r.account_id WHERE r.id = %s",
            (run_id,),
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.post("/admin/runs/{run_id}/cancel")
def admin_cancel_run(
    run_id: int,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Cooperative cancel of any org's run — the platform twin of
    DELETE /pipeline/runs/{id} (api/routes/pipeline.py), same mechanics:

    * ``request_cancel`` sets an in-process flag the run checks between steps.
      The flag reaches only THIS instance; a run executing on the other instance
      never sees it and stops only via the row below — which `_run_pipeline`
      does not re-read. Pre-existing, shared with the tenant endpoint.
    * The row is flipped to ``cancelled`` right away so every UI agrees. The
      ``AND status IN (...)`` guard closes the select→update race the tenant
      endpoint has; a run that finishes in between answers 409. Note that
      `_run_pipeline._set_status` writes without a guard, so a run that
      completes *after* this flip overwrites it with ``done`` — also
      pre-existing and deliberately left alone here.
    """
    with db.cursor() as cur:
        cur.execute("SELECT id, account_id, zip, status FROM pipeline_runs WHERE id = %s",
                    (run_id,))
        run = dict_fetchone(cur)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    problem = validate_run_cancel(run["status"])
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    request_cancel(run_id)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE pipeline_runs SET status = 'cancelled', finished_at = NOW(), "
            "result_json = COALESCE(result_json, '{}'::jsonb) || %s::jsonb "
            "WHERE id = %s AND status IN ('queued', 'running')",
            (Json({"error": "cancelled by platform admin"}), run_id),
        )
        if cur.rowcount == 0:
            db.rollback()
            raise HTTPException(status_code=409,
                                detail="Run finished before it could be cancelled.")
    record_admin_action(
        db, admin, "run.cancel", "pipeline_run", run_id,
        {"account_id": run["account_id"], "zip": run["zip"],
         "previous_status": run["status"]},
    )
    db.commit()
    return {"ok": True, "run_id": run_id, "status": "cancelled",
            "previous_status": run["status"]}


# ── Backlog ───────────────────────────────────────────────────────────────────

@router.get("/admin/backlog")
def admin_backlog(db: PGConn = Depends(get_db)):
    """Queues and stale work, one soft_query block each. The webhook, token
    and firing tables have no supporting index — a scan that hits the cap
    degrades that one block, never the page."""
    degraded: list[str] = []

    def _q(name, fn, fallback):
        value, timed_out = soft_query(db, fn, fallback)
        if timed_out:
            degraded.append(name)
        return value

    stale_after = stale_run_threshold(cfg.RUN_MAX_SECONDS)

    def _runs(cur):
        # The same two rules reconcile_stale_runs applies (api/scheduler.py).
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE status = 'queued') AS queued, "
            "COUNT(*) FILTER (WHERE status = 'running') AS running, "
            "COUNT(*) FILTER (WHERE status = 'queued' "
            "  AND created_at < NOW() - INTERVAL '1 hour') AS queued_stale, "
            "COUNT(*) FILTER (WHERE status = 'running' "
            "  AND COALESCE(started_at, created_at) < NOW() - make_interval(secs => %s)) "
            "  AS running_stale, "
            "MIN(created_at) AS oldest_active_at "
            "FROM pipeline_runs WHERE status IN ('queued', 'running')",
            (stale_after,),
        )
        return dict_fetchone(cur)

    def _verify_tokens(cur):
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE expires_at > NOW()) AS live, "
            "COUNT(*) FILTER (WHERE expires_at <= NOW()) AS expired_unused "
            "FROM user_tokens WHERE purpose = 'verify_email' AND used_at IS NULL"
        )
        return dict_fetchone(cur)

    def _webhooks(cur):
        # `ignored` is a normal outcome (events this deployment did not
        # subscribe to) and is deliberately not counted; `received` means
        # claimed but never finished, `error` means the handler raised.
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE status = 'received') AS received, "
            "COUNT(*) FILTER (WHERE status = 'error') AS error, "
            "COUNT(*) FILTER (WHERE status = 'error' "
            "  AND received_at > NOW() - INTERVAL '7 days') AS error_7d, "
            "MIN(received_at) FILTER (WHERE status = 'received') AS oldest_received_at, "
            "MAX(received_at) AS last_received_at "
            "FROM stripe_webhook_events"
        )
        return dict_fetchone(cur)

    def _firings(cur):
        cur.execute(
            "SELECT COUNT(*) AS fired_24h, COUNT(DISTINCT account_id) AS accounts_24h "
            "FROM workflow_rule_firings WHERE fired_at > NOW() - INTERVAL '24 hours'"
        )
        return dict_fetchone(cur)

    return {
        "geocode_queue": _q("geocode_queue", geocode_queue_block, None),
        "runs": _q("runs", _runs, None),
        "verify_tokens": _q("verify_tokens", _verify_tokens, None),
        "stripe_webhooks": _q("stripe_webhooks", _webhooks, None),
        "workflow_firings": _q("workflow_firings", _firings, None),
        "stale_after_seconds": stale_after,
        "degraded": degraded,
    }


# ── System ────────────────────────────────────────────────────────────────────

@router.get("/admin/system")
def admin_system(db: PGConn = Depends(get_db)):
    """Build, instance, migrations, timeouts and the scheduler's state. The
    snapshot is explicit — numbers, names and flags only, the same principle
    as admin_logic.evaluate_config_checks — so no secret can be echoed."""
    degraded: list[str] = []

    def _q(name, fn, fallback):
        value, timed_out = soft_query(db, fn, fallback)
        if timed_out:
            degraded.append(name)
        return value

    def _applied(cur):
        cur.execute("SELECT filename, applied_at FROM schema_migrations "
                    "ORDER BY applied_at DESC, filename DESC")
        return dict_fetchall(cur)

    def _pg_version(cur):
        cur.execute("SELECT current_setting('server_version')")
        return cur.fetchone()[0]

    applied = _q("migrations", _applied, None)
    on_disk = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    migrations = {
        "on_disk": len(on_disk),
        "applied": None if applied is None else len(applied),
        "pending": None if applied is None else pending_migrations(
            on_disk, [r["filename"] for r in applied]),
        "latest_applied": (applied[0] if applied else None),
    }
    return {
        "app": {
            "commit": os.getenv("RENDER_GIT_COMMIT"),
            "service": os.getenv("RENDER_SERVICE_NAME"),
            "instance_id": os.getenv("RENDER_INSTANCE_ID"),
            "host": socket.gethostname(),
            "python": platform.python_version(),
            "postgres": _q("postgres_version", _pg_version, None),
        },
        "migrations": migrations,
        "db": {
            "pool_min": cfg.DB_POOL_MIN,
            "pool_max": cfg.DB_POOL_MAX,
            "statement_timeout_ms": cfg.DB_STATEMENT_TIMEOUT_MS,
            "dashboard_statement_timeout_ms": cfg.DASHBOARD_STATEMENT_TIMEOUT_MS,
            "account_delete_timeout_ms": cfg.ACCOUNT_DELETE_TIMEOUT_MS,
            "data_health_block_timeout_ms": cfg.DATA_HEALTH_BLOCK_TIMEOUT_MS,
        },
        "scheduler": {
            "running": scheduler.running,
            "state": scheduler.state,
            "jobs": len(scheduler.get_jobs()),
            "workflow_tick_hour": cfg.WORKFLOW_TICK_HOUR,
            "user_digest_hour": cfg.USER_DIGEST_HOUR,
            "ml_retrain_enabled": cfg.ML_RETRAIN_ENABLED,
            "run_max_seconds": cfg.RUN_MAX_SECONDS,
        },
        "degraded": degraded,
    }
