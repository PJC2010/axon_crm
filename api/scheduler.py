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


def _run_pipeline(run_id: int, zip_code: str, vertical: str | None, account_id: int,
                  top_n: int | None = None, center_address: str | None = None,
                  radius_mi: float | None = None):
    """Execute the enrichment pipeline step-by-step, checking for cancellation between steps.

    `top_n` (Top-N cap) and `center_address` + `radius_mi` (radius-from-address)
    are optional volume controls. When either is set, a selection step runs after
    the free steps and before paid enrichment so only a focused subset incurs
    paid API cost.
    """
    conn = psycopg2.connect(DATABASE_URL)
    capped = bool(top_n or (center_address and radius_mi))

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
        n = seed(zip_code, account_id, csv_path=None, limit=None)
        log.info("[1/8] run=%d Seed: %d records", run_id, n)

        # Step 2 — Census
        if _check_cancel(): return
        from pipeline.census import enrich_census
        n = enrich_census(zip_code, account_id)
        log.info("[2/8] run=%d Census: %d updated", run_id, n)

        # Step 3 — Geocode
        if _check_cancel(): return
        from pipeline.geocode import enrich_geocode
        n = enrich_geocode(zip_code, account_id)
        log.info("[3/8] run=%d Geocode: %d updated", run_id, n)

        # Step 4 — HCAD fallback (free) — runs BEFORE paid RentCast/Attom so they
        # only spend calls on fields HCAD couldn't fill.
        if _check_cancel(): return
        from pipeline.hcad_enrichment import enrich_hcad
        n = enrich_hcad(zip_code, account_id)
        log.info("[4/8] run=%d HCAD fallback: %d backfilled", run_id, n)

        # Step 4.5 — Selection (volume control) — after all FREE steps, before
        # any PAID enrichment. Marks the subset that proceeds to paid steps.
        if capped:
            if _check_cancel(): return
            from pipeline.select import select_for_enrichment
            from pipeline.geocode import geocode_address
            center = None
            if center_address and radius_mi:
                center = geocode_address(center_address)
                if center is None:
                    log.warning("run=%d could not geocode center address %r — "
                                "radius filter skipped", run_id, center_address)
            sources["selection"] = select_for_enrichment(
                conn, zip_code, account_id, top_n=top_n, center=center,
                radius_mi=radius_mi, vertical=vertical,
            )
            log.info("[4.5/8] run=%d Selection: %s", run_id, sources["selection"])

        # Step 5 — Property detail (RentCast → Attom)
        if _check_cancel(): return
        from pipeline.property import enrich_property
        counters = enrich_property(zip_code, account_id, selected_only=capped)
        sources.update(counters)
        log.info("[5/8] run=%d Property: %s", run_id, counters)

        # Step 6 — Permits
        if _check_cancel(): return
        from pipeline.permits import enrich_permits
        n = enrich_permits(zip_code, account_id, csv_path=None)
        log.info("[6/8] run=%d Permits: %d updated", run_id, n)

        # Step 7 — Score
        if _check_cancel(): return
        from pipeline.scorer import score_zip
        n = score_zip(zip_code, account_id, vertical=vertical)
        log.info("[7/8] run=%d Scoring: %d scored", run_id, n)

        # Step 7.5 — Precision trim: now that real scores exist, cut the
        # over-sampled selection back to exactly top_n before skip-tracing.
        if capped and top_n:
            if _check_cancel(): return
            from pipeline.select import trim_to_top_n
            kept = trim_to_top_n(conn, zip_code, account_id, top_n)
            log.info("[7.5/8] run=%d Trim: kept top %d", run_id, kept)

        # Step 8 — Contact / skip-trace (after scoring for optional grade gate)
        if _check_cancel(): return
        from pipeline.contact import enrich_contact
        sources["contact"] = enrich_contact(zip_code, account_id, selected_only=capped)
        log.info("[8/8] run=%d Contact: %s", run_id, sources["contact"])

        # Step 9 — Timing signals (free): diff sale/permit fields against the
        # previous run's baseline, record signal_events, fire signal_event rules.
        if _check_cancel(): return
        from pipeline.signals import detect_signals
        sources["signals"] = detect_signals(zip_code, account_id)
        log.info("[signals] run=%d %s", run_id, sources["signals"])

        # Coverage snapshot for the frontend.
        from pipeline.coverage import fill_rates
        coverage = fill_rates(conn, zip_code, account_id)

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


def _scheduled_job(schedule_id: int, zip_code: str, vertical: str | None, account_id: int,
                   top_n: int | None = None, center_address: str | None = None,
                   radius_mi: float | None = None):
    """Wrapper that creates a pipeline_runs row then kicks off the pipeline."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs "
                "(schedule_id, zip, vertical, top_n, center_address, radius_mi, triggered_by, account_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'schedule', %s) RETURNING id",
                (schedule_id, zip_code, vertical, top_n, center_address, radius_mi, account_id),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    _run_pipeline(run_id, zip_code, vertical, account_id, top_n=top_n,
                  center_address=center_address, radius_mi=radius_mi)


def add_schedule_job(schedule: dict):
    trigger = _schedule_trigger(schedule)
    scheduler.add_job(
        _scheduled_job,
        trigger=trigger,
        id=_job_id(schedule["id"]),
        args=[schedule["id"], schedule["zip"], schedule.get("vertical"),
              schedule["account_id"], schedule.get("top_n"),
              schedule.get("center_address"), schedule.get("radius_mi")],
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled pipeline job %s: %s @ %s", _job_id(schedule["id"]), schedule["zip"], trigger)


def remove_schedule_job(schedule_id: int):
    job_id = _job_id(schedule_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def enqueue_run(run_id: int, zip_code: str, vertical: str | None, account_id: int,
                top_n: int | None = None, center_address: str | None = None,
                radius_mi: float | None = None):
    """Fire a one-off pipeline run immediately in the thread pool."""
    scheduler.add_job(
        _run_pipeline,
        id=f"run_{run_id}",
        args=[run_id, zip_code, vertical, account_id, top_n, center_address, radius_mi],
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
