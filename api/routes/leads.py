"""
GET  /api/leads           — paginated, filtered lead list
GET  /api/leads/{id}      — single lead detail
PATCH /api/leads/{id}/status — update lead status
GET  /api/zips            — distinct ZIP codes in DB
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel, Field

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user
from api.models import (
    Lead, LeadPage, StatusUpdate, LeadContactUpdate,
    ScoreExplanation, ScoreFactor, VerticalFactor,
)
from config import DEFAULT_WEIGHTS, VERTICAL_WEIGHTS, CONTACT_PROVIDER, CONTACT_API_KEY
from pipeline.scoring import explain_score, describe_vertical
from pipeline.contact import PROVIDERS

router = APIRouter()
log = logging.getLogger(__name__)

SORT_MAP = {
    "score":      "lead_score DESC NULLS LAST",
    "sale_date":  "last_sale_date DESC NULLS LAST",
    "address":    "address ASC",
    "grade":      "score_grade ASC",
}


@router.get("/leads", response_model=LeadPage)
def list_leads(
    zip: str | None = Query(None),
    grade: str | None = Query(None),
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("score"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    order = SORT_MAP.get(sort, SORT_MAP["score"])
    conditions, params = _build_filters(user["account_id"], zip=zip, grade=grade, vertical=vertical, status=status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM properties {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT * FROM properties {where} ORDER BY {order} LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    return LeadPage(total=total, page=page, page_size=page_size,
                    results=[Lead(**r) for r in rows])


@router.get("/leads/{lead_id}", response_model=Lead)
def get_lead(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM properties WHERE id = %s AND account_id = %s", (lead_id, user["account_id"]))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
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

    return ScoreExplanation(
        lead_id=lead_id,
        score=breakdown["score"],
        grade=breakdown["grade"],
        vertical=vertical,
        is_default_profile=vdesc["is_default"],
        factors=[ScoreFactor(**f) for f in breakdown["factors"]],
        top_drivers=breakdown["top_drivers"],
        vertical_description=[VerticalFactor(**f) for f in vdesc["factors"]],
        score_updated_at=row.get("score_updated_at"),
        weights_drift=drift,
    )


@router.patch("/leads/{lead_id}/status")
def update_status(lead_id: int, body: StatusUpdate, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    body.validate_status()
    acct = user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT status FROM properties WHERE id = %s AND account_id = %s", (lead_id, acct))
        prev = cur.fetchone()
        old_status = prev[0] if prev else None

        cur.execute(
            "UPDATE properties SET status = %s, stage_moved_at = NOW() WHERE id = %s AND account_id = %s RETURNING *",
            (body.status, lead_id, acct),
        )
        row = dict_fetchone(cur)
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found")

        cur.execute(
            "INSERT INTO stage_transitions (property_id, from_status, to_status, transitioned_by) "
            "VALUES (%s, %s, %s, %s)",
            (lead_id, old_status, body.status, user["id"]),
        )
        db.commit()

    from api.workflow_engine import execute_status_change_rules
    workflow_results = execute_status_change_rules(db, lead_id, old_status, body.status, user["id"], acct)

    # Winning a job makes the surrounding street the cheapest lead source —
    # queue a door-knock task for nearby uncontacted leads.
    if body.status == "won" and old_status != "won":
        from api.neighbors import create_neighbor_task
        try:
            neighbor_result = create_neighbor_task(db, lead_id, acct, user["id"])
            if neighbor_result:
                workflow_results.append(neighbor_result)
        except Exception:
            log.exception("Neighbor task creation failed for lead %d", lead_id)

    # Lead fields plus what automation did (including failures), so the UI can
    # tell the user when a rule's action didn't run.
    return {**Lead(**row).model_dump(), "workflow_actions": workflow_results}


@router.patch("/leads/{lead_id}/contact", response_model=Lead)
def update_contact(lead_id: int, body: LeadContactUpdate, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
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
            "created_at FROM contact_history WHERE property_id = %s "
            "UNION ALL "
            "SELECT id, property_id, 'note' AS type, note AS title, NULL AS detail, "
            "created_at FROM contact_notes WHERE property_id = %s "
            "UNION ALL "
            "SELECT id, property_id, 'task' AS type, title, "
            "CASE WHEN is_complete THEN 'completed' ELSE priority END AS detail, "
            "created_at FROM tasks WHERE property_id = %s "
            "UNION ALL "
            "SELECT id, property_id, 'signal' AS type, "
            "CASE signal_type WHEN 'just_sold' THEN 'Property just sold' "
            "                 WHEN 'new_permit' THEN 'New permit activity' "
            "                 ELSE signal_type END AS title, "
            "details->>'summary' AS detail, "
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

def _build_filters(account_id: int, **kwargs) -> tuple[list[str], list]:
    conditions, params = ["account_id = %s"], [account_id]
    mapping = {
        "zip":      "zip = %s",
        "grade":    "score_grade = %s",
        "vertical": "vertical = %s",
        "status":   "status = %s",
    }
    for key, sql in mapping.items():
        val = kwargs.get(key)
        if val:
            conditions.append(sql)
            params.append(val)
    # Always exclude archived leads unless explicitly included
    if not kwargs.get("include_archived"):
        conditions.append("archived_at IS NULL")
    return conditions, params
