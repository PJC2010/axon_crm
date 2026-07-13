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


def _run_summary(conn, zip_code: str, account_id: int, sources: dict) -> dict:
    """Plain-language outcome of a pipeline run for the ZIP: how many properties
    are scored, how many at each top grade, and how many paid skip-traces this
    run spent (prospective-user audit P1: per-run transparency kills the fear
    of variable data costs)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE lead_score IS NOT NULL), "
            "       COUNT(*) FILTER (WHERE score_grade = 'A'), "
            "       COUNT(*) FILTER (WHERE score_grade = 'B'), "
            "       COUNT(*) FILTER (WHERE contact_phone IS NOT NULL OR contact_email IS NOT NULL) "
            "FROM properties WHERE zip = %s AND account_id = %s AND archived_at IS NULL",
            (zip_code, account_id),
        )
        scored, grade_a, grade_b, with_contact = cur.fetchone()
    contact = sources.get("contact") or {}
    return {
        "properties_scored": scored,
        "grade_a": grade_a,
        "grade_b": grade_b,
        "with_contact": with_contact,
        "skip_traces_used": contact.get("ok", 0),
        "storm_hits": (sources.get("signals") or {}).get("storm_event", 0),
    }


def _send_storm_mode_alert(conn, account_id: int, zip_code: str, hits: int) -> None:
    """Storm Mode: one aggregated owner email when a run detects fresh storm
    damage in a ZIP — the addresses are already scored and waiting. Fails soft
    (no email config / no owner = skip); an alert failure never fails the run."""
    from api import notifications
    from config import APP_BASE_URL

    try:
        if not notifications.email_configured():
            return
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email FROM users WHERE account_id = %s AND role = 'owner' "
                "AND is_active = TRUE ORDER BY id LIMIT 1",
                (account_id,),
            )
            owner = cur.fetchone()
        if not owner or not owner[0]:
            return
        # Grade split of the just-hit homes (signal_events written moments ago).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FILTER (WHERE p.score_grade IN ('A','B')) "
                "FROM signal_events se JOIN properties p ON p.id = se.property_id "
                "WHERE se.account_id = %s AND se.signal_type = 'storm_event' "
                "  AND p.zip = %s AND se.created_at > NOW() - INTERVAL '2 hours'",
                (account_id, zip_code),
            )
            top_grades = cur.fetchone()[0] or 0
        subject = f"Storm Mode: {hits} home{'s' if hits != 1 else ''} in {zip_code} just took storm damage"
        html = (
            '<div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">'
            f'<h2 style="margin:0 0 8px">Storm activity in {zip_code}</h2>'
            f"<p>Axon just matched fresh NOAA storm reports to <strong>{hits}</strong> "
            f"propert{'ies' if hits != 1 else 'y'} in your territory"
            + (f" — <strong>{top_grades}</strong> of them grade A or B" if top_grades else "")
            + ". The out-of-town crews are loading their trucks; your list is already ranked.</p>"
            f'<p style="margin:24px 0"><a href="{APP_BASE_URL}/dashboard" '
            'style="background:#1a5a75;color:#fff;text-decoration:none;padding:12px 24px;'
            'border-radius:8px;font-weight:600">Open your leads</a></p>'
            "</div>"
        )
        notifications.send_email(to_email=owner[0], subject=subject, html=html)
        log.info("Storm Mode alert sent: account=%d zip=%s hits=%d", account_id, zip_code, hits)
    except Exception:
        log.warning("Storm Mode alert failed for account %d zip %s", account_id, zip_code,
                    exc_info=True)


def _run_pipeline(run_id: int, zip_code: str, vertical: str | None, account_id: int,
                  top_n: int | None = None, center_address: str | None = None,
                  radius_mi: float | None = None, region_id: str | None = None,
                  seed_source: str | None = None):
    """Execute the enrichment pipeline step-by-step, checking for cancellation between steps.

    `top_n` (Top-N cap) and `center_address` + `radius_mi` (radius-from-address)
    are optional volume controls. When either is set, a selection step runs after
    the free steps and before paid enrichment so only a focused subset incurs
    paid API cost.

    `region_id` (HCAD named neighborhood) runs the same per-ZIP steps for every
    ZIP the region touches, seeding each ZIP from the free local HCAD data
    instead of the paid RentCast scan. When it is None the run targets the single
    `zip_code` exactly as before.

    `seed_source` picks where step 1 gets its addresses for a plain ZIP run:
    "hcad" (free, local Harris County data) or "rentcast" (paid address scan).
    None defers to the SEED_SOURCE env default. Region runs ignore it — they
    always seed from HCAD. Choosing "hcad" does not skip RentCast entirely: the
    later property step still gap-fills whatever HCAD left NULL.
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

    def _run_one_zip(zip_code: str) -> dict | None:
        """Run the full step sequence for one ZIP. Returns the per-ZIP result, or
        None if the run was cancelled mid-way (status already set)."""
        sources: dict = {}

        # Step 1 — Seed (free HCAD for region runs and for seed_source="hcad",
        # else RentCast/CSV). `seed()` resolves the default when seed_source is None.
        if _check_cancel(): return None
        from config import SEED_SOURCE
        from pipeline.seed import seed
        n = seed(zip_code, account_id, csv_path=None, limit=None, region_id=region_id,
                 seed_source=seed_source)
        resolved = "hcad" if region_id else (seed_source or SEED_SOURCE or "rentcast")
        log.info("[1/8] run=%d Seed (%s): %d records", run_id, resolved, n)

        # Step 2 — Census
        if _check_cancel(): return None
        from pipeline.census import enrich_census
        n = enrich_census(zip_code, account_id)
        log.info("[2/8] run=%d Census: %d updated", run_id, n)

        # Step 3 — Geocode
        if _check_cancel(): return None
        from pipeline.geocode import enrich_geocode
        n = enrich_geocode(zip_code, account_id)
        log.info("[3/8] run=%d Geocode: %d updated", run_id, n)

        # Step 4 — HCAD fallback (free) — runs BEFORE paid RentCast so it
        # only spends calls on fields HCAD couldn't fill.
        if _check_cancel(): return None
        from pipeline.hcad_enrichment import enrich_hcad
        n = enrich_hcad(zip_code, account_id)
        log.info("[4/8] run=%d HCAD fallback: %d backfilled", run_id, n)

        # Step 4.5 — Selection (volume control) — after all FREE steps, before
        # any PAID enrichment. Marks the subset that proceeds to paid steps.
        if capped:
            if _check_cancel(): return None
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

        # Step 5 — Property detail (RentCast)
        if _check_cancel(): return None
        from pipeline.property import enrich_property
        counters = enrich_property(zip_code, account_id, selected_only=capped)
        sources.update(counters)
        log.info("[5/8] run=%d Property: %s", run_id, counters)

        # Step 6 — Permits
        if _check_cancel(): return None
        from pipeline.permits import enrich_permits
        n = enrich_permits(zip_code, account_id, csv_path=None)
        log.info("[6/8] run=%d Permits: %d updated", run_id, n)

        # Step 6.5 — Storm/hail enrichment (free, needs lat/lng from step 3).
        if _check_cancel(): return None
        from pipeline.storm import enrich_storm
        n = enrich_storm(zip_code, account_id)
        log.info("[6.5/8] run=%d Storm: %d matched", run_id, n)

        # Step 6.75 — Neighborhood value benchmark. Account-wide (geohash cells
        # cross ZIP lines) and must precede scoring so the neighborhood signal
        # reads fresh ratios that include this ZIP's just-enriched values.
        if _check_cancel(): return None
        from pipeline.neighborhood import recompute_neighborhood_values
        recompute_neighborhood_values(conn, account_id)

        # Step 7 — Score
        if _check_cancel(): return None
        from pipeline.scorer import score_zip
        n = score_zip(zip_code, account_id, vertical=vertical)
        log.info("[7/8] run=%d Scoring: %d scored", run_id, n)

        # Step 7.5 — Precision trim: now that real scores exist, cut the
        # over-sampled selection back to exactly top_n before skip-tracing.
        if capped and top_n:
            if _check_cancel(): return None
            from pipeline.select import trim_to_top_n
            kept = trim_to_top_n(conn, zip_code, account_id, top_n)
            log.info("[7.5/8] run=%d Trim: kept top %d", run_id, kept)

        # Step 8 — Contact / skip-trace (after scoring for optional grade gate)
        if _check_cancel(): return None
        from pipeline.contact import enrich_contact
        sources["contact"] = enrich_contact(zip_code, account_id, selected_only=capped)
        log.info("[8/8] run=%d Contact: %s", run_id, sources["contact"])

        # Step 8.5 — Demographics / life-events (paid, optional, grade-gated)
        if _check_cancel(): return None
        from pipeline.demographics import enrich_demographics
        sources["demographics"] = enrich_demographics(zip_code, account_id, selected_only=capped)
        log.info("[8.5/8] run=%d Demographics: %s", run_id, sources["demographics"])

        # Step 9 — Timing signals (free): diff sale/permit/storm fields against the
        # previous run's baseline, record signal_events, fire signal_event rules.
        if _check_cancel(): return None
        from pipeline.signals import detect_signals
        sources["signals"] = detect_signals(zip_code, account_id)
        log.info("[signals] run=%d %s", run_id, sources["signals"])

        # Storm Mode (audit P1): the morning-after moment. When this run found
        # fresh storm hits, email the owner the headline while the 48-hour
        # window is open — one aggregated email, not one per property.
        storm_hits = (sources["signals"] or {}).get("storm_event", 0)
        if storm_hits:
            _send_storm_mode_alert(conn, account_id, zip_code, storm_hits)

        # Coverage snapshot for the frontend + the plain-language run summary
        # ("what did this run cost / produce") shown in Settings → Recent runs.
        from pipeline.coverage import fill_rates
        coverage = fill_rates(conn, zip_code, account_id)
        return {"zip": zip_code, "sources": sources, "coverage": coverage,
                "summary": _run_summary(conn, zip_code, account_id, sources)}

    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET status = 'running', started_at = NOW() WHERE id = %s",
                (run_id,),
            )
        conn.commit()

        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        # Region runs fan out across every ZIP the neighborhood touches; a plain
        # ZIP run is just a single-element list.
        if region_id:
            from pipeline import hcad_store
            zips = hcad_store.region_zips(region_id)
            if not zips:
                _set_status("failed", {"error": f"No parcels found for region {region_id}"})
                return
        else:
            zips = [zip_code]

        by_zip: dict = {}
        for z in zips:
            result = _run_one_zip(z)
            if result is None:
                return   # cancelled — status already set
            by_zip[z] = result

        if region_id:
            _set_status("done", {
                "status": "completed",
                "region_id": region_id,
                "zips": zips,
                "by_zip": by_zip,
            })
        else:
            # Preserve the original single-ZIP result shape for existing UI.
            single = by_zip[zip_code]
            _set_status("done", {
                "status": "completed",
                "zip": zip_code,
                "sources": single["sources"],
                "coverage": single["coverage"],
                "summary": single["summary"],
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
                radius_mi: float | None = None, seed_source: str | None = None):
    """Fire a one-off pipeline run immediately in the thread pool."""
    scheduler.add_job(
        _run_pipeline,
        id=f"run_{run_id}",
        args=[run_id, zip_code, vertical, account_id, top_n, center_address, radius_mi],
        kwargs={"seed_source": seed_source},
        replace_existing=True,
    )


def enqueue_region_run(run_id: int, region_id: str, vertical: str | None, account_id: int,
                       top_n: int | None = None, center_address: str | None = None,
                       radius_mi: float | None = None):
    """Fire a one-off region run (free HCAD seed, fanned out across the region's
    ZIPs) immediately in the thread pool."""
    scheduler.add_job(
        _run_pipeline,
        id=f"run_{run_id}",
        kwargs={"run_id": run_id, "zip_code": "", "vertical": vertical,
                "account_id": account_id, "top_n": top_n, "center_address": center_address,
                "radius_mi": radius_mi, "region_id": region_id},
        replace_existing=True,
    )


def retrain_models():
    """Nightly: refresh outcome labels and retrain the predictive models.

    Runs entirely in-process (pure-Python trainer); safe to fail without affecting
    the rest of the app — a stale champion simply stays active until the next run.
    """
    from config import ML_STALE_OPEN_DAYS  # noqa: F401  (kept explicit for clarity)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        from pipeline.ml.train import train_all
        result = train_all(conn)
        log.info("Model retrain finished: %s", result.get("promoted"))
    except Exception:
        log.exception("Model retrain job failed")
    finally:
        conn.close()


def schedule_retraining():
    """Register the daily retrain cron (idempotent — replaces any existing job)."""
    from config import ML_RETRAIN_HOUR
    scheduler.add_job(
        retrain_models,
        trigger=CronTrigger(hour=ML_RETRAIN_HOUR, minute=0, timezone="UTC"),
        id="ml_retrain_nightly",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled nightly model retrain at %02d:00 UTC", ML_RETRAIN_HOUR)


# Fixed advisory-lock key for the workflow tick: the scheduler runs in-process
# in every Uvicorn worker, so without this a multi-worker deploy would evaluate
# the daily rules N times. The firings ledger already dedups actions; the lock
# just avoids the wasted concurrent scans.
WORKFLOW_TICK_LOCK_KEY = 742026001
ACCOUNT_RESCORE_LOCK_KEY = 742026002
RECURRING_INVOICE_LOCK_KEY = 742026003


def run_workflow_daily_tick():
    """Daily: evaluate date_offset / inactivity workflow rules for all accounts."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (WORKFLOW_TICK_LOCK_KEY,))
            if not cur.fetchone()[0]:
                log.info("Workflow tick skipped — another worker holds the lock")
                return
        try:
            from api.workflow_engine import run_daily_rules
            summary = run_daily_rules(conn)
            log.info("Workflow daily tick finished: %s", summary)
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (WORKFLOW_TICK_LOCK_KEY,))
            conn.commit()
    except Exception:
        log.exception("Workflow daily tick failed")
    finally:
        conn.close()


def schedule_workflow_tick():
    """Register the daily workflow-rule cron (idempotent — replaces any existing job)."""
    from config import WORKFLOW_TICK_HOUR
    scheduler.add_job(
        run_workflow_daily_tick,
        trigger=CronTrigger(hour=WORKFLOW_TICK_HOUR, minute=15, timezone="UTC"),
        id="workflow_daily_tick",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled daily workflow tick at %02d:15 UTC", WORKFLOW_TICK_HOUR)


def run_account_rescore_tick():
    """Daily: rescore non-property accounts (insurance renewal, retail RFM) whose
    scores drift with time (days-to-renewal, days-since-last-order)."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (ACCOUNT_RESCORE_LOCK_KEY,))
            if not cur.fetchone()[0]:
                log.info("Account rescore skipped — another worker holds the lock")
                return
        try:
            from pipeline.account_rescore import rescore_all_accounts
            summary = rescore_all_accounts(conn)
            log.info("Account rescore finished: %s", summary)
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (ACCOUNT_RESCORE_LOCK_KEY,))
            conn.commit()
    except Exception:
        log.exception("Account rescore tick failed")
    finally:
        conn.close()


def schedule_account_rescore():
    """Register the daily account-rescore cron (idempotent)."""
    from config import WORKFLOW_TICK_HOUR
    scheduler.add_job(
        run_account_rescore_tick,
        # 30 min after the workflow tick so renewal-proximity scores are fresh
        # before any date-based rules that read them run the next morning.
        trigger=CronTrigger(hour=WORKFLOW_TICK_HOUR, minute=45, timezone="UTC"),
        id="account_rescore_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled daily account rescore at %02d:45 UTC", WORKFLOW_TICK_HOUR)


def run_recurring_invoice_tick():
    """Daily: generate the next occurrence of every due recurring invoice."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (RECURRING_INVOICE_LOCK_KEY,))
            if not cur.fetchone()[0]:
                log.info("Recurring invoice tick skipped — another worker holds the lock")
                return
        try:
            from api.recurring_invoices import generate_due_invoices
            summary = generate_due_invoices(conn)
            log.info("Recurring invoice tick finished: %s", summary)
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (RECURRING_INVOICE_LOCK_KEY,))
            conn.commit()
    except Exception:
        log.exception("Recurring invoice tick failed")
    finally:
        conn.close()


def schedule_recurring_invoices():
    """Register the daily recurring-invoice cron (idempotent)."""
    from config import WORKFLOW_TICK_HOUR
    scheduler.add_job(
        run_recurring_invoice_tick,
        trigger=CronTrigger(hour=WORKFLOW_TICK_HOUR, minute=30, timezone="UTC"),
        id="recurring_invoices_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled daily recurring invoices at %02d:30 UTC", WORKFLOW_TICK_HOUR)


TRIAL_EXPIRY_LOCK_KEY = 742026005


def run_trial_expiry_tick():
    """Daily: downgrade expired self-serve trials with no subscription to starter."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (TRIAL_EXPIRY_LOCK_KEY,))
            if not cur.fetchone()[0]:
                log.info("Trial expiry tick skipped — another worker holds the lock")
                return
        try:
            from api.billing import expire_stale_trials
            n = expire_stale_trials(conn)
            if n:
                log.info("Trial expiry tick: downgraded %d account(s) to starter", n)
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (TRIAL_EXPIRY_LOCK_KEY,))
            conn.commit()
    except Exception:
        log.exception("Trial expiry tick failed")
    finally:
        conn.close()


