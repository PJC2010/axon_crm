"""APScheduler singleton — runs pipeline jobs in a thread pool inside the FastAPI process."""
import logging
from datetime import datetime, timezone

import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import DATABASE_URL

log = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")

DAY_MAP = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def _job_id(schedule_id: int) -> str:
    return f"pipeline_schedule_{schedule_id}"


def _run_pipeline(run_id: int, zip_code: str, vertical: str | None):
    """Execute the enrichment pipeline and update the pipeline_runs row."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET status = 'running', started_at = NOW() WHERE id = %s",
                (run_id,),
            )
        conn.commit()

        # Import here to avoid circular imports at module load time
        import sys, os
        from types import SimpleNamespace
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from run_pipeline import run_zip

        fake_args = SimpleNamespace(
            vertical=vertical,
            skip="",
            seed_csv=None,
            permit_csv=None,
            limit=None,
        )
        run_zip(zip_code, fake_args)
        result = {"status": "completed", "zip": zip_code}

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET status = 'done', finished_at = NOW(), result_json = %s WHERE id = %s",
                (psycopg2.extras.Json(result), run_id),
            )
        conn.commit()
        log.info("Pipeline run %d done", run_id)

    except Exception as exc:
        log.exception("Pipeline run %d failed", run_id)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET status = 'failed', finished_at = NOW(), "
                    "result_json = %s WHERE id = %s",
                    (psycopg2.extras.Json({"error": str(exc)}), run_id),
                )
            conn.commit()
        except Exception:
            pass
    finally:
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
