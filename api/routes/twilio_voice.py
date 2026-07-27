"""
Inbound call tracking webhooks (the `calls` module's public half).

POST /api/public/twilio/voice — Twilio's "A call comes in" webhook for every
purchased tracking number (api/routes/calls.py sets the URL at purchase time).
The tenant is resolved from the To number via tracking_numbers, the caller is
matched to a record by phone digits *scoped to that account* (unlike the SMS
route's cross-account match), an unknown caller becomes a new lead, the call
is logged, and the caller is forwarded to the business's real phone. When
PHONE_APPEND_PROVIDER=versium, the caller's number is also reverse-appended
(address/name/email) onto the lead — once per caller, flagged in
enrichment_flags.phone_append.

POST /api/public/twilio/voice/dial-status — the <Dial> action callback: one
request after the forwarded leg ends carrying DialCallStatus/DialCallDuration.
Records the outcome, rewrites the timeline line, and on a missed call drops an
urgent call-back task on the owner's plate (speed-to-lead, same play as
api/routes/public_intake.py).

Both routes are signature-verified against X-Twilio-Signature and must answer
2xx TwiML for every business-level miss (unknown number, released number) —
a non-2xx makes Twilio retry forever. Idempotency anchor: calls.call_sid is
UNIQUE, so webhook retries skip all side effects and re-return the same TwiML.
"""
import logging

import psycopg2.extras
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from psycopg2.extensions import connection as PGConn

from config import (
    PHONE_APPEND_API_KEY, PHONE_APPEND_PROVIDER,
    PUBLIC_API_BASE_URL, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
)
from api import call_logic
from api.deps import get_db
from api.lead_events_emit import emit_event
from api.routes.twilio_inbound import _match_account_property_id, _signature_valid, normalize_phone

log = logging.getLogger(__name__)

public_router = APIRouter()


def voice_configured() -> bool:
    """Unlike sms_configured(), no TWILIO_FROM_NUMBER needed — calls arrive on
    per-account tracking numbers, not the global platform number."""
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)


def _twiml(xml: str) -> Response:
    return Response(content=xml, media_type="text/xml")


def _api_base_url(request: Request) -> str:
    """Public origin for webhook callback URLs. PUBLIC_API_BASE_URL when set;
    otherwise the incoming request's own origin, force-upgraded to https for
    Render's TLS-terminating proxy (same reasoning as _signature_valid)."""
    if PUBLIC_API_BASE_URL:
        return PUBLIC_API_BASE_URL.rstrip("/")
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://") and "localhost" not in base and "127.0.0.1" not in base:
        base = "https://" + base[len("http://"):]
    return base


def _active_tracking_number(db: PGConn, to_digits: str) -> dict | None:
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, account_id, forward_to FROM tracking_numbers "
            "WHERE phone_digits = %s AND status = 'active'",
            (to_digits,),
        )
        row = cur.fetchone()
    return {"id": row[0], "account_id": row[1], "forward_to": row[2]} if row else None


# Columns a reverse phone append may fill — never user-editable-only fields.
_APPEND_FIELDS = ("address", "city", "state", "zip", "contact_email")


