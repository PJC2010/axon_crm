"""
GET  /api/property-data/audit             — per-field null report + what a sweep would cost
POST /api/property-data/backfill          — run a RentCast gap-fill / verification sweep
GET  /api/property-data/discrepancies     — stored values RentCast disagrees with
GET  /api/property-data/non-residential   — leads that are not homes, with examples
POST /api/property-data/non-residential/archive — archive them

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
    field: Optional[str] = Query(
        None,
        description="Restrict to one property field. `address` returns the "
                    "records RentCast answered about a different property.",
    ),
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

    Entries under the `address` field are a different and more serious finding —
    RentCast resolved the lookup to a different property, so the record was
    rejected rather than written. Read those first.
    """
    from pipeline.backfill import discrepancy_summary, list_discrepancies
    try:
        items = list_discrepancies(db, user["account_id"], field=field,
                                   zip_code=zip, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"summary": discrepancy_summary(db, user["account_id"], zip_code=zip),
            "items": items}


# ── Non-residential leads ────────────────────────────────────────────────────

class NonResidentialArchiveRequest(BaseModel):
    zip: Optional[str] = None
    # Restrict the action to specific reasons. Default: every EXCLUDE-tier
    # reason. Review-tier reasons are rejected — see pipeline/residential.py.
    reasons: Optional[list[str]] = None
    # Count what would be archived without writing. Costs nothing either way;
    # this exists so the UI can confirm a number before acting.
    dry_run: bool = False


@router.get("/property-data/non-residential")
def property_data_non_residential(
    zip: Optional[str] = Query(None, description="Restrict to one ZIP"),
    sample_limit: int = Query(10, ge=0, le=200,
                              description="Example rows to return"),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
    _mod: dict = _prospecting,
):
    """Live leads that do not look like homes, counted by reason, with examples.

    Free: pure SQL over columns already stored, no vendor calls, nothing
    written — same contract as /property-data/audit, safe on a page load.

    Axon targets residential homeowners, but the free HCAD seed takes a whole
    ZIP off the county roll, and the county roll is every *parcel*: shopping
    centres, churches, school-district land and vacant lots included. Reasons
    come in two tiers. `exclude` reasons are structurally impossible for a house
    and are what the archive endpoint acts on; `review` reasons are reported
    only, because a legitimate home can look like that.

    `excludable` is smaller than the sum of the per-reason counts — one bad row
    usually trips several reasons at once.
    """
    from pipeline.property_audit import audit as non_residential_audit
    return non_residential_audit(db, user["account_id"], zip_code=zip,
                                 sample_limit=sample_limit)


@router.post("/property-data/non-residential/archive")
def property_data_non_residential_archive(
    body: NonResidentialArchiveRequest,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
    _mod: dict = _prospecting,
):
    """Archive the leads the audit flags as non-residential.

    Soft-delete via `archived_at`, the same mechanism POST /leads/{id}/archive
    uses, so the rows stay recoverable with /leads/{id}/unarchive and keep their
    notes, history and appointments. `exclusion_reason` records which rule fired.

    Archiving rather than deleting is also the only thing that *works*: the
    shared parcel cache still holds the parcel, and the tenant-materialization
    step skips addresses this account already has — so a deleted row is
    re-created by the next scheduled run, while an archived one is not.

    Owner-only and irreversible in bulk (though reversible per lead), so it is
    not rate-limited like the paid sweep but is deliberately not a GET.
    """
    from pipeline.property_audit import archive as archive_non_residential
    try:
        return archive_non_residential(
            db, current_user["account_id"], zip_code=body.zip,
            reasons=body.reasons, dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
