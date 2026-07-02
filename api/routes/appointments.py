"""
GET    /api/appointments         — list (filters: status, property_id, assigned_to,
                                   from/to starts_at range, page) + roll-ups
POST   /api/appointments         — create
GET    /api/appointments/{id}    — single
PATCH  /api/appointments/{id}    — update
DELETE /api/appointments/{id}    — delete (owner only)

Appointments are scheduled visits/bookings (Phase 5 associated object,
reintroducing the 031 schema). Lifecycle events fire appointment_event rules
and log to the lead's activity feed; starts_at is a date_offset trigger source
(e.g. "1 day before appointment → reminder task").
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner
from api.models import Appointment, AppointmentCreate, AppointmentUpdate, APPOINTMENT_STATUSES

log = logging.getLogger(__name__)

router = APIRouter()

_FIELDS = ("property_id", "assigned_to", "title", "location", "starts_at",
           "ends_at", "status", "notes")


def _get_appointment_or_404(db: PGConn, appointment_id: int, account_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM appointments WHERE id = %s AND account_id = %s",
                    (appointment_id, account_id))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return row


def _fire_appointment_event(db: PGConn, appointment: dict, event: str, user_id: int) -> None:
    """Run appointment_event workflow rules; never let automation break the request."""
    from api.workflow_engine import execute_object_event_rules
    try:
        execute_object_event_rules(
            db, account_id=appointment["account_id"], lead_id=appointment["property_id"],
            object_type="appointment", event=event, user_id=user_id,
        )
    except Exception:
        log.exception("appointment_event rules failed for appointment %d (%s)", appointment["id"], event)


def _log_appointment_history(db: PGConn, appointment: dict, action: str, user_id: int) -> None:
    if not appointment.get("property_id"):
        return
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, created_by) "
            "VALUES (%s, %s, %s, %s)",
            (appointment["property_id"], action, appointment.get("status"), user_id),
        )


@router.get("/appointments", response_model=dict)
def list_appointments(
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    assigned_to: Optional[int] = Query(None),
    starts_after: Optional[datetime] = Query(None, alias="from"),
    starts_before: Optional[datetime] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    conditions, params = ["account_id = %s"], [user["account_id"]]
    if status:
        conditions.append("status = %s"); params.append(status)
    if property_id is not None:
        conditions.append("property_id = %s"); params.append(property_id)
    if assigned_to is not None:
        conditions.append("assigned_to = %s"); params.append(assigned_to)
    if starts_after is not None:
        conditions.append("starts_at >= %s"); params.append(starts_after)
    if starts_before is not None:
        conditions.append("starts_at <= %s"); params.append(starts_before)
    where = "WHERE " + " AND ".join(conditions)
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM appointments {where}", params)
        total = cur.fetchone()[0]
        rollup_where = "WHERE account_id = %s" + (" AND property_id = %s" if property_id is not None else "")
        rollup_params = [user["account_id"]] + ([property_id] if property_id is not None else [])
        cur.execute(
            f"SELECT MIN(starts_at) FILTER (WHERE status = 'scheduled' AND starts_at >= NOW()), "
            f"COUNT(*) FILTER (WHERE status = 'scheduled' AND starts_at >= NOW()) "
            f"FROM appointments {rollup_where}",
            rollup_params,
        )
        next_at, upcoming_count = cur.fetchone()
        cur.execute(
            f"SELECT * FROM appointments {where} ORDER BY starts_at ASC, id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    return {
        "items": [Appointment(**r).model_dump() for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "next_at": next_at.isoformat() if next_at else None,
        "upcoming_count": upcoming_count,
    }


@router.post("/appointments", response_model=Appointment, status_code=201)
def create_appointment(body: AppointmentCreate, current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    if body.status not in APPOINTMENT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO appointments (property_id, assigned_to, title, location, starts_at, ends_at, "
            "status, notes, created_by, account_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (body.property_id, body.assigned_to, body.title, body.location, body.starts_at,
             body.ends_at, body.status, body.notes, current_user["id"], current_user["account_id"]),
        )
        row = dict_fetchone(cur)
    _log_appointment_history(db, row, f"Appointment scheduled — {row['title']}", current_user["id"])
    db.commit()
    _fire_appointment_event(db, row, "created", current_user["id"])
    return Appointment(**row)


@router.get("/appointments/{appointment_id}", response_model=Appointment)
def get_appointment(appointment_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    return Appointment(**_get_appointment_or_404(db, appointment_id, user["account_id"]))


@router.patch("/appointments/{appointment_id}", response_model=Appointment)
def update_appointment(appointment_id: int, body: AppointmentUpdate, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    existing = _get_appointment_or_404(db, appointment_id, user["account_id"])
    if body.status is not None and body.status not in APPOINTMENT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    sets, params = ["updated_at = NOW()"], []
    for field in _FIELDS:
        val = getattr(body, field)
        if val is not None:
            sets.append(f"{field} = %s"); params.append(val)
    if len(sets) == 1:
        raise HTTPException(status_code=400, detail="Nothing to update")

    params.extend([appointment_id, user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE appointments SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
            params,
        )
        row = dict_fetchone(cur)
    status_changed = body.status is not None and body.status != existing["status"]
    if status_changed:
        _log_appointment_history(db, row, f"Appointment {body.status.replace('_', ' ')} — {row['title']}", user["id"])
    db.commit()
    if status_changed:
        _fire_appointment_event(db, row, body.status, user["id"])
    return Appointment(**row)


@router.delete("/appointments/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM appointments WHERE id = %s AND account_id = %s RETURNING id",
                    (appointment_id, current_user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Appointment not found")