def _append_caller_address(db: PGConn, account_id: int, property_id: int | None,
                           from_digits: str, lead_created: bool) -> None:
    """Reverse-append a caller's address via Versium onto their lead.

    Runs once per caller: a newly created lead always gets one attempt, a
    matched lead only when it still lacks an address and no earlier attempt was
    flagged (enrichment_flags.phone_append). The flag is written after any
    completed attempt — match or no-match, the provider charged for the query —
    so repeat calls from the same number never re-spend. Only empty fields are
    filled; a real contact_name beats call_logic's "Caller ..." placeholder.
    """
    if PHONE_APPEND_PROVIDER != "versium" or not PHONE_APPEND_API_KEY \
            or not from_digits or property_id is None:
        return
    from pipeline.contact import versium_phone_append  # late import: api <-> pipeline
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT address, city, state, zip, contact_name, contact_email, "
                "       enrichment_flags "
                "FROM properties WHERE id = %s AND account_id = %s",
                (property_id, account_id),
            )
            row = cur.fetchone()
        if not row:
            return
        (cur_addr, cur_city, cur_state, cur_zip, cur_name, cur_email,
         cur_flags) = row
        flags = dict(cur_flags or {})
        if not lead_created and (cur_addr or flags.get("phone_append")):
            return  # already has an address, or an attempt was already paid for

        data = versium_phone_append(from_digits) or {}
        current = {"address": cur_addr, "city": cur_city, "state": cur_state,
                   "zip": cur_zip, "contact_email": cur_email}
        updates = {f: data[f] for f in _APPEND_FIELDS
                   if data.get(f) and not current[f]}
        if data.get("contact_name") and \
                (not cur_name or cur_name.startswith("Caller ")):
            updates["contact_name"] = data["contact_name"]

        flags["phone_append"] = PHONE_APPEND_PROVIDER
        sets = [f"{k} = %s" for k in updates]
        params = list(updates.values())
        with db.cursor() as cur:
            cur.execute(
                f"UPDATE properties SET {', '.join(sets + ['enrichment_flags = %s'])} "
                "WHERE id = %s AND account_id = %s",
                (*params, psycopg2.extras.Json(flags), property_id, account_id),
            )
            db.commit()
        log.info("Phone append: account=%s lead=%s filled=%s",
                 account_id, property_id, sorted(updates))
    except Exception:
        db.rollback()
        log.exception("Phone append failed for lead %s", property_id)


@public_router.post("/public/twilio/voice")
async def inbound_call(
    request: Request,
    CallSid: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    CallerName: str = Form(""),
    db: PGConn = Depends(get_db),
):
    if not voice_configured():
        return Response(status_code=403, content="Call tracking is not configured")
    if not await _signature_valid(request):
        log.warning("Inbound call rejected: invalid Twilio signature (From=%s)", From)
        return Response(status_code=403, content="Invalid signature")

    tracking = _active_tracking_number(db, normalize_phone(To))
    if not tracking or not tracking["forward_to"]:
        # Number released or never configured — not Twilio's problem; 200 or it
        # retries forever.
        log.warning("Inbound call to %s matched no forwardable tracking number", To)
        return _twiml(call_logic.build_unconfigured_twiml())

    dial_twiml = call_logic.build_dial_twiml(
        tracking["forward_to"],
        f"{_api_base_url(request)}/api/public/twilio/voice/dial-status",
    )
    if not CallSid:
        return _twiml(dial_twiml)  # can't log without an id; still connect the call

    from_digits = normalize_phone(From)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO calls (account_id, property_id, tracking_number_id, call_sid, "
            "                   from_number, from_digits, to_number, caller_name) "
            "VALUES (%s, NULL, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (call_sid) DO NOTHING RETURNING id",
            (tracking["account_id"], tracking["id"], CallSid,
             From, from_digits, To, CallerName.strip() or None),
        )
        fresh = cur.fetchone()
        if not fresh:
            # Twilio retry: every side effect already happened; same TwiML,
            # rebuilt purely from the tracking_numbers row.
            db.rollback()
            return _twiml(dial_twiml)

        property_id = _match_account_property_id(db, tracking["account_id"], from_digits) if from_digits else None
        lead_created = property_id is None
        if lead_created:
            row = call_logic.new_lead_row(From, from_digits, CallerName)
            cur.execute(
                "INSERT INTO properties (account_id, contact_name, contact_phone, status, "
                "                        lead_source, enrichment_flags) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (tracking["account_id"], row["contact_name"], row["contact_phone"],
                 row["status"], row["lead_source"], psycopg2.extras.Json(row["enrichment_flags"])),
            )
            property_id = cur.fetchone()[0]

        cur.execute(
            "UPDATE calls SET property_id = %s, lead_created = %s WHERE id = %s",
            (property_id, lead_created, fresh[0]),
        )
        # body stays NULL: the timeline renders body-less rows as plain action
        # lines, not chat bubbles. The dial-status callback rewrites action/
        # outcome once the call's fate is known.
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, channel, direction, body, external_id) "
            "VALUES (%s, 'Inbound call', NULL, 'call', 'inbound', NULL, %s) "
            "ON CONFLICT (external_id) DO NOTHING",
            (property_id, CallSid),
        )
        db.commit()

    # Post-commit, best-effort: reverse-append the caller's address via Versium
    # so an unknown caller's lead arrives with more than a phone number. Never
    # blocks the forward — any failure is logged and the call still connects.
    _append_caller_address(db, tracking["account_id"], property_id,
                           from_digits, lead_created)

    log.info("Inbound call: account=%s lead=%s created=%s sid=%s",
             tracking["account_id"], property_id, lead_created, CallSid)
    return _twiml(dial_twiml)


