"""
GET  /api/leads/{id}/notes  — list notes for a lead
POST /api/leads/{id}/notes  — add a note
"""
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user
from api.models import Note, NoteCreate

router = APIRouter()


@router.get("/leads/{lead_id}/notes", response_model=list[Note])
def list_notes(lead_id: int, db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    _assert_lead(db, lead_id, user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM contact_notes WHERE property_id = %s ORDER BY created_at DESC",
            (lead_id,),
        )
        return [Note(**r) for r in dict_fetchall(cur)]


@router.post("/leads/{lead_id}/notes", response_model=Note, status_code=201)
def add_note(lead_id: int, body: NoteCreate, db: PGConn = Depends(get_db), current_user: dict = Depends(get_current_user)):
    _assert_lead(db, lead_id, current_user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_notes (property_id, note, created_by) VALUES (%s, %s, %s) "
            "RETURNING *",
            (lead_id, body.note, current_user["id"]),
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        db.commit()
    return Note(**row)


def _assert_lead(db, lead_id: int, account_id: int):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM properties WHERE id = %s AND account_id = %s", (lead_id, account_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lead not found")
