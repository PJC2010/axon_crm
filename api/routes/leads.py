"""
GET  /api/leads           — paginated, filtered lead list
GET  /api/leads/{id}      — single lead detail
PATCH /api/leads/{id}/status — update lead status
GET  /api/zips            — distinct ZIP codes in DB
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user
from api.models import (
    Lead, LeadPage, StatusUpdate, LeadContactUpdate,
    ScoreExplanation, ScoreFactor, VerticalFactor,
)
from config import DEFAULT_WEIGHTS, VERTICAL_WEIGHTS
from pipeline.scoring import explain_score, describe_vertical

router = APIRouter()

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
    _: dict = Depends(get_current_user),
):
    order = SORT_MAP.get(sort, SORT_MAP["score"])
    conditions, params = _build_filters(zip=zip, grade=grade, vertical=vertical, status=status)
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
def get_lead(lead_id: int, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM properties WHERE id = %s", (lead_id,))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Lead(**row)


@router.get("/leads/{lead_id}/score-explanation", response_model=ScoreExplanation)
def get_score_explanation(lead_id: int, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    """Explain why a lead scored the way it did: per-factor contributions plus a
    description of the weighting profile used for the lead's vertical."""
    with db.cursor() as cur:
        cur.execute("SELECT * FROM properties WHERE id = %s", (lead_id,))
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


@router.patch("/leads/{lead_id}/status", response_model=Lead)
def update_status(lead_id: int, body: StatusUpdate, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    body.validate_status()
    with db.cursor() as cur:
        cur.execute("SELECT status FROM properties WHERE id = %s", (lead_id,))
        prev = cur.fetchone()
        old_status = prev[0] if prev else None

        cur.execute(
            "UPDATE properties SET status = %s, stage_moved_at = NOW() WHERE id = %s RETURNING *",
            (body.status, lead_id),
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
    workflow_results = execute_status_change_rules(db, lead_id, old_status, body.status, user["id"])

    lead = Lead(**row)
    return lead


@router.patch("/leads/{lead_id}/contact", response_model=Lead)
def update_contact(lead_id: int, body: LeadContactUpdate, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")
    sets = [f"{k} = %s" for k in fields]
    params = list(fields.values()) + [lead_id]
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET {', '.join(sets)} WHERE id = %s RETURNING *",
            params,
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Lead(**row)


@router.get("/leads/{lead_id}/timeline")
def get_timeline(lead_id: int, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    with db.cursor() as cur:
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
            "ORDER BY created_at DESC",
            (lead_id, lead_id, lead_id),
        )
        rows = dict_fetchall(cur)
    return rows


@router.get("/zips")
def list_zips(db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT zip FROM properties WHERE zip IS NOT NULL ORDER BY zip")
        return [r[0] for r in cur.fetchall()]


@router.post("/leads/{lead_id}/archive", response_model=Lead)
def archive_lead(lead_id: int, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    """Soft-delete: mark lead as archived"""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE properties SET archived_at = NOW() WHERE id = %s RETURNING *",
            (lead_id,)
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(404, "Lead not found")
    db.commit()
    return Lead(**row)


@router.post("/leads/{lead_id}/unarchive", response_model=Lead)
def unarchive_lead(lead_id: int, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    """Restore archived lead"""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE properties SET archived_at = NULL WHERE id = %s RETURNING *",
            (lead_id,)
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(404, "Lead not found")
    db.commit()
    return Lead(**row)


@router.post("/leads/archive-bulk")
def archive_bulk(body: dict, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    """Bulk archive by IDs: {"ids": [1, 2, 3]}"""
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(400, "No lead IDs provided")

    placeholders = ",".join(["%s"] * len(ids))
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET archived_at = NOW() WHERE id IN ({placeholders}) RETURNING id",
            ids
        )
        updated = cur.fetchall()
    db.commit()
    return {"archived_count": len(updated), "ids": [r[0] for r in updated]}


@router.post("/leads/unarchive-bulk")
def unarchive_bulk(body: dict, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    """Bulk unarchive by IDs: {"ids": [1, 2, 3]}"""
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(400, "No lead IDs provided")

    placeholders = ",".join(["%s"] * len(ids))
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET archived_at = NULL WHERE id IN ({placeholders}) RETURNING id",
            ids
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
    _: dict = Depends(get_current_user),
):
    """Archive all leads matching filters"""
    conditions, params = _build_filters(zip=zip, grade=grade, vertical=vertical, status=status)
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

def _build_filters(**kwargs) -> tuple[list[str], list]:
    conditions, params = [], []
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
