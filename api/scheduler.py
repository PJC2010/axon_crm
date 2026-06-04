"""APScheduler singleton — runs pipeline jobs in a thread pool inside the FastAPI process."""
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import DATABASE_URL

log = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")

# ── Cancellation flags ────────────────────────────────────────────────────────
# run_id → True means a cancel has been requested for that run
_cancel_flags: set[int] = set()


def request_cancel(run_id: int) -> None:
    """Signal a running pipeline to stop after its current step."""
    _cancel_flags.add(run_id)


def is_cancelled(run_id: int) -> bool:
    return run_id in _cancel_flags


def _clear_cancel(run_id: int) -> None:
    _cancel_flags.discard(run_id)

DAY_MAP = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def _job_id(schedule_id: int) -> str:
    return f"pipeline_schedule_{schedule_id}"


def _run_pipeline(run_id: int, zip_code: str, vertical: str | None):
    """Execute the enrichment pipeline step-by-step, checking for cancellation between steps."""
    conn = psycopg2.connect(DATABASE_URL)

    def _set_status(status: str, result: dict | None = None):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET status = %s, finished_at = NOW(), result_json = %s WHERE id = %s",
                (status, psycopg2.extras.Json(result or {}), run_id),
            )
        conn.commit()

    def _check_cancel() -> bool:
        if is_cancelled(run_id):
            log.info("Pipeline run %d cancelled", run_id)
            _set_status("cancelled", {"reason": "cancelled by user"})
            _clear_cancel(run_id)
            return True
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET status = 'running', started_at = NOW() WHERE id = %s",
                (run_id,),
            )
        conn.commit()

        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        sources: dict = {}

        # Step 1 — Seed
        if _check_cancel(): return
        from pipeline.seed import seed
        n = seed(zip_code, csv_path=None, limit=None)
        log.info("[1/8] run=%d Seed: %d records", run_id, n)

        # Step 2 — Census
        if _check_cancel(): return
        from pipeline.census import enrich_census
        n = enrich_census(zip_code)
        log.info("[2/8] run=%d Census: %d updated", run_id, n)

        # Step 3 — Geocode
        if _check_cancel(): return
        from pipeline.geocode import enrich_geocode
        n = enrich_geocode(zip_code)
        log.info("[3/8] run=%d Geocode: %d updated", run_id, n)

        # Step 4 — HCAD fallback (free) — runs BEFORE paid RentCast/Attom so they
        # only spend calls on fields HCAD couldn't fill.
        if _check_cancel(): return
        from pipeline.hcad_enrichment import enrich_hcad
        n = enrich_hcad(zip_code)
        log.info("[4/8] run=%d HCAD fallback: %d backfilled", run_id, n)

        # Step 5 — Property detail (RentCast → Attom)
        if _check_cancel(): return
        from pipeline.property import enrich_property
        counters = enrich_property(zip_code)
        sources.update(counters)
        log.info("[5/8] run=%d Property: %s", run_id, counters)

        # Step 6 — Permits
        if _check_cancel(): return
        from pipeline.permits import enrich_permits
        n = enrich_permits(zip_code, csv_path=None)
        log.info("[6/8] run=%d Permits: %d updated", run_id, n)

        # Step 7 — Score
        if _check_cancel(): return
        from pipeline.scorer import score_zip
        n = score_zip(zip_code, vertical=vertical)
        log.info("[7/8] run=%d Scoring: %d scored", run_id, n)

        # Step 8 — Contact / skip-trace (after scoring for optional grade gate)
        if _check_cancel(): return
        from pipeline.contact import enrich_contact
        sources["contact"] = enrich_contact(zip_code)
        log.info("[8/8] run=%d Contact: %s", run_id, sources["contact"])

        # Coverage snapshot for the frontend.
        from pipeline.coverage import fill_rates
        coverage = fill_rates(conn, zip_code)

        _set_status("done", {
            "status": "completed",
            "zip": zip_code,
            "sources": sources,
            "coverage": coverage,
        })
        log.info("Pipeline run %d done", run_id)

    except Exception as exc:
        log.exception("Pipeline run %d failed", run_id)
        try:
            _set_status("failed", {"error": str(exc)})
        except Exception:
            pass
    finally:
        _clear_cancel(run_id)
        conn.close()


def _schedule_trigger(schedule: dict) -> CronTrigger:
    day = DAY_MAP.get((schedule["day_of_week"] or "monday").lower(), "mon")
    hour = int(schedule.get("hour", 6))
    return CronTrigger(day_of_week=day, hour=hour, minute=0, timezone="UTC")


def _scheduled_job(schedule_id: int, zip_code: str, vertical: str | None):
    """Wrapper that creates a pipeline_runs row then kicks off the pipeline."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (schedule_id, zip, vertical, triggered_by) "
                "VALUES (%s, %s, %s, 'schedule') RETURNING id",
                (schedule_id, zip_code, vertical),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    _run_pipeline(run_id, zip_code, vertical)


def add_schedule_job(schedule: dict):
    trigger = _schedule_trigger(schedule)
    scheduler.add_job(
        _scheduled_job,
        trigger=trigger,
        id=_job_id(schedule["id"]),
        args=[schedule["id"], schedule["zip"], schedule.get("vertical")],
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled pipeline job %s: %s @ %s", _job_id(schedule["id"]), schedule["zip"], trigger)


def remove_schedule_job(schedule_id: int):
    job_id = _job_id(schedule_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def enqueue_run(run_id: int, zip_code: str, vertical: str | None):
    """Fire a one-off pipeline run immediately in the thread pool."""
    scheduler.add_job(
        _run_pipeline,
        id=f"run_{run_id}",
        args=[run_id, zip_code, vertical],
        replace_existing=True,
    )


def load_active_schedules():
    """Called at startup — restore all active schedules from the DB into APScheduler."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pipeline_schedules WHERE is_active = TRUE")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        for row in rows:
            add_schedule_job(row)
        log.info("Loaded %d active pipeline schedule(s)", len(rows))
    except Exception:
        log.exception("Could not load pipeline schedules at startup")
