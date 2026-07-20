"""
POST /api/public/twilio/sms — inbound Twilio SMS webhook (two-way messaging).

Point the Twilio phone number's "A message comes in" webhook at this route.
Every request is verified against X-Twilio-Signature (signed with the auth
token over the full URL + form params), the sender is matched to a record by
phone number, and the message is logged to contact_history as an inbound SMS
so it threads into the record's timeline next to the outbound sends.

Tenancy note: when the To number is one of the per-account tracking numbers
(the `calls` module, api/routes/calls.py), the tenant is resolved from it, the
sender is matched *scoped to that account*, and an unknown sender becomes a
new lead — the SMS twin of the voice webhook in api/routes/twilio_voice.py.
Otherwise (the global TWILIO_FROM_NUMBER) matching is cross-account by phone
digits, tie-broken by whichever record was most recently texted (that's who
the customer is replying to); there an unknown sender can't be attributed to
a tenant, so no lead is created.
"""
import logging

import psycopg2.extras
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from psycopg2.extensions import connection as PGConn

from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
from api import call_logic
from api.deps import get_db
from api.notifications import sms_configured

log = logging.getLogger(__name__)

public_router = APIRouter()

# Twilio expects TwiML back; empty <Response/> = "received, no auto-reply".
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def normalize_phone(raw: str | None) -> str:
    """Last 10 digits of a phone number ('' when too short to be one), so
    +1 (713) 555-0142, 7135550142 and 17135550142 all compare equal."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) < 7:
        return ""
    return digits[-10:]


def _twiml() -> Response:
    return Response(content=EMPTY_TWIML, media_type="text/xml")


async def _signature_valid(request: Request) -> bool:
    from twilio.request_validator import RequestValidator
    url = str(request.url)
    # Render terminates TLS at its proxy (uvicorn sees plain http), but Twilio
    # signed the https URL it was configured with — same force-upgrade as the
    # MMS media link in api/routes/invoices.py.
    if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
        url = "https://" + url[len("http://"):]
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature", "")
    return RequestValidator(TWILIO_AUTH_TOKEN).validate(url, dict(form), signature)


def _active_tracking_number(db: PGConn, to_digits: str) -> dict | None:
    """The account owning this tracking number, or None when the To number
    isn't a tracking number (i.e. it's the global TWILIO_FROM_NUMBER)."""
    if not to_digits:
        return None
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, account_id FROM tracking_numbers "
            "WHERE phone_digits = %s AND status = 'active'",
            (to_digits,),
        )
        row = cur.fetchone()
    return {"id": row[0], "account_id": row[1]} if row else None


def _match_account_property_id(db: PGConn, account_id: int, digits: str) -> int | None:
    """The account's record with this sender's number on either contact phone —
    the account-scoped variant of _match_property_id."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.id FROM properties p "
            "WHERE p.account_id = %(account_id)s "
            "  AND (RIGHT(regexp_replace(COALESCE(p.contact_phone,''),     '[^0-9]', '', 'g'), 10) = %(digits)s "
            "    OR RIGHT(regexp_replace(COALESCE(p.contact_phone_alt,''), '[^0-9]', '', 'g'), 10) = %(digits)s) "
            "ORDER BY p.updated_at DESC NULLS LAST, p.id DESC "
            "LIMIT 1",
            {"account_id": account_id, "digits": digits},
        )
        row = cur.fetchone()
    return row[0] if row else None


def _match_property_id(db: PGConn, digits: str) -> int | None:
    """The record this sender is most plausibly replying to: match on either
    contact phone, preferring whoever we texted most recently."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.id FROM properties p "
            "LEFT JOIN LATERAL ("
            "  SELECT MAX(ch.created_at) AS last_out FROM contact_history ch "
            "  WHERE ch.property_id = p.id AND ch.channel = 'sms' AND ch.direction = 'outbound'"
            ") lo ON TRUE "
            "WHERE RIGHT(regexp_replace(COALESCE(p.contact_phone,''),     '[^0-9]', '', 'g'), 10) = %(digits)s "
            "   OR RIGHT(regexp_replace(COALESCE(p.contact_phone_alt,''), '[^0-9]', '', 'g'), 10) = %(digits)s "
            "ORDER BY lo.last_out DESC NULLS LAST, p.updated_at DESC NULLS LAST "
            "LIMIT 1",
            {"digits": digits},
        )
        row = cur.fetchone()
    return row[0] if row else None


@public_router.post("/public/twilio/sms")
async def inbound_sms(
    request: Request,
    From: str = Form(""),
    To: str = Form(""),
    Body: str = Form(""),
    MessageSid: str = Form(""),
    db: PGConn = Depends(get_db),
):
    # Tracking-number SMS needs only the account SID + auth token (like the
    # voice webhook); the global-number path additionally needs
    # TWILIO_FROM_NUMBER, which sms_configured() covers.
    if not (sms_configured() or (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)):
        return Response(status_code=403, content="SMS is not configured")
    if not await _signature_valid(request):
        log.warning("Inbound SMS rejected: invalid Twilio signature (From=%s)", From)
        return Response(status_code=403, content="Invalid signature")

    digits = normalize_phone(From)
    tracking = _active_tracking_number(db, normalize_phone(To))

    if tracking:
        # Tenant known from the To number — scope the match, and auto-create a
        # lead for an unknown sender (same play as the voice webhook).
        property_id = _match_account_property_id(db, tracking["account_id"], digits) if digits else None
        if property_id is None:
            row = call_logic.new_lead_row(From, digits, channel="sms")
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO properties (account_id, contact_name, contact_phone, status, "
                    "                        lead_source, enrichment_flags) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (tracking["account_id"], row["contact_name"], row["contact_phone"],
                     row["status"], row["lead_source"], psycopg2.extras.Json(row["enrichment_flags"])),
                )
                property_id = cur.fetchone()[0]
                db.commit()
            log.info("Inbound SMS from %s created lead %s for account %s",
                     From, property_id, tracking["account_id"])
    else:
        property_id = _match_property_id(db, digits) if digits else None
        if property_id is None:
            # Global-number text from an unknown sender: no tenant to attribute
            # a lead to. Still 200 + empty TwiML — an unmatched text isn't
            # Twilio's problem, and a non-2xx would make it retry forever.
            log.warning("Inbound SMS from %s matched no record", From)
            return _twiml()

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, channel, direction, body, external_id) "
            "VALUES (%s, 'SMS received', NULL, 'sms', 'inbound', %s, %s) "
            "ON CONFLICT (external_id) DO NOTHING",
            (property_id, Body, MessageSid or None),
        )
        db.commit()
    return _twiml()
