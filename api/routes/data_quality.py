"""
GET  /api/property-data/audit          — per-field null report + what a sweep would cost
POST /api/property-data/backfill       — run a RentCast gap-fill / verification sweep
GET  /api/property-data/discrepancies  — stored values RentCast disagrees with

The audit is free (pure SQL, no vendor calls) and safe to hit on a page load.
The backfill spends money per property, so it is owner-only, rate-limited, and
runs in the scheduler's thread pool tracked as a `pipeline_runs` row — the same
place ZIP runs report to, so /api/pipeline/runs lists it and /api/pipeline/runs/
{id} returns its result.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel, Field

from api.deps import dict_fetchone, get_current_user, get_db, require_owner
from api.entitlements import require_module

router = APIRouter()

# Data-acquisition endpoints, gated like the rest of the prospecting surface.
_prospecting = Depends(require_module("prospecting"))

# `pipeline_runs.zip` is NOT NULL and holds a sentinel for non-ZIP runs (region
# runs already use "region:<id>"). An account-wide sweep gets its own.
BACKFILL_LABEL = "backfill"

DISCREPANCY_LIMIT = 100


class BackfillRequest(BaseModel):
    zip: Optional[str] = None
    # fill: write only into NULLs, record disagreements without acting on them.
    # refresh: additionally overwrite the fields that legitimately move (market
    # estimate, latest sale, owner-occupancy). Never the county's structural facts.
    mode: Literal["fill", "refresh"] = "fill"
    limit: Optional[int] = Field(default=None, ge=1, le=25_000)
    # Plan the sweep and report what it would touch without spending anything.
    dry_run: bool = False
    # Re-score the affected ZIPs afterwards — the sweep fills scoring inputs.
    rescore: bool = True


@router.get("/property-data/audit")
def property_data_audit(
    zip: Optional[str] = Query(None, description="Restrict to one ZIP"),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
    _mod: dict = _prospecting,
):
    """What is missing from this account's property data, and what filling it costs.

    Free: no vendor calls, nothing written. `rentcast.eligible` is the number of
    properties the next sweep would actually pay for — `gap_rows` minus the ones
    still inside their PROPERTY_RECHECK_DAYS cooldown.
    """
    from pipeline.backfill import audit
    return audit(db, user["account_id"], zip_code=zip)


@router.post("/property-data/backfill", status_code=201)
def property_data_backfill(
    body: BackfillRequest,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
    _mod: dict = _prospecting,
):
    """Queue a RentCast sweep over this account's properties.

    Returns the `pipeline_runs` row immediately; poll /api/pipeline/runs/{id} for
    the result, and DELETE it to cancel — the sweep checks between properties and
    keeps whatever it has already paid for.
    """
    from api.ratelimit import pipeline_run_limiter
    from api.scheduler import enqueue_backfill

    acct = current_user["account_id"]
    # Real enrichment-API dollars per property — same throttle as a manual run.
    # A dry run costs nothing, so it is exempt.
    if not body.dry_run:
        pipeline_run_limiter.check(f"acct:{acct}")

    zip_label = body.zip or BACKFILL_LABEL
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (zip, triggered_by, account_id) "
            "VALUES (%s, 'manual', %s) RETURNING *",
            (zip_label, acct),
        )
        run = dict_fetchone(cur)
        db.commit()

    enqueue_backfill(run["id"], acct, zip_code=body.zip, mode=body.mode,
                     limit=body.limit, dry_run=body.dry_run, rescore=body.rescore)
    return run


@router.get("/property-data/discrepancies")
def property_data_discrepancies(
    field: Optional[str] = Query(None, description="Restrict to one property field"),
    zip: Optional[str] = Query(None, description="Restrict to one ZIP"),
    limit: int = Query(DISCREPANCY_LIMIT, ge=1, le=1000),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
    _mod: dict = _prospecting,
):
    """Fields where what we store disagrees with what RentCast returned.

    A sweep in fill mode records these rather than acting on them: for structural
    facts the county appraisal district is the better record, and estimated_value
    feeds lead scoring, so an automatic overwrite would silently move grades.
    """
    from pipeline.backfill import discrepancy_summary, list_discrepancies
    try:
        items = list_discrepancies(db, user["account_id"], field=field,
                                   zip_code=zip, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"summary": discrepancy_summary(db, user["account_id"], zip_code=zip),
            "items": items}
