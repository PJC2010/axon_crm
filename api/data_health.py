"""Platform data-health snapshot — the nightly report behind GET /admin/data-health.

What an operator wants to know about the shared data layer: how much of the
parcel cache has coordinates and a residential verdict, whether the free
APN→centroid join is still matching, how much of each tenant's book is
unclassified or excludable, where RentCast disagrees with the county, and
whether the 0079 mail-city regression is back. Every one of those is a full
scan of parcels / hcad_properties (~1.5M rows each) or of every tenant's
properties, and the pre-0083 data-quality page is the precedent for what such
a scan does on a page load: QueryCanceled. So this runs as a scheduler tick
(run_snapshot) on its own connection under an advisory lock, lands one JSONB
row in data_health_snapshots (migration 0087), and the admin endpoint
(api/routes/admin_data.py) reads the newest row.

Blocks are independent: each runs under its own statement timeout
(DATA_HEALTH_BLOCK_TIMEOUT_MS) in its own transaction, a failure is recorded
in ``blocks_failed`` and the rest still land, and the row's status says
whether the report is whole (``ok``), holed (``partial``) or missing
(``error``). Only aggregates cross the tenant boundary — counts per org and
per ZIP, never an address, an owner name or a stored value.
"""
import logging
import socket
import time
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2.extras import Json

from config import DATA_HEALTH_BLOCK_TIMEOUT_MS, DATABASE_URL

log = logging.getLogger(__name__)

LOCK_KEY = 742026011          # next in the 7420260xx tick-lock series (api/scheduler.py)
JOB_ID = "data_health_snapshot_daily"
MANUAL_JOB_ID = "data_health_snapshot_manual"
KEEP_SNAPSHOTS = 30
# A refresh request while a `running` row younger than this exists is refused:
# the job is single-writer, and a row this fresh is a live run, not a crash.
RUNNING_GRACE_MINUTES = 30


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _row(cur) -> dict:
    cols = [d[0] for d in cur.description]
    r = cur.fetchone()
    return dict(zip(cols, r)) if r else {}


