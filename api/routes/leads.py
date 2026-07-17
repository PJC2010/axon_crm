"""
GET  /api/leads           — paginated, filtered lead list
GET  /api/leads/{id}      — single lead detail
PATCH /api/leads/{id}/status — update lead status
GET  /api/zips            — distinct ZIP codes in DB
"""
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel, Field

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user
from api.lead_events_emit import emit_surfaced, emit_viewed
from api.models import (
    Lead, LeadPage, StatusUpdate, LeadContactUpdate,
    CustomerSearchResult, ScoreExplanation, ScoreFactor, VerticalFactor, MLFactor,
)
from config import (
    DEFAULT_WEIGHTS, VERTICAL_WEIGHTS, CONTACT_PROVIDER, CONTACT_API_KEY, SCORER_MODE,
)
from pipeline.scoring import explain_score, describe_vertical
from pipeline.contact import PROVIDERS

router = APIRouter()
log = logging.getLogger(__name__)

SORT_MAP = {
    "score":               "lead_score DESC NULLS LAST",
    "sale_date":           "last_sale_date DESC NULLS LAST",
    "address":             "address ASC",
    "grade":               "score_grade ASC",
    "value":               "estimated_value DESC NULLS LAST",
    "neighborhood_pctile": "neighborhood_value_pctile DESC NULLS LAST",
    # Geo blend — falls back to the property score for leads not yet geo-scored.
    "final_score":         "COALESCE(lgs.final_score, p.lead_score) DESC NULLS LAST",
}


