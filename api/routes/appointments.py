"""
GET    /api/appointments              — list (filters: start, end, property_id, assigned_to, status)
POST   /api/appointments              — create
GET    /api/appointments/{id}         — single
PATCH  /api/appointments/{id}         — update fields / status
DELETE /api/appointments/{id}         — delete
POST   /api/appointments/{id}/send    — email/SMS the customer a calendar invite
GET    /api/leads/{lead_id}/appointments — appointments for a specific lead

Appointments are scheduled visits/meetings (distinct from tasks, which are
reminders). They carry a start/end time, location, and lifecycle status, and can
send the customer an .ics calendar invite (reusing api/notifications.py).
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user
from api.models import (
    Appointment, AppointmentCreate, AppointmentUpdate,
    SendAppointmentRequest, APPOINTMENT_STATUSES,
)

log = logging.getLogger(__name__)
router = APIRouter()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/appointments", response_model=list[Appointment])
def list_appointments(
    start: Optional[datetime] = Query(None, description="inclusive lower bound on starts_at"),
    end: Optional[datetime] = Query(None, description="exclusive upper bound on starts_at"),
    property_id: Optional[int] = Query(None),
    assigned_to: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    conditions, params = ["account_id = %s"], [user["account_id"]]
    if start is not None:
        conditions.append("starts_at >= %s"); params.append(start)
    if end is not None:
        conditions.append("starts_at < %s"); params.append(end)
    if property_id is not None:
        conditions.append("property_id = %s"); params.append(property_id)
    if assigned_to is not None:
        conditions.append("assigned_to = %s"); params.append(assigned_to)
    if status:
        conditions.append("status = %s"); params.append(status)
    where = "WHERE " + " AND ".join(conditions)
    with db.cursor() as cur:
        cur.execute(f"SELECT * FROM appointments {where} ORDER BY starts_at ASC", params)
        return [Appointment(**r) for r in dict_fetchall(cur)]


@router.post("/appointments", response_model=Appointment, status_code=201)
def create_appointment(body: AppointmentCreate, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO appointments "
            "(account_id, property_id, assigned_to, title, location, starts_at, ends_at, notes, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (user["account_id"], body.property_id, body.assigned_to, body.title, body.location,
             body.starts_at, body.ends_at, body.notes, user["id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    return Appointment(**row)


@router.get("/appointments/{appt_id}", response_model=Appointment)
def get_appointment(appt_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM appointments WHERE id = %s AND account_id = %s", (appt_id, user["account_id"]))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return Appointment(**row)


@router.patch("/appointments/{appt_id}", response_model=Appointment)
def update_appointment(appt_id: int, body: AppointmentUpdate, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in APPOINTMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {APPOINTMENT_STATUSES}")
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")
    sets = [f"{k} = %s" for k in fields]
    params = list(fields.values()) + [appt_id, user["account_id"]]
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE appointments SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
            params,
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # Guard against a status-only no-op leaving an inverted window.
    if row["ends_at"] <= row["starts_at"]:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    return Appointment(**row)


@router.delete("/appointments/{appt_id}", status_code=204)
def delete_appointment(appt_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM appointments WHERE id = %s AND account_id = %s RETURNING id", (appt_id, user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Appointment not found")


@router.post("/appointments/{appt_id}/send")
def send_appointment(appt_id: int, body: SendAppointmentRequest, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    """Send the customer a calendar invite by email (with .ics) and/or SMS.

    Recipient defaults to the linked lead's contact email/phone; callers may
    override per channel. Each channel fails soft so one failure doesn't block
    the other — the response reports per-channel status."""
    from api.calendar_ics import build_ics
    from api.notifications import send_appointment_email, send_appointment_sms

    with db.cursor() as cur:
        cur.execute("SELECT * FROM appointments WHERE id = %s AND account_id = %s", (appt_id, user["account_id"]))
        appt = dict_fetchone(cur)
        if not appt:
            raise HTTPException(status_code=404, detail="Appointment not found")
        to_email, to_phone = body.to_email, body.to_phone
        if appt.get("property_id") and (not to_email or not to_phone):
            cur.execute(
                "SELECT contact_email, contact_phone FROM properties WHERE id = %s AND account_id = %s",
                (appt["property_id"], user["account_id"]),
            )
            lead = dict_fetchone(cur) or {}
            to_email = to_email or lead.get("contact_email")
            to_phone = to_phone or lead.get("contact_phone")

    business_name = user.get("username") or "Axon"
    results: dict[str, str] = {}

    if "email" in body.channels:
        if not to_email:
            results["email"] = "skipped: no recipient email"
        else:
            try:
                ics = build_ics(
                    uid=f"appt-{appt['id']}@axon-crm",
                    summary=appt["title"],
                    start=appt["starts_at"],
                    end=appt["ends_at"],
                    location=appt.get("location"),
                    description=appt.get("notes"),
                )
                send_appointment_email(
                    to_email=to_email, business_name=business_name, title=appt["title"],
                    starts_at=appt["starts_at"], location=appt.get("location"), ics_text=ics,
                )
                results["email"] = "sent"
            except Exception as exc:
                log.exception("appointment email failed for %d", appt_id)
                results["email"] = f"error: {exc}"

    if "sms" in body.channels:
        if not to_phone:
            results["sms"] = "skipped: no recipient phone"
        else:
            try:
                send_appointment_sms(
                    to_phone=to_phone, business_name=business_name, title=appt["title"],
                    starts_at=appt["starts_at"], location=appt.get("location"),
                )
                results["sms"] = "sent"
            except Exception as exc:
                log.exception("appointment sms failed for %d", appt_id)
                results["sms"] = f"error: {exc}"

    return {"results": results}


@router.get("/leads/{lead_id}/appointments", response_model=list[Appointment])
def lead_appointments(lead_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM appointments WHERE property_id = %s AND account_id = %s ORDER BY starts_at DESC",
            (lead_id, user["account_id"]),
        )
        return [Appointment(**r) for r in dict_fetchall(cur)]