@public_router.post("/public/twilio/voice/dial-status")
async def dial_status(
    request: Request,
    CallSid: str = Form(""),
    DialCallStatus: str = Form(""),
    DialCallDuration: str = Form(""),
    db: PGConn = Depends(get_db),
):
    if not voice_configured():
        return Response(status_code=403, content="Call tracking is not configured")
    if not await _signature_valid(request):
        log.warning("Dial status rejected: invalid Twilio signature (sid=%s)", CallSid)
        return Response(status_code=403, content="Invalid signature")

    outcome = call_logic.map_dial_status(DialCallStatus)
    duration = int(DialCallDuration) if DialCallDuration.isdigit() else None

    with db.cursor() as cur:
        cur.execute(
            "UPDATE calls SET status = 'completed', outcome = %s, duration_seconds = %s, "
            "completed_at = NOW() "
            "WHERE call_sid = %s AND status <> 'completed' "
            "RETURNING account_id, property_id, from_digits",
            (outcome, duration, CallSid),
        )
        row = cur.fetchone()
        if not row:
            db.rollback()  # duplicate callback (or unknown sid) — nothing to do
            return _twiml(call_logic.build_hangup_twiml())
        account_id, property_id, from_digits = row

        cur.execute(
            "UPDATE contact_history SET action = %s, outcome = %s WHERE external_id = %s",
            (call_logic.history_action_for(outcome, duration), outcome, CallSid),
        )
        db.commit()

    # Post-commit side effects, both best-effort: the call outcome is recorded
    # either way.
    if property_id is not None and outcome == "answered":
        emit_event(db, property_id, account_id, "contacted", channel="call",
                   metadata={"call_sid": CallSid, "direction": "inbound", "duration": duration})
    elif property_id is not None:
        try:
            _missed_call_task(db, account_id, property_id, from_digits)
        except Exception:
            db.rollback()
            log.exception("Missed-call task failed for lead %s", property_id)

    return _twiml(call_logic.build_hangup_twiml())


def _missed_call_task(db: PGConn, account_id: int, property_id: int, from_digits: str | None) -> None:
    """Speed-to-lead for a missed call: an urgent same-day call-back task for
    the account's owner (the task half of public_intake._speed_to_lead_response)."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE account_id = %s AND role = 'owner' AND is_active = TRUE "
            "ORDER BY id LIMIT 1",
            (account_id,),
        )
        owner = cur.fetchone()
        if not owner:
            return  # nobody to assign work to — skip quietly
        caller = call_logic.format_phone_display(from_digits or "") or "unknown number"
        cur.execute(
            "INSERT INTO tasks (property_id, title, due_date, priority, created_by, account_id) "
            "VALUES (%s, %s, CURRENT_DATE, 'urgent', %s, %s)",
            (property_id, f"Missed call from {caller} — call back now", owner[0], account_id),
        )
        db.commit()
