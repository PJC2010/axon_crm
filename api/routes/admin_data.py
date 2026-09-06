"""Platform data health — the shared data layer's vital signs. Deliberately CROSS-TENANT.

The same reviewed exemption from the account_id-scoping rule as
api/routes/admin.py (CLAUDE.md): this router serves the platform operator, is
included in api/main.py with the router-wide require_platform_admin guard, and
tests/test_router_gating.py asserts that guard for every router serving /admin.
No endpoint here may declare a query param named ``token``.

GET  /admin/data-health          — newest snapshot + live queue/staleness figures
POST /admin/data-health/refresh  — recompute the snapshot now (background job)

The heavy figures come from the nightly snapshot (api/data_health.py, migration
0087) and are never computed here. What this endpoint computes live is
index-only or tiny: geocode_queue by status, the unclassified count per org
(idx_properties_unclassified), the two rule-stamp tables and the org names —
each under api/deps.py::soft_query. Rule staleness is decided here rather than
in the snapshot on purpose: a deploy that changes the residential rule must
show every stamp stale immediately, not after the next tick.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api import data_health
from api.admin_audit import record_admin_action
from api.admin_logic import (
    data_health_alerts, match_rate, overlay_account_state, overlay_zip_rule_state,
    pct, rule_summary,
)
from api.deps import (
    dict_fetchall, dict_fetchone, get_db, require_platform_admin, soft_query,
)

log = logging.getLogger(__name__)
router = APIRouter()


def _current_hashes() -> tuple[str, str]:
    """The residential rule as deployed, in both of its stamped forms. They are
    different strings by construction (property_audit hashes every reason,
    parcels hashes the EXCLUDE tier) and each compares only with its own table."""
    from pipeline.parcels import _rule_hash as parcel_rule_hash
    from pipeline.property_audit import rule_hash as property_rule_hash
    return property_rule_hash(), parcel_rule_hash()


def _hcad_source(report: dict) -> str:
    """duckdb | postgres | none — the api/routes/hcad.py ternary, minus the
    extra connection hcad_available() would open: the snapshot already counted
    the mirror."""
    from pipeline import hcad_store
    if hcad_store.db_exists():
        return "duckdb"
    hcad = report.get("hcad") or {}
    return "postgres" if (hcad.get("properties") or 0) > 0 else "none"


@router.get("/admin/data-health")
def admin_data_health(db: PGConn = Depends(get_db)):
    degraded: list[str] = []

    def _q(name, fn, fallback):
        value, timed_out = soft_query(db, fn, fallback)
        if timed_out:
            degraded.append(name)
        return value

    with db.cursor() as cur:
        cur.execute(
            "SELECT id, started_at, finished_at, status, triggered_by, host, report "
            "FROM data_health_snapshots WHERE status IN ('ok', 'partial') "
            "ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        snapshot = dict_fetchone(cur)
        cur.execute(
            "SELECT id, started_at, finished_at, status, triggered_by, error "
            "FROM data_health_snapshots ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        latest = dict_fetchone(cur)
        cur.execute("SELECT id, name FROM accounts")
        names = {r["id"]: r["name"] for r in dict_fetchall(cur)}

    def _geocode(cur):
        cur.execute("SELECT status, COUNT(*) AS n, MIN(queued_at) AS oldest "
                    "FROM geocode_queue GROUP BY status")
        by_status = {r["status"]: r for r in dict_fetchall(cur)}
        cur.execute("SELECT last_error, COUNT(*) AS n FROM geocode_queue "
                    "WHERE status = 'failed' GROUP BY last_error ORDER BY n DESC LIMIT 5")
        errors = dict_fetchall(cur)
        return {
            "queued": (by_status.get("queued") or {}).get("n", 0),
            "failed": (by_status.get("failed") or {}).get("n", 0),
            "done": (by_status.get("done") or {}).get("n", 0),
            "oldest_queued_at": (by_status.get("queued") or {}).get("oldest"),
            "top_errors": errors,
        }

    def _unclassified(cur):
        # Index-only on idx_properties_unclassified (0083): the backlog shrinks
        # toward empty, so this is cheap exactly when it matters least.
        cur.execute("SELECT account_id, COUNT(*) AS n FROM properties "
                    "WHERE non_residential_reasons IS NULL GROUP BY account_id")
        return {r["account_id"]: r["n"] for r in dict_fetchall(cur)}

    def _stamps(sql):
        def _fn(cur):
            cur.execute(sql)
            return dict_fetchall(cur)
        return _fn

    geocode_queue = _q("geocode_queue", _geocode, None)
    live_unclassified = _q("unclassified_live", _unclassified, None)
    property_stamps = _q(
        "property_rule_stamps",
        _stamps("SELECT account_id, rule_hash, classified_at FROM property_rule_stamps"), [])
    parcel_stamps = _q(
        "parcel_rule_stamps",
        _stamps("SELECT zip, rule_hash, classified_at FROM parcel_rule_stamps"), [])

    property_hash, parcel_hash = _current_hashes()
    report = (snapshot or {}).get("report") or {}
    zips = overlay_zip_rule_state(report.get("zips") or [], parcel_stamps, parcel_hash)
    accounts = overlay_account_state(
        report.get("accounts") or [], names, property_stamps, live_unclassified, property_hash)
    rule = {"property_rule_hash": property_hash, "parcel_rule_hash": parcel_hash,
            **rule_summary(zips, accounts)}
    live = {
        "geocode_queue": geocode_queue,
        "hcad_source": "unknown" if snapshot is None else _hcad_source(report),
    }
    now = datetime.now(timezone.utc)
    alerts = data_health_alerts(snapshot, live, rule, now=now)

    summary = None
    if snapshot is not None:
        parcels = report.get("parcels") or {}
        apn = report.get("apn_match") or {}
        rate = match_rate(apn.get("with_apn"), apn.get("matched"))
        summary = {
            "coords_pct": pct(parcels.get("with_coords"), parcels.get("total")),
            "apn_pct": pct(parcels.get("with_apn"), parcels.get("total")),
            "match_rate_pct": None if rate is None else round(100 * rate, 1),
            "unclassified_pct": pct(parcels.get("unclassified"), parcels.get("total")),
            "non_residential_pct": pct(parcels.get("non_residential"), parcels.get("total")),
        }

    refresh = None
    if latest is not None:
        running = latest["status"] == "running"
        age = (now - latest["started_at"]).total_seconds() if latest.get("started_at") else 0
        stalled = running and age > data_health.RUNNING_GRACE_MINUTES * 60
        refresh = {**latest, "running": running and not stalled, "stalled": stalled}

    return {
        "snapshot": snapshot,
        "summary": summary,
        "zips": zips,
        "accounts": accounts,
        "rule": rule,
        "live": live,
        "alerts": alerts,
        "refresh": refresh,
        "job_id": data_health.JOB_ID,
        "degraded": degraded,
    }


@router.post("/admin/data-health/refresh", status_code=202)
def admin_data_health_refresh(
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Recompute the snapshot now, in the background. Refused while a fresh
    `running` row exists — the job is single-writer, and a second request would
    only lose the advisory lock and log a skip."""
    with db.cursor() as cur:
        cur.execute("SELECT id, started_at, status FROM data_health_snapshots "
                    "ORDER BY started_at DESC, id DESC LIMIT 1")
        latest = dict_fetchone(cur)
    if latest and latest["status"] == "running":
        age = (datetime.now(timezone.utc) - latest["started_at"]).total_seconds()
        if age < data_health.RUNNING_GRACE_MINUTES * 60:
            raise HTTPException(
                status_code=409,
                detail="A snapshot is already being computed — give it a few minutes.",
            )
    data_health.enqueue_snapshot()
    record_admin_action(
        db, admin, "data_health.refresh", None, None,
        {"previous_snapshot_id": latest["id"] if latest else None},
    )
    db.commit()
    return {"queued": True, "job_id": data_health.MANUAL_JOB_ID}
