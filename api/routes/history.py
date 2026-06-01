"""
GET  /api/leads/{id}/history  — contact history for a lead
POST /api/leads/{id}/history  — log a contact action
"""
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user
from api.models import HistoryEntry, HistoryCreate

router = APIRouter()


@router.get("/leads/{lead_id}/history", response_model=list[HistoryEntry])
def list_history(lead_id: int, db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    _assert_lead(db, lead_id)
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM contact_history WHERE property_id = %s ORDER BY created_at DESC",
            (lead_id,),
        )
        return [HistoryEntry(**r) for r in dict_fetchall(cur)]


@router.post("/leads/{lead_id}/history", response_model=HistoryEntry, status_code=201)
def add_history(lead_id: int, body: HistoryCreate, db: PGConn = Depends(get_db), current_user: dict = Depends(get_current_user)):
    _assert_lead(db, lead_id)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, created_by) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (lead_id, body.action, body.outcome, current_user["id"]),
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        db.commit()
    return HistoryEntry(**row)


def _assert_lead(db, lead_id: int):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM properties WHERE id = %s", (lead_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lead not found")