def schedule_trial_expiry():
    """Register the daily trial-expiry cron (idempotent)."""
    from config import WORKFLOW_TICK_HOUR
    scheduler.add_job(
        run_trial_expiry_tick,
        trigger=CronTrigger(hour=WORKFLOW_TICK_HOUR, minute=50, timezone="UTC"),
        id="trial_expiry_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled daily trial expiry at %02d:50 UTC", WORKFLOW_TICK_HOUR)


GEO_RESCORE_LOCK_KEY = 742026004


def _run_customer_geo_rescore(account_id: int, customer_id: int):
    """Background worker: re-score leads within the blast radius of a new customer."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        from pipeline.geo_score_store import refresh_service_area, rescore_nearby_leads_for_customer
        # A new customer both grows the derived service area and shifts nearby
        # proximity/density — refresh the area first so the gate is current.
        refresh_service_area(conn, account_id)
        n = rescore_nearby_leads_for_customer(conn, account_id, customer_id)
        log.info("Customer geo rescore: account=%d customer=%d rescored=%d", account_id, customer_id, n)
    except Exception:
        conn.rollback()
        log.exception("Customer geo rescore failed (account=%d customer=%d)", account_id, customer_id)
    finally:
        conn.close()


def enqueue_customer_geo_rescore(account_id: int, customer_id: int):
    """Fire-and-forget: a lead just became a customer — re-score its neighbors off
    the request path (juncto geo layer). Safe no-op if the scheduler isn't running
    (e.g. under tests), so the status-change path never fails because of geo."""
    try:
        scheduler.add_job(
            _run_customer_geo_rescore,
            id=f"geo_rescore_customer_{account_id}_{customer_id}",
            args=[account_id, customer_id],
            replace_existing=True,
            misfire_grace_time=3600,
        )
    except Exception:
        log.exception("Could not enqueue customer geo rescore (account=%d customer=%d)",
                      account_id, customer_id)


def run_geo_rescore_tick():
    """Nightly: drain the geocode queue, refresh derived service areas, and
    re-score every account's leads whose geo inputs may have drifted."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (GEO_RESCORE_LOCK_KEY,))
            if not cur.fetchone()[0]:
                log.info("Geo rescore skipped — another worker holds the lock")
                return
        try:
            from pipeline.geocode_provider import process_queue
            from pipeline.geo_score_store import refresh_service_area, rescore_leads
            from pipeline.geo_cluster_store import backfill_h3, recompute_clusters
            process_queue(conn, limit=1000)
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM accounts")
                account_ids = [r[0] for r in cur.fetchall()]
            total = 0
            for account_id in account_ids:
                try:
                    # H3 first so freshly geocoded rows land in a hex; rescore before
                    # clustering so cluster_id tags rows that carry current scores.
                    backfill_h3(conn, account_id)
                    refresh_service_area(conn, account_id)
                    total += rescore_leads(conn, account_id)
                    recompute_clusters(conn, account_id)
                except Exception:
                    conn.rollback()
                    log.exception("Geo rescore failed for account %d", account_id)
            log.info("Geo rescore tick finished: %d lead(s) across %d account(s)",
                     total, len(account_ids))
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (GEO_RESCORE_LOCK_KEY,))
            conn.commit()
    except Exception:
        log.exception("Geo rescore tick failed")
    finally:
        conn.close()


def schedule_geo_rescore():
    """Register the nightly geo-rescore cron (idempotent)."""
    from config import WORKFLOW_TICK_HOUR
    scheduler.add_job(
        run_geo_rescore_tick,
        # After the account rescore (…:45) so property scores are fresh before the
        # geo blend reads them.
        trigger=CronTrigger(hour=WORKFLOW_TICK_HOUR, minute=50, timezone="UTC"),
        id="geo_rescore_nightly",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled nightly geo rescore at %02d:50 UTC", WORKFLOW_TICK_HOUR)


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
