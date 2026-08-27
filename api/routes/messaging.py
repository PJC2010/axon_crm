"""
GET    /api/message-templates        — list templates
POST   /api/message-templates        — create (owner)
PATCH  /api/message-templates/{id}   — update (owner)
DELETE /api/message-templates/{id}   — delete (owner)
POST   /api/leads/{id}/message       — render + send a message to the record's contact
GET    /api/sms/diagnostics          — why SMS sending is/isn't working (owner)

Contact-level messaging (Phase 7). Templates carry {{merge_fields}} resolved
per record (see api/messaging.py); sends go out via the same Resend/Twilio
primitives as invoices and are logged to contact_history so they appear in the
record's activity timeline.
"""
import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import (
    get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner,
    require_verified_sender,
)
from api.ratelimit import message_send_limiter
from api import messaging, notifications, scoring_quota
from api.models import (
    MessageTemplate, MessageTemplateCreate, MessageTemplateUpdate,
    SendMessageRequest, MESSAGE_CHANNELS,
)

log = logging.getLogger(__name__)

router = APIRouter()


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/message-templates", response_model=list[MessageTemplate])
def list_templates(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM message_templates WHERE account_id = %s ORDER BY name",
            (user["account_id"],),
        )
        return dict_fetchall(cur)


@router.post("/message-templates", status_code=201, response_model=MessageTemplate)
def create_template(body: MessageTemplateCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    if body.channel not in MESSAGE_CHANNELS:
        raise HTTPException(status_code=400, detail="channel must be 'email' or 'sms'")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required")
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO message_templates (account_id, name, channel, subject, body, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (current_user["account_id"], name, body.channel, body.subject, body.body, current_user["id"]),
            )
            row = dict_fetchone(cur)
            db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A template named '{name}' already exists")
    return row


@router.patch("/message-templates/{template_id}", response_model=MessageTemplate)
def update_template(template_id: int, body: MessageTemplateUpdate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    if body.channel is not None and body.channel not in MESSAGE_CHANNELS:
        raise HTTPException(status_code=400, detail="channel must be 'email' or 'sms'")
    sets, params = [], []
    for field in ("name", "channel", "subject", "body"):
        val = getattr(body, field)
        if val is not None:
            sets.append(f"{field} = %s"); params.append(val)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    sets.append("updated_at = NOW()")
    params.extend([template_id, current_user["account_id"]])
    try:
        with db.cursor() as cur:
            cur.execute(
                f"UPDATE message_templates SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
                params,
            )
            row = dict_fetchone(cur)
            db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409, detail="A template with that name already exists")
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return row


@router.delete("/message-templates/{template_id}", status_code=204)
def delete_template(template_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM message_templates WHERE id = %s AND account_id = %s RETURNING id",
                    (template_id, current_user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")


# ── Send to a record's contact ──────────────────────────────────────────────────

@router.post("/leads/{lead_id}/message")
def send_lead_message(lead_id: int, body: SendMessageRequest,
                      user: dict = Depends(require_verified_sender),
                      db: PGConn = Depends(get_db)):
    account_id = user["account_id"]
    message_send_limiter.check(f"acct:{account_id}")

    with db.cursor() as cur:
        cur.execute(
            "SELECT id, contact_name, contact_email, contact_phone, address, owner_name, "
            "       lead_score, status, lead_source "
            "FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
        record = dict_fetchone(cur)
    if not record:
        raise HTTPException(status_code=404, detail="Lead not found")
    # Sending consumes a reveal: the response echoes the recipient, which is
    # exactly the contact detail a masked lead withholds (api/scoring_quota.py).
    scoring_quota.require_actionable(db, account_id, record)

    # Resolve channel/subject/body from the template or the ad-hoc payload.
    channel, subject, template = body.channel or "email", body.subject, None
    text_body = body.body
    if body.template_id is not None:
        with db.cursor() as cur:
            cur.execute(
                "SELECT * FROM message_templates WHERE id = %s AND account_id = %s",
                (body.template_id, account_id),
            )
            template = dict_fetchone(cur)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        channel = template["channel"]
        subject = subject if subject is not None else template["subject"]
        text_body = text_body if text_body is not None else template["body"]

    if channel not in MESSAGE_CHANNELS:
        raise HTTPException(status_code=400, detail="channel must be 'email' or 'sms'")
    if not text_body:
        raise HTTPException(status_code=400, detail="Message body is required")

    recipient = messaging.recipient_for_channel(record, channel)
    if not recipient:
        raise HTTPException(status_code=400, detail=f"This contact has no {channel} address on file")

    # Per-policy sends (renewal reminders) merge that policy's fields.
    policy = None
    if body.policy_id is not None:
        with db.cursor() as cur:
            cur.execute(
                "SELECT * FROM policies WHERE id = %s AND account_id = %s AND property_id = %s",
                (body.policy_id, account_id, lead_id),
            )
            policy = dict_fetchone(cur)
        if not policy:
            raise HTTPException(status_code=404, detail="Policy not found on this record")

    with db.cursor() as cur:
        cur.execute("SELECT name, review_link FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
    business_name = row[0] if row else None

    ctx = messaging.build_context(record, business_name, policy=policy,
                                  review_link=row[1] if row else None)
    rendered_subject = messaging.render_template(subject, ctx)
    rendered_body = messaging.render_template(text_body, ctx)

    try:
        if channel == "email":
            if not notifications.email_configured():
                raise HTTPException(status_code=503, detail="Email is not configured")
            html = rendered_body.replace("\n", "<br>")
            notifications.send_email(to_email=recipient, subject=rendered_subject or "(no subject)", html=html)
        else:
            # Prefer the account's own tracking number so the text comes from
            # the number this contact already has on caller ID (and so replies
            # thread back to this tenant); TWILIO_FROM_NUMBER is the fallback.
            sms_from = notifications.account_sms_from(db, account_id)
            if not notifications.sms_configured(sms_from):
                raise HTTPException(status_code=503, detail="SMS is not configured")
            notifications.send_sms(to_phone=recipient, body=rendered_body, from_number=sms_from)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Message send failed for lead %d", lead_id)
        raise HTTPException(status_code=502, detail=f"Send failed: {exc}")

    label = template["name"] if template else "Message"
    if policy:
        policy_label = " ".join(x for x in (policy.get("carrier"), policy.get("policy_type")) if x) \
            or f"policy #{policy['id']}"
        label = f"{label} ({policy_label})"
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, created_by, "
            "channel, direction, body) "
            "VALUES (%s, %s, %s, %s, %s, 'outbound', %s)",
            (lead_id, f"{channel.upper()} sent — {label}", "sent", user["id"],
             channel, rendered_body),
        )
        db.commit()

    return {"sent": True, "channel": channel, "to": recipient}


@router.get("/sms/diagnostics")
def sms_diagnostics(current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    """Why SMS sends are failing, without sending one.

    Twilio's 21659 ("not a Twilio phone number or Short Code country mismatch")
    only says the send was refused, not which half of the pair is wrong. This
    asks Twilio directly whether the resolved sender is a number the configured
    Account SID actually owns and whether it is SMS-capable.

    The Twilio project's other numbers stay out of the response — only the count
    is reported — since one tenant has no business seeing another's number.
    """
    sms_from = notifications.account_sms_from(db, current_user["account_id"])
    report = notifications.verify_sms_sender(sms_from)
    owned_count = len(report.pop("available_senders", []))
    return {**report, "owned_number_count": owned_count,
            "configured": notifications.sms_configured(sms_from)}