def _jsonable(value):
    """What json.dumps cannot take from psycopg2: timestamps and Decimals."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _exclude_array_sql() -> str:
    """The EXCLUDE tier as a text[] literal — code constants, never user input."""
    from pipeline.residential import EXCLUDE_REASONS
    return "ARRAY[" + ", ".join(f"'{r}'" for r in EXCLUDE_REASONS) + "]::text[]"


# ── Blocks ────────────────────────────────────────────────────────────────────

def _block_parcels(cur) -> dict:
    cur.execute(
        "SELECT COUNT(*) AS total, COUNT(latitude) AS with_coords, "
        "COUNT(parcel_apn) AS with_apn, "
        "COUNT(*) FILTER (WHERE non_residential IS NULL) AS unclassified, "
        "COUNT(*) FILTER (WHERE non_residential) AS non_residential, "
        "COUNT(property_type) AS property_type, COUNT(year_built) AS year_built, "
        "COUNT(estimated_value) AS estimated_value, COUNT(owner_name) AS owner_name, "
        "MAX(updated_at) AS last_updated_at "
        "FROM parcels"
    )
    return _row(cur)


def _block_apn_match(cur) -> dict:
    # The county_build.report() join: the denominator excludes NULL-APN parcels
    # on purpose (see admin_logic.match_rate).
    cur.execute(
        "SELECT COUNT(*) FILTER (WHERE p.parcel_apn IS NOT NULL) AS with_apn, "
        "COUNT(c.acct) AS matched "
        "FROM parcels p LEFT JOIN hcad_parcel_centroids c ON c.acct = p.parcel_apn"
    )
    return _row(cur)


def _block_zips(cur) -> list[dict]:
    cur.execute(
        "SELECT zip, COUNT(*) AS parcels, COUNT(latitude) AS with_coords, "
        "COUNT(*) FILTER (WHERE non_residential IS NULL) AS unclassified, "
        "COUNT(*) FILTER (WHERE non_residential) AS non_residential "
        "FROM parcels GROUP BY zip"
    )
    by_zip = {r["zip"]: r for r in _rows(cur)}
    # county_zips()'s SQL: the roll's own ZIP list, so a ZIP with county rows
    # and no cache shows up as 0% covered instead of not at all.
    cur.execute(
        "SELECT site_zip AS zip, COUNT(*) AS hcad_rows FROM hcad_properties "
        "WHERE site_zip IS NOT NULL AND site_zip <> '' GROUP BY site_zip"
    )
    for r in _rows(cur):
        row = by_zip.setdefault(r["zip"], {
            "zip": r["zip"], "parcels": 0, "with_coords": 0,
            "unclassified": 0, "non_residential": 0,
        })
        row["hcad_rows"] = r["hcad_rows"]
    for row in by_zip.values():
        row.setdefault("hcad_rows", 0)
    return sorted(by_zip.values(), key=lambda r: (-(r["parcels"] or 0), r["zip"]))


def _block_geocode_sources(cur) -> list[dict]:
    cur.execute(
        "SELECT COALESCE(geocode_source, '(none)') AS source, COUNT(*) AS count "
        "FROM parcels GROUP BY 1 ORDER BY 2 DESC"
    )
    return _rows(cur)


def _block_hcad(cur) -> dict:
    out: dict = {}
    cur.execute("SELECT COUNT(*) AS properties, COUNT(site_city) AS site_city_filled "
                "FROM hcad_properties")
    out.update(_row(cur))
    # hcad_properties carries no load timestamp; the centroid mirror's is the
    # one freshness clock (its loader is a TRUNCATE + reload, so MAX ≈ the
    # last rebuild).
    cur.execute("SELECT COUNT(*) AS centroids, MAX(loaded_at) AS centroids_loaded_at "
                "FROM hcad_parcel_centroids")
    out.update(_row(cur))
    cur.execute("SELECT COUNT(*) AS permits FROM hcad_permits")
    out.update(_row(cur))
    return out


def _block_accounts(cur) -> list[dict]:
    cur.execute(
        "SELECT account_id, COUNT(*) AS properties, COUNT(latitude) AS with_coords, "
        "COUNT(*) FILTER (WHERE non_residential_reasons IS NULL) AS unclassified, "
        f"COUNT(*) FILTER (WHERE non_residential_reasons && {_exclude_array_sql()}) "
        "AS excludable "
        "FROM properties WHERE archived_at IS NULL GROUP BY account_id"
    )
    return _rows(cur)


def _block_discrepancies(cur) -> dict:
    # Open = kept, not overwritten: the sweep recorded a disagreement and left
    # the stored value alone (pipeline/reconcile.py). Counts only.
    cur.execute(
        "SELECT field, source, COUNT(*) AS open FROM property_field_audits "
        "WHERE verdict = 'mismatch' AND resolution = 'kept' "
        "GROUP BY field, source ORDER BY open DESC, field"
    )
    by_field = _rows(cur)
    cur.execute(
        "SELECT account_id, COUNT(*) AS open FROM property_field_audits "
        "WHERE verdict = 'mismatch' AND resolution = 'kept' "
        "GROUP BY account_id ORDER BY open DESC LIMIT 50"
    )
    by_account = _rows(cur)
    return {
        "total_open": sum(r["open"] for r in by_field),
        "by_field": by_field,
        "by_account": by_account,
    }


# tools/audit_data_quality.py section 4: the cohort migration 0079 NULLed —
# HCAD-seeded absentee rows whose city appears inside their own mailing
# address, i.e. the owner's mailing city on the property card. Non-zero after
# 0079 means a writer regressed to mail_city.
_MAIL_CITY_LEAK = (
    "SELECT COUNT(*) FROM {table} WHERE enrichment_flags->>'seed' = 'hcad' "
    "AND owner_occupied IS NOT TRUE AND city IS NOT NULL AND mailing_address IS NOT NULL "
    "AND POSITION(UPPER(city) IN UPPER(mailing_address)) > 0"
)
_NULL_CITY = ("SELECT COUNT(*) FROM {table} WHERE enrichment_flags->>'seed' = 'hcad' "
              "AND city IS NULL")


def _block_city_sanity(cur) -> dict:
    out: dict = {}
    for table in ("parcels", "properties"):
        cur.execute(_MAIL_CITY_LEAK.format(table=table))
        out[f"{table}_mail_city_leak"] = cur.fetchone()[0]
        cur.execute(_NULL_CITY.format(table=table))
        out[f"{table}_null_city"] = cur.fetchone()[0]
    return out


BLOCKS = {
    "parcels": _block_parcels,
    "apn_match": _block_apn_match,
    "zips": _block_zips,
    "geocode_sources": _block_geocode_sources,
    "hcad": _block_hcad,
    "accounts": _block_accounts,
    "discrepancies": _block_discrepancies,
    "city_sanity": _block_city_sanity,
}
BLOCK_NAMES = tuple(BLOCKS)


def build_report(conn, *, block_timeout_ms: int | None = None) -> dict:
    """Run every block on ``conn``. A failed block is None and named in
    ``blocks_failed``; the others still land. Each block is its own
    transaction, so a cancelled statement (or any error) unwinds only itself,
    and the SET LOCAL statement_timeout lapses with it."""
    ms = DATA_HEALTH_BLOCK_TIMEOUT_MS if block_timeout_ms is None else block_timeout_ms
    t0 = time.monotonic()
    report: dict = {"blocks_failed": []}
    for name, fn in BLOCKS.items():
        try:
            with conn.cursor() as cur:
                if ms and ms > 0:
                    cur.execute("SELECT set_config('statement_timeout', %s, true)",
                                (str(int(ms)),))
                report[name] = _jsonable(fn(cur))
            conn.rollback()  # read-only: this only ends the transaction
        except Exception:
            conn.rollback()
            report[name] = None
            report["blocks_failed"].append(name)
            log.exception("data-health block %s failed", name)
    report["duration_seconds"] = round(time.monotonic() - t0, 1)
    return report


# ── The tick ──────────────────────────────────────────────────────────────────

def run_snapshot(triggered_by: str = "schedule"):
    """Compute and store one snapshot. Returns the row id, None when skipped.

    Same shape as the other ticks in api/scheduler.py: own connection, an
    advisory lock so only one web instance computes, one summary log line.
    The `running` row is committed before the scans start so the admin page can
    show a refresh in progress, and is finished (or marked error) whatever the
    blocks do.
    """
    conn = psycopg2.connect(DATABASE_URL)
    row_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            if not cur.fetchone()[0]:
                log.info("Data-health snapshot skipped — another worker holds the lock")
                return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO data_health_snapshots (triggered_by, host) "
                    "VALUES (%s, %s) RETURNING id",
                    (triggered_by, socket.gethostname()),
                )
                row_id = cur.fetchone()[0]
            conn.commit()
            try:
                report = build_report(conn)
                status = "partial" if report["blocks_failed"] else "ok"
                error = None
            except Exception as exc:  # build_report catches per block; belt and braces
                log.exception("Data-health snapshot failed")
                report = {"blocks_failed": list(BLOCK_NAMES)}
                status, error = "error", f"{type(exc).__name__}: {exc}"[:2000]
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE data_health_snapshots SET finished_at = NOW(), status = %s, "
                    "report = %s, error = %s WHERE id = %s",
                    (status, Json(report), error, row_id),
                )
                cur.execute(
                    "DELETE FROM data_health_snapshots WHERE id NOT IN ("
                    "SELECT id FROM data_health_snapshots "
                    "ORDER BY started_at DESC, id DESC LIMIT %s)",
                    (KEEP_SNAPSHOTS,),
                )
            conn.commit()
            log.info("Data-health snapshot #%s %s in %ss (%s)", row_id, status,
                     report.get("duration_seconds"), triggered_by)
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            conn.commit()
    except Exception:
        log.exception("Data-health snapshot tick failed")
    finally:
        conn.close()
    return row_id


def schedule_data_health_snapshot():
    """Register the nightly snapshot cron (idempotent)."""
    from apscheduler.triggers.cron import CronTrigger

    from api.scheduler import scheduler
    from config import WORKFLOW_TICK_HOUR
    scheduler.add_job(
        run_snapshot,
        # :35 — a free slot between recurring invoices (:30) and the account
        # rescore (:45); these are reads and coexist with either.
        trigger=CronTrigger(hour=WORKFLOW_TICK_HOUR, minute=35, timezone="UTC"),
        id=JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduled nightly data-health snapshot at %02d:35 UTC", WORKFLOW_TICK_HOUR)


def enqueue_snapshot() -> None:
    """Fire a snapshot now in the scheduler's thread pool (the admin Refresh).
    Same one-shot shape as api/scheduler.py::enqueue_backfill."""
    from api.scheduler import scheduler
    scheduler.add_job(
        run_snapshot,
        id=MANUAL_JOB_ID,
        kwargs={"triggered_by": "admin"},
        replace_existing=True,
    )
