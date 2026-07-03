"""
POST /api/public/twilio/sms — inbound Twilio SMS webhook (two-way messaging).

Point the Twilio phone number's "A message comes in" webhook at this route.
Every request is verified against X-Twilio-Signature (signed with the auth
token over the full URL + form params), the sender is matched to a record by
phone number, and the message is logged to contact_history as an inbound SMS
so it threads into the record's timeline next to the outbound sends.

Tenancy note: the app currently sends from one global TWILIO_FROM_NUMBER, so
inbound matching is cross-account by phone digits, tie-broken by whichever
record was most recently texted (that's who the customer is replying to).
Per-account numbers matched on the To number can replace this later.
"""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from psycopg2.extensions import connection as PGConn

from config import TWILIO_AUTH_TOKEN
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
    if not sms_configured():
        return Response(status_code=403, content="SMS is not configured")
    if not await _signature_valid(request):
        log.warning("Inbound SMS rejected: invalid Twilio signature (From=%s)", From)
        return Response(status_code=403, content="Invalid signature")

    digits = normalize_phone(From)
    property_id = _match_property_id(db, digits) if digits else None
    if property_id is None:
        # Still 200 + empty TwiML: an unmatched text isn't Twilio's problem,
        # and a non-2xx would make it retry forever.
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
