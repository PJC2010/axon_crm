"""
POST /api/public/website-lead — public lead intake from the insure-auto
marketing website.

Authenticated by a shared-secret header (X-Axon-Api-Key) rather than a login:
the caller is insure-auto's own Next.js server (pages/api/quote-request.js and
pages/api/contact.js), never a visitor's browser directly, so there is no user
session to check. Every website lead is written to a single account, chosen via
PUBLIC_INTAKE_ACCOUNT_ID, since this deployment serves one agency.

Modeled on api/routes/twilio_inbound.py (public router + verified caller) and
api/routes/imports.py (dedup + provenance-tagging conventions).
"""
import logging
from hmac import compare_digest

import psycopg2.extras
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from psycopg2.extensions import connection as PGConn

from config import PUBLIC_INTAKE_ACCOUNT_ID, PUBLIC_INTAKE_API_KEY
from api.deps import get_db
from api.models import WebsiteLeadCreate
from api.ratelimit import client_ip, public_intake_limiter

log = logging.getLogger(__name__)
public_router = APIRouter()

# insure-auto's quote-type slugs -> Axon's insurance `vertical` categories
# (api/business_types.py _INSURANCE_CATEGORIES). renters-insurance has no clean
# match today, so it's left unmapped (still recorded in custom_fields).
_QUOTE_TYPE_TO_VERTICAL = {
    "personal-auto": "auto",
    "home-insurance": "home",
    "commercial-auto": "commercial",
}


def intake_configured() -> bool:
    return bool(PUBLIC_INTAKE_API_KEY and PUBLIC_INTAKE_ACCOUNT_ID)


def _key_valid(provided: str | None) -> bool:
    return bool(provided) and compare_digest(provided, PUBLIC_INTAKE_API_KEY)


@public_router.post("/public/website-lead")
async def create_website_lead(
    payload: WebsiteLeadCreate,
    request: Request,
    db: PGConn = Depends(get_db),
    x_axon_api_key: str | None = Header(default=None, alias="X-Axon-Api-Key"),
):
    if not intake_configured():
        raise HTTPException(status_code=503, detail="Website lead intake is not configured")
    if not _key_valid(x_axon_api_key):
        log.warning("Website lead intake rejected: invalid API key (ip=%s)", client_ip(request))
        raise HTTPException(status_code=403, detail="Invalid API key")

    public_intake_limiter.check(client_ip(request))

    try:
        payload.validate_lead()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    account_id = int(PUBLIC_INTAKE_ACCOUNT_ID)
    vertical = _QUOTE_TYPE_TO_VERTICAL.get(payload.quote_type or "")

    custom_fields = dict(payload.fields or {})
    if payload.quote_type:
        custom_fields["quote_type"] = payload.quote_type
    if payload.subject:
        custom_fields["subject"] = payload.subject
    if payload.message:
        custom_fields["message"] = payload.message

    row = {
        "contact_name": payload.full_name.strip(),
        "contact_email": payload.email.strip().lower(),
        "contact_phone": payload.phone,
        "vertical": vertical,
        "status": "prospect",
        "lead_source": f"website_{payload.form_type}_form",
        "enrichment_flags": {
            "source": "insure_auto_website",
            "form_type": payload.form_type,
            "is_preview": payload.is_preview,
        },
        "custom_fields": custom_fields,
    }

    with db.cursor() as cur:
        inserted, lead_id = _upsert_lead(cur, account_id, row)
        note = f"Website {payload.form_type} form submission" + (
            f" ({payload.quote_type})" if payload.quote_type else ""
        )
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, channel, direction, body) "
            "VALUES (%s, %s, NULL, 'website', 'inbound', %s)",
            (lead_id, note, payload.message or ""),
        )
        db.commit()

    # Speed-to-lead (prospective-user audit P1): most website leads hire the
    # first responder, so acknowledge instantly and put a call on someone's
    # plate now — never at the cost of the intake itself.
    if inserted and not payload.is_preview:
        try:
            _speed_to_lead_response(db, account_id, lead_id, row)
        except Exception:
            db.rollback()
            log.exception("Speed-to-lead response failed for lead %s", lead_id)

    log.info(
        "Website lead intake: account=%s lead=%s form=%s inserted=%s",
        account_id, lead_id, payload.form_type, inserted,
    )
    return {"ok": True, "created": inserted}


