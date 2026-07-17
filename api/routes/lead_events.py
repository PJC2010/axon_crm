"""
POST /api/leads/{id}/events — append an outcome event to a lead's log
GET  /api/leads/{id}/events — list a lead's outcome events (oldest first)

The append-only lead_events log is the scoring feedback loop's raw material:
pipeline actions (surfaced/viewed/contacted/quote_sent/won/…) become training
labels for the scoring model. Rows are never updated or deleted; occurred_at
and the acting user are set server-side so the log stays trustworthy.
"""
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user
from api.models import LEAD_EVENT_TYPES, LeadEvent, LeadEventCreate

router = APIRouter()


@router.get("/leads/{lead_id}/events", response_model=list[LeadEvent])
def list_lead_events(lead_id: int, db: PGConn = Depends(get_db),
                     user: dict = Depends(get_current_user)):
    _assert_lead(db, lead_id, user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM lead_events WHERE property_id = %s AND account_id = %s "
            "ORDER BY occurred_at ASC, id ASC",
            (lead_id, user["account_id"]),
        )
        return [LeadEvent(**r) for r in dict_fetchall(cur)]


@router.post("/leads/{lead_id}/events", response_model=LeadEvent, status_code=201)
def add_lead_event(lead_id: int, body: LeadEventCreate, db: PGConn = Depends(get_db),
                   current_user: dict = Depends(get_current_user)):
    if body.event_type not in LEAD_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event_type {body.event_type!r}; expected one of {LEAD_EVENT_TYPES}",
        )
    _assert_lead(db, lead_id, current_user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO lead_events "
            "(property_id, account_id, event_type, channel, actor_user_id, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (
                lead_id, current_user["account_id"], body.event_type, body.channel,
                current_user["id"],
                psycopg2.extras.Json(body.metadata) if body.metadata is not None else None,
            ),
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        db.commit()
    return LeadEvent(**row)


def _assert_lead(db, lead_id: int, account_id: int):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM properties WHERE id = %s AND account_id = %s",
                    (lead_id, account_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lead not found")