@router.get("/leads", response_model=LeadPage)
def list_leads(
    zip: str | None = Query(None),
    grade: str | None = Query(None),
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    min_value: int | None = Query(None, ge=0),
    max_value: int | None = Query(None, ge=0),
    neighborhood: str | None = Query(None, description="geohash-6 cell"),
    min_neighborhood_pctile: float | None = Query(None, ge=0, le=1),
    sort: str = Query("score"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    order = SORT_MAP.get(sort, SORT_MAP["score"])
    # Prefix filters with the properties alias — the query LEFT JOINs
    # lead_geo_scores, which also has an account_id, so bare names are ambiguous.
    conditions, params = _build_filters(
        user["account_id"], prefix="p.", zip=zip, grade=grade, vertical=vertical, status=status,
        min_value=min_value, max_value=max_value, neighborhood=neighborhood,
        min_neighborhood_pctile=min_neighborhood_pctile,
    )
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM properties p {where}", params)
        total = cur.fetchone()[0]

        # LEFT JOIN the geo scores so the list carries final_score / geo components
        # and can sort by the blend. Leads not yet geo-scored simply have NULLs.
        cur.execute(
            f"SELECT p.*, lgs.geo_score, lgs.final_score, "
            f"       lgs.components AS geo_components, lgs.nearest_customer_m, "
            f"       lgs.customers_within_1600m "
            f"FROM properties p "
            f"LEFT JOIN lead_geo_scores lgs ON lgs.property_id = p.id "
            f"{where} ORDER BY {order} LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    # Feedback loop (Phase 2): a listed lead has been surfaced to the contractor.
    # First-only + best-effort, so a page render never appends per-row noise and
    # never breaks the read.
    emit_surfaced(db, [r["id"] for r in rows], user["account_id"], actor_user_id=user["id"])

    return LeadPage(total=total, page=page, page_size=page_size,
                    results=[Lead(**r) for r in rows])


# NOTE: literal-path routes (/leads/search, /leads/by-number/...) must be declared
# before /leads/{lead_id}, or the int-typed param route would shadow them.

@router.get("/leads/search", response_model=list[CustomerSearchResult])
def search_leads(
    q: str = Query(..., min_length=1, description="Free text: account number, name, address, phone, or email"),
    limit: int = Query(20, ge=1, le=50),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Universal customer lookup. Matches across account_number, contact/owner
    name, address, email, and phone (digits only, so formatting doesn't matter).
    Exact and prefix account-number hits rank first, then everything else.
    Always scoped to the caller's account and excludes archived leads. Uses the
    trigram (pg_trgm) indexes from migration 038 for fast ILIKE substring search."""
    term = q.strip()
    if not term:
        return []
    digits = re.sub(r"[^0-9]", "", term)
    params = {
        "account_id": user["account_id"],
        "term": term,
        "prefix": f"{term}%",
        "like": f"%{term}%",
        "digits": digits,
        "digits_like": f"%{digits}%",
        "limit": limit,
    }
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, account_number, contact_name, owner_name, address, city, zip,
                   contact_phone, status, score_grade,
                   CASE
                       WHEN UPPER(account_number) = UPPER(%(term)s)     THEN 0
                       WHEN account_number ILIKE %(prefix)s             THEN 1
                       ELSE 2
                   END AS match_rank
            FROM properties
            WHERE account_id = %(account_id)s AND archived_at IS NULL
              AND (
                    account_number ILIKE %(like)s
                 OR contact_name   ILIKE %(like)s
                 OR owner_name     ILIKE %(like)s
                 OR address        ILIKE %(like)s
                 OR contact_email  ILIKE %(like)s
                 OR (%(digits)s <> '' AND
                     regexp_replace(COALESCE(contact_phone, ''), '[^0-9]', '', 'g') ILIKE %(digits_like)s)
              )
            ORDER BY match_rank, contact_name NULLS LAST, account_number
            LIMIT %(limit)s
            """,
            params,
        )
        rows = dict_fetchall(cur)
    return [CustomerSearchResult(**r) for r in rows]


@router.get("/leads/by-number/{account_number}", response_model=Lead)
def get_lead_by_number(account_number: str, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Resolve a customer by their durable account number — the stable handle
    that deep links, quotes, and QR codes reference instead of the internal id."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM properties WHERE account_number = %s AND account_id = %s",
            (account_number, user["account_id"]),
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Lead(**row)


@router.get("/leads/{lead_id}", response_model=Lead)
def get_lead(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM properties WHERE id = %s AND account_id = %s", (lead_id, user["account_id"]))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    # Feedback loop (Phase 2): opening a lead's detail is a 'viewed' signal.
    # First-only + best-effort.
    emit_viewed(db, lead_id, user["account_id"], actor_user_id=user["id"])
    return Lead(**row)


@router.get("/leads/{lead_id}/score-explanation", response_model=ScoreExplanation)
def get_score_explanation(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Explain why a lead scored the way it did: per-factor contributions plus a
    description of the weighting profile used for the lead's vertical."""
    with db.cursor() as cur:
        cur.execute("SELECT * FROM properties WHERE id = %s AND account_id = %s", (lead_id, user["account_id"]))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    vertical = row.get("vertical")
    weights = VERTICAL_WEIGHTS.get(vertical, DEFAULT_WEIGHTS) if vertical else DEFAULT_WEIGHTS
    breakdown = explain_score(row, weights)
    vdesc = describe_vertical(vertical)

    # The stored lead_score was computed when the lead was last scored; current
    # weights may differ. Report the recomputed total (so factor contributions
    # reconcile) and flag any drift from the stored value.
    stored = row.get("lead_score")
    drift = stored is not None and abs(stored - breakdown["score"]) > 0.5

    # Overlay the learned model's explanation when one is active. Kept best-effort:
    # a missing/unbuilt model just leaves the deterministic breakdown untouched.
    ml: dict = {}
    if SCORER_MODE in ("shadow", "learned"):
        try:
            from pipeline.ml import predict
            loaded = predict.load_model(db, user["account_id"])
            if loaded:
                version_id, model = loaded
                ml = predict.explain(model, version_id, row)
        except Exception:
            log.exception("Learned score explanation failed for lead %s", lead_id)

    return ScoreExplanation(
        lead_id=lead_id,
        score=breakdown["score"],
        grade=breakdown["grade"],
        vertical=vertical,
        is_default_profile=vdesc["is_default"],
        factors=[ScoreFactor(**f) for f in breakdown["factors"]],
        top_drivers=breakdown["top_drivers"],
        summary=breakdown["summary"],
        vertical_description=[VerticalFactor(**f) for f in vdesc["factors"]],
        score_updated_at=row.get("score_updated_at"),
        weights_drift=drift,
        scorer_mode=SCORER_MODE,
        ml_conversion_prob=ml.get("ml_conversion_prob"),
        ml_grade=ml.get("ml_grade"),
        ml_model_version=ml.get("ml_model_version"),
        ml_factors=[MLFactor(**f) for f in ml.get("ml_factors", [])],
        ml_top_drivers=ml.get("ml_top_drivers", []),
    )


@router.patch("/leads/{lead_id}/status")
def update_status(lead_id: int, body: StatusUpdate, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    body.validate_status()
    # Shared with quote-event automations (api/lead_logic.py): stage_transitions
    # audit, status_change rules, neighbor door-knock task on a win.
    from api.lead_logic import apply_status_change
    row, workflow_results = apply_status_change(db, lead_id, body.status, user["id"], user["account_id"])
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Lead fields plus what automation did (including failures), so the UI can
    # tell the user when a rule's action didn't run.
    return {**Lead(**row).model_dump(), "workflow_actions": workflow_results}


@router.patch("/leads/{lead_id}/contact", response_model=Lead)
def update_contact(lead_id: int, body: LeadContactUpdate, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    # exclude_unset so callers can explicitly clear a field (e.g. assigned_to=null
    # to unassign a rep) — only fields present in the request body are touched.
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")
    sets = [f"{k} = %s" for k in fields]
    params = list(fields.values()) + [lead_id, user["account_id"]]
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
            params,
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Lead(**row)


@router.post("/leads/{lead_id}/enrich", response_model=Lead)
def enrich_lead(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """On-demand skip-trace for a single lead.

    Reuses the same provider lookup as the batch pipeline (pipeline.contact).
    Only fills contact fields that are currently empty — never overwrites
    values a user has already entered. Returns 409 when no provider is
    configured so the UI can surface a clear, actionable message.
    """
    lookup = PROVIDERS.get(CONTACT_PROVIDER)
    if not CONTACT_PROVIDER or not CONTACT_API_KEY or lookup is None:
        raise HTTPException(
            status_code=409,
            detail="Contact enrichment isn't configured — set CONTACT_PROVIDER and CONTACT_API_KEY.",
        )

    acct = user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT * FROM properties WHERE id = %s AND account_id = %s", (lead_id, acct))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not row.get("owner_name"):
        raise HTTPException(
            status_code=422,
            detail="This lead has no owner name to skip-trace against.",
        )

    data = lookup(row) or {}
    # Only fill fields that are currently empty on the lead.
    updates = {
        field: data[field]
        for field in ("contact_name", "contact_phone", "contact_email")
        if data.get(field) and not row.get(field)
    }
    if not updates:
        raise HTTPException(status_code=404, detail="No new contact details found.")

    flags = dict(row.get("enrichment_flags") or {})
    flags["contact"] = CONTACT_PROVIDER

    sets = [f"{k} = %s" for k in updates]
    params = list(updates.values()) + [json.dumps(flags), lead_id, acct]
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET {', '.join(sets)}, enrichment_flags = %s "
            "WHERE id = %s AND account_id = %s RETURNING *",
            params,
        )
        updated = dict_fetchone(cur)
        db.commit()
    return Lead(**updated)


@router.get("/leads/{lead_id}/neighbors")
def get_neighbors(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Uncontacted leads in the same geohash cell — door-knock targets while
    a crew is already on the street."""
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM properties WHERE id = %s AND account_id = %s", (lead_id, user["account_id"]))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lead not found")

    from api.neighbors import find_neighbors
    neighbors = find_neighbors(db, lead_id, user["account_id"])
    return {"count": len(neighbors), "neighbors": neighbors}


@router.get("/leads/{lead_id}/timeline")
def get_timeline(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM properties WHERE id = %s AND account_id = %s", (lead_id, user["account_id"]))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lead not found")
        cur.execute(
            "SELECT id, property_id, 'history' AS type, action AS title, outcome AS detail, "
            "channel, direction, body, "
            "created_at FROM contact_history WHERE property_id = %s "
            "UNION ALL "
            "SELECT id, property_id, 'note' AS type, note AS title, NULL AS detail, "
            "NULL AS channel, NULL AS direction, NULL AS body, "
            "created_at FROM contact_notes WHERE property_id = %s "
            "UNION ALL "
            "SELECT id, property_id, 'task' AS type, title, "
            "CASE WHEN is_complete THEN 'completed' ELSE priority END AS detail, "
            "NULL AS channel, NULL AS direction, NULL AS body, "
            "created_at FROM tasks WHERE property_id = %s "
            "UNION ALL "
            "SELECT id, property_id, 'signal' AS type, "
            "CASE signal_type WHEN 'just_sold' THEN 'Property just sold' "
            "                 WHEN 'new_permit' THEN 'New permit activity' "
            "                 ELSE signal_type END AS title, "
            "details->>'summary' AS detail, "
            "NULL AS channel, NULL AS direction, NULL AS body, "
            "detected_at AS created_at FROM signal_events WHERE property_id = %s "
            "ORDER BY created_at DESC",
            (lead_id, lead_id, lead_id, lead_id),
        )
        rows = dict_fetchall(cur)
    return rows


@router.get("/zips")
def list_zips(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT zip FROM properties WHERE zip IS NOT NULL AND account_id = %s ORDER BY zip",
            (user["account_id"],),
        )
        return [r[0] for r in cur.fetchall()]


@router.get("/regions")
def list_regions(
    q: str | None = Query(None, description="Case-insensitive substring filter on region name"),
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    """Named HCAD neighborhoods a user can pick as a service area, read straight
    from the free local HCAD data (zero paid API calls). Lets users target an area
    by name instead of guessing a ZIP. Returns [] when the HCAD data is absent so
    the frontend falls back to manual ZIP entry."""
    from pipeline import hcad_store
    regions = hcad_store.list_regions()   # DuckDB, or Postgres mirror, or []
    if q:
        ql = q.lower()
        regions = [r for r in regions if ql in (r["name"] or "").lower()]
    return regions[:limit]


@router.get("/neighborhoods")
def list_neighborhoods(
    zip: str | None = Query(None),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Geohash-6 neighborhoods (the same ~block cells used for value benchmarking),
    with lead count and median value, so the UI can offer a 'pick a block' filter.
    Only cells with enough leads to be meaningful are returned; optionally narrowed
    to a selected ZIP."""
    from config import NEIGHBORHOOD_MIN_MEMBERS
    params: list = [user["account_id"]]
    zip_clause = ""
    if zip:
        zip_clause = "AND zip = %s"
        params.append(zip)
    params.append(NEIGHBORHOOD_MIN_MEMBERS)
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT LEFT(geohash, 6) AS cell,
                   COUNT(*) AS leads,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY estimated_value) AS median_value,
                   mode() WITHIN GROUP (ORDER BY hcad_neighborhood_name)
                     FILTER (WHERE hcad_neighborhood_name IS NOT NULL) AS name
            FROM properties
            WHERE account_id = %s AND geohash IS NOT NULL AND archived_at IS NULL
              {zip_clause}
            GROUP BY cell
            HAVING COUNT(*) >= %s
            ORDER BY median_value DESC NULLS LAST
            """,
            params,
        )
        return [
            {"cell": cell, "name": name, "leads": leads,
             "median_value": int(median_value) if median_value is not None else None}
            for cell, leads, median_value, name in cur.fetchall()
        ]


@router.post("/leads/{lead_id}/archive", response_model=Lead)
def archive_lead(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Soft-delete: mark lead as archived"""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE properties SET archived_at = NOW() WHERE id = %s AND account_id = %s RETURNING *",
            (lead_id, user["account_id"])
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(404, "Lead not found")
    db.commit()
    return Lead(**row)


@router.post("/leads/{lead_id}/unarchive", response_model=Lead)
def unarchive_lead(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Restore archived lead"""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE properties SET archived_at = NULL WHERE id = %s AND account_id = %s RETURNING *",
            (lead_id, user["account_id"])
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(404, "Lead not found")
    db.commit()
    return Lead(**row)


class BulkIds(BaseModel):
    """Validated ID list for bulk operations — ints only, bounded size."""
    ids: list[int] = Field(..., min_length=1, max_length=500)


@router.post("/leads/archive-bulk")
def archive_bulk(body: BulkIds, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Bulk archive by IDs: {"ids": [1, 2, 3]}"""
    ids = body.ids
    placeholders = ",".join(["%s"] * len(ids))
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET archived_at = NOW() WHERE id IN ({placeholders}) AND account_id = %s RETURNING id",
            ids + [user["account_id"]]
        )
        updated = cur.fetchall()
    db.commit()
    return {"archived_count": len(updated), "ids": [r[0] for r in updated]}


@router.post("/leads/unarchive-bulk")
def unarchive_bulk(body: BulkIds, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Bulk unarchive by IDs: {"ids": [1, 2, 3]}"""
    ids = body.ids
    placeholders = ",".join(["%s"] * len(ids))
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET archived_at = NULL WHERE id IN ({placeholders}) AND account_id = %s RETURNING id",
            ids + [user["account_id"]]
        )
        updated = cur.fetchall()
    db.commit()
    return {"unarchived_count": len(updated), "ids": [r[0] for r in updated]}


@router.post("/leads/archive-by-filter")
def archive_by_filter(
    zip: str | None = Query(None),
    grade: str | None = Query(None),
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Archive all leads matching filters"""
    conditions, params = _build_filters(user["account_id"], zip=zip, grade=grade, vertical=vertical, status=status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET archived_at = NOW() {where} RETURNING id",
            params
        )
        updated = cur.fetchall()
    db.commit()
    return {"archived_count": len(updated), "ids": [r[0] for r in updated]}


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_filters(account_id: int, prefix: str = "", **kwargs) -> tuple[list[str], list]:
    # `prefix` (e.g. "p.") qualifies column names for queries that JOIN another
    # table; it defaults to "" so single-table callers are unchanged.
    p = prefix
    conditions, params = [f"{p}account_id = %s"], [account_id]
    # Each entry maps a kwarg to a single-placeholder SQL fragment. Range and
    # geohash filters fit the same shape (one %s each) as the equality filters.
    mapping = {
        "zip":                     f"{p}zip = %s",
        "grade":                   f"{p}score_grade = %s",
        "vertical":                f"{p}vertical = %s",
        "status":                  f"{p}status = %s",
        "min_value":               f"{p}estimated_value >= %s",
        "max_value":               f"{p}estimated_value <= %s",
        "neighborhood":            f"LEFT({p}geohash, 6) = %s",
        "min_neighborhood_pctile": f"{p}neighborhood_value_pctile >= %s",
        "min_lat":                 f"{p}latitude >= %s",
        "max_lat":                 f"{p}latitude <= %s",
        "min_lng":                 f"{p}longitude >= %s",
        "max_lng":                 f"{p}longitude <= %s",
    }
    for key, sql in mapping.items():
        val = kwargs.get(key)
        if val:
            conditions.append(sql)
            params.append(val)
    # Always exclude archived leads unless explicitly included
    if not kwargs.get("include_archived"):
        conditions.append(f"{p}archived_at IS NULL")
    return conditions, params