def _speed_to_lead_response(db: PGConn, account_id: int, lead_id: int, row: dict) -> None:
    """Instant follow-through on a brand-new website lead.

    1. An urgent same-day task for the account's owner ("call within 5 minutes"),
       so the lead lands on the Command Center immediately.
    2. An SMS acknowledgment from the account's "Website lead auto-reply (SMS)"
       template (seeded by the business-type packs; owners can edit or delete it
       to change/disable the auto-reply). Fails soft: no Twilio, no template, or
       no phone simply skips the send.
    """
    from api import messaging, notifications

    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE account_id = %s AND role = 'owner' AND is_active = TRUE "
            "ORDER BY id LIMIT 1",
            (account_id,),
        )
        owner = cur.fetchone()
    if not owner:
        return  # nobody to assign work to — skip quietly

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO tasks (property_id, title, due_date, priority, created_by, account_id) "
            "VALUES (%s, %s, CURRENT_DATE, 'urgent', %s, %s)",
            (lead_id, "New website lead — call within 5 minutes", owner[0], account_id),
        )
        db.commit()

    if not (row.get("contact_phone") and notifications.sms_configured()):
        return
    with db.cursor() as cur:
        cur.execute(
            "SELECT body FROM message_templates WHERE account_id = %s "
            "AND name = 'Website lead auto-reply (SMS)' AND channel = 'sms'",
            (account_id,),
        )
        template = cur.fetchone()
    if not template:
        return  # owner removed the template = auto-reply off
    with db.cursor() as cur:
        cur.execute("SELECT name FROM accounts WHERE id = %s", (account_id,))
        acct = cur.fetchone()
    body = messaging.render_template(
        template[0], messaging.build_context(row, acct[0] if acct else None))
    notifications.send_sms(to_phone=row["contact_phone"], body=body)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, channel, direction, body) "
            "VALUES (%s, 'SMS sent — Website lead auto-reply', 'sent', 'sms', 'outbound', %s)",
            (lead_id, body),
        )
        db.commit()


def _upsert_lead(cur, account_id: int, row: dict) -> tuple[bool, int]:
    """Insert or update by (account_id, lower(contact_email)) — the partial
    unique index from db/migrations/0018_contact_import.sql. Website leads are
    always address-less people contacts, so email is the only dedup key needed
    (unlike imports.py's address-first variant).

    contact_email and status are excluded from the UPDATE SET: email is the
    conflict key, and a repeat submission from a lead who has already moved
    past Prospect (Quoted/Bound/...) shouldn't be reset backwards.
    """
    cols = ["account_id"] + list(row.keys())
    values = [account_id] + [
        psycopg2.extras.Json(v) if k in ("enrichment_flags", "custom_fields") else v
        for k, v in row.items()
    ]
    col_names = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))

    plain_updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in row
        if c not in ("contact_email", "status", "enrichment_flags", "custom_fields")
    )
    merge_updates = (
        "enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags, "
        "custom_fields = properties.custom_fields || EXCLUDED.custom_fields"
    )
    updates = ", ".join(u for u in (plain_updates, merge_updates) if u)

    cur.execute(
        f"INSERT INTO properties ({col_names}) VALUES ({placeholders}) "
        "ON CONFLICT (account_id, lower(contact_email)) "
        "WHERE address IS NULL AND contact_email IS NOT NULL "
        f"DO UPDATE SET {updates} "
        "RETURNING id, (xmax = 0) AS inserted",
        values,
    )
    lead_id, inserted = cur.fetchone()
    return bool(inserted), lead_id
