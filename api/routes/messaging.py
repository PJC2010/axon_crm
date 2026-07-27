"""
GET    /api/message-templates        — list templates
POST   /api/message-templates        — create (owner)
PATCH  /api/message-templates/{id}   — update (owner)
DELETE /api/message-templates/{id}   — delete (owner)
POST   /api/leads/{id}/message       — render + send a message to the record's contact
GET    /api/leads/{id}/conversation  — the record's SMS thread, oldest first
POST   /api/leads/{id}/conversation/seen — mark the thread's inbound texts read
GET    /api/unread-messages          — account-wide unseen inbound SMS, per lead

Contact-level messaging (Phase 7). Templates carry {{merge_fields}} resolved
per record (see api/messaging.py); sends go out via the same Resend/Twilio
primitives as invoices and are logged to contact_history so they appear in the
record's activity timeline.

Two-way: inbound texts arrive via api/routes/twilio_inbound.py and join the
same contact_history thread. Inbound rows carry seen_at NULL until a user opens
the conversation; the unread summary powers the header message bell.
"""
import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner
from api import messaging, notifications
from api.models import (
    ConversationMessage, MessageTemplate, MessageTemplateCreate, MessageTemplateUpdate,
    SendMessageRequest, UnreadMessagesResponse, MESSAGE_CHANNELS,
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
def send_lead_message(lead_id: int, body: SendMessageRequest, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    account_id = user["account_id"]

    with db.cursor() as cur:
        cur.execute(
            "SELECT id, contact_name, contact_email, contact_phone, address, owner_name "
            "FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
        record = dict_fetchone(cur)
    if not record:
        raise HTTPException(status_code=404, detail="Lead not found")

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
            if not notifications.sms_configured():
                raise HTTPException(status_code=503, detail="SMS is not configured")
            notifications.send_sms(to_phone=recipient, body=rendered_body)
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


# ── Two-way conversation + unread tracking ──────────────────────────────────────

def _assert_lead(db: PGConn, lead_id: int, account_id: int) -> None:
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lead not found")


@router.get("/leads/{lead_id}/conversation", response_model=list[ConversationMessage])
def get_conversation(lead_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    """The record's SMS thread, oldest first — the chat view's data source."""
    _assert_lead(db, lead_id, user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, direction, body, created_at, seen_at FROM contact_history "
            "WHERE property_id = %s AND channel = 'sms' AND body IS NOT NULL "
            "ORDER BY created_at ASC, id ASC",
            (lead_id,),
        )
        return dict_fetchall(cur)


@router.post("/leads/{lead_id}/conversation/seen")
def mark_conversation_seen(lead_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    """Mark every inbound text on the thread read. Called when the conversation
    is on screen, so 'unread' always means 'arrived while nobody was looking'."""
    _assert_lead(db, lead_id, user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "UPDATE contact_history SET seen_at = NOW() "
            "WHERE property_id = %s AND direction = 'inbound' AND seen_at IS NULL",
            (lead_id,),
        )
        marked = cur.rowcount
        db.commit()
    return {"marked": marked}


@router.get("/unread-messages", response_model=UnreadMessagesResponse)
def unread_messages(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    """Unseen inbound texts for the account, grouped per lead (archived records
    excluded) — the header message bell polls this."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.id AS lead_id, p.contact_name, p.address, "
            "       COUNT(*) AS unseen, "
            "       (array_agg(ch.body ORDER BY ch.created_at DESC))[1] AS last_body, "
            "       MAX(ch.created_at) AS last_at "
            "FROM contact_history ch "
            "JOIN properties p ON p.id = ch.property_id "
            "WHERE p.account_id = %s AND p.archived_at IS NULL "
            "  AND ch.channel = 'sms' AND ch.direction = 'inbound' AND ch.seen_at IS NULL "
            "GROUP BY p.id, p.contact_name, p.address "
            "ORDER BY last_at DESC",
            (user["account_id"],),
        )
        rows = dict_fetchall(cur)
    return {"count": sum(r["unseen"] for r in rows), "leads": rows}
