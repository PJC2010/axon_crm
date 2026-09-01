"""Saved segments — named, shareable lead-list filter sets.

GET    /api/segments        — list this account's segments
POST   /api/segments        — save a segment (any authenticated user)
PATCH  /api/segments/{id}   — rename / re-filter
DELETE /api/segments/{id}   — delete (creator or owner/admin)

`filters` stores the same shape the GET /api/leads querystring accepts (the
frontend LeadFilters type). Keys are validated against ALLOWED_FILTER_KEYS —
kept in lockstep with _build_filters in api/routes/leads.py — so a stored
segment can always be replayed against the lead list.
"""
import json

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user
from api.models import Segment, SegmentCreate, SegmentUpdate

router = APIRouter()

# Mirrors the filter mapping in api/routes/leads.py:_build_filters plus `sort`.
# page/page_size are ephemeral view state and are stripped rather than rejected.
ALLOWED_FILTER_KEYS = frozenset({
    "zip", "grade", "vertical", "status", "min_value", "max_value",
    "neighborhood", "min_neighborhood_pctile", "sort",
})
_STRIPPED_KEYS = ("page", "page_size", "show_all")  # ephemeral view state, never stored


def _clean_filters(filters: dict) -> dict:
    cleaned = {k: v for k, v in filters.items() if k not in _STRIPPED_KEYS and v not in (None, "")}
    unknown = set(cleaned) - ALLOWED_FILTER_KEYS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown filter keys: {sorted(unknown)}")
    return cleaned


def _row_to_segment(row: dict) -> dict:
    if isinstance(row.get("filters"), str):
        row["filters"] = json.loads(row["filters"])
    return row


@router.get("/segments", response_model=list[Segment])
def list_segments(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM segments WHERE account_id = %s ORDER BY name",
            (user["account_id"],),
        )
        return [_row_to_segment(r) for r in dict_fetchall(cur)]


@router.post("/segments", status_code=201, response_model=Segment)
def create_segment(body: SegmentCreate, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Segment name is required")
    filters = _clean_filters(body.filters)
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO segments (account_id, name, filters, created_by) "
                "VALUES (%s, %s, %s, %s) RETURNING *",
                (user["account_id"], name, json.dumps(filters), user["id"]),
            )
            row = dict_fetchone(cur)
            db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A segment named '{name}' already exists")
    return _row_to_segment(row)


@router.patch("/segments/{segment_id}", response_model=Segment)
def update_segment(segment_id: int, body: SegmentUpdate, db: PGConn = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    sets, params = [], []
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Segment name is required")
        sets.append("name = %s"); params.append(name)
    if body.filters is not None:
        sets.append("filters = %s"); params.append(json.dumps(_clean_filters(body.filters)))
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.extend([segment_id, user["account_id"]])
    try:
        with db.cursor() as cur:
            cur.execute(
                f"UPDATE segments SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
                params,
            )
            row = dict_fetchone(cur)
            db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409, detail="A segment with that name already exists")
    if not row:
        raise HTTPException(status_code=404, detail="Segment not found")
    return _row_to_segment(row)


@router.delete("/segments/{segment_id}", status_code=204)
def delete_segment(segment_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT created_by FROM segments WHERE id = %s AND account_id = %s",
            (segment_id, user["account_id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Segment not found")
    if row[0] != user["id"] and user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the segment's creator or an owner can delete it")
    with db.cursor() as cur:
        cur.execute("DELETE FROM segments WHERE id = %s AND account_id = %s", (segment_id, user["account_id"]))
        db.commit()
