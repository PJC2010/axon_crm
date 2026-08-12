"""
Inbound call tracking webhooks (the `calls` module's public half).

POST /api/public/twilio/voice — Twilio's "A call comes in" webhook for every
purchased tracking number (api/routes/calls.py sets the URL at purchase time).
The tenant is resolved from the To number via tracking_numbers, the caller is
matched to a record by phone digits *scoped to that account* (unlike the SMS
route's cross-account match), an unknown caller becomes a new lead, the call
is logged, and the caller is forwarded to the business's real phone. When
PHONE_APPEND_PROVIDER names a provider, the caller's number is also
reverse-appended (address/name/email) onto the lead — once per caller, flagged
in enrichment_flags.phone_append. Callers this webhook couldn't reach in time
are backfilled later by api/call_append_sweep.py.

POST /api/public/twilio/voice/dial-status — the <Dial> action callback: one
request after the forwarded leg ends carrying DialCallStatus/DialCallDuration.
Records the outcome, rewrites the timeline line, and on a missed call drops an
urgent call-back task on the owner's plate (speed-to-lead, same play as
api/routes/public_intake.py).

POST /api/public/twilio/voice/outbound — the power dialer's TwiML App Voice
URL (the authenticated half lives in api/routes/dialer.py). The browser SDK
connects with a lead_id, never a phone number: the identity in From
(client:axon-<account>-<user>) is re-verified against the users table and the
number is resolved server-side from that account's own lead — so a leaked
Voice token can only dial phones this tenant already stores, and never a
do-not-call lead. Caller ID is the account's tracking number (call-backs ring
the tenant) with TWILIO_FROM_NUMBER as fallback.

POST /api/public/twilio/voice/outbound-status — the outbound <Dial> action
callback. Completes the mechanical outcome only; deliberately NO missed-call
task and NO call_event workflow rules — those are inbound speed-to-lead plays,
and firing the missed-call auto-text at a cold-called lead who never picked up
would be an unsolicited SMS. Human semantics land via POST /api/dialer/dispositions.

All routes are signature-verified against X-Twilio-Signature and must answer
2xx TwiML for every business-level miss (unknown number, released number,
unknown lead) — a non-2xx makes Twilio retry forever. Idempotency anchor:
calls.call_sid is UNIQUE, so webhook retries skip all side effects and
re-return the same TwiML.
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
from api import call_logic, dialer_logic, sms_logic
from api.deps import get_db
from api.lead_events_emit import emit_event
from api.phone_append_logic import merge_append, merge_flags
from api.routes.twilio_inbound import _match_account_property_id, _signature_valid, normalize_phone

log = logging.getLogger(__name__)

public_router = APIRouter()


def voice_configured() -> bool:
    """Unlike sms_configured(), no TWILIO_FROM_NUMBER needed — calls arrive on
    per-account tracking numbers, not the global platform number."""
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)


def dialer_configured() -> bool:
    """Browser calling needs an API Key pair + TwiML App on top of the base
    credentials. Read from config at call time (not module import) so the
    check tracks the live values."""
    import config
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN
                and config.TWILIO_API_KEY_SID and config.TWILIO_API_KEY_SECRET
                and config.TWILIO_TWIML_APP_SID)


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


def _append_caller_address(db: PGConn, account_id: int, property_id: int | None,
                           from_digits: str, lead_created: bool) -> None:
    """Reverse-append a caller's address onto their lead via the configured provider.

    Runs once per caller: a newly created lead always gets one attempt, a
    matched lead only when it still lacks an address and no earlier attempt was
    flagged (enrichment_flags.phone_append). The flag is written after any
    completed attempt — match or no-match, the provider charged for the query —
    so repeat calls from the same number never re-spend. Which columns may be
    filled is api/phone_append_logic.py's call, shared with the backfill sweep.

    Best-effort by construction: this runs post-commit and every failure is
    swallowed, because a provider outage must never stop the call connecting.
    """
    if not PHONE_APPEND_PROVIDER or not PHONE_APPEND_API_KEY \
            or not from_digits or property_id is None:
        return
    # Late import: api <-> pipeline. The registry check rides along with it so
    # an unknown provider name costs nothing but a dict lookup.
    from pipeline.contact import PHONE_APPEND_PROVIDERS, phone_append
    if PHONE_APPEND_PROVIDER not in PHONE_APPEND_PROVIDERS:
        return
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
        if not lead_created and (cur_addr or (cur_flags or {}).get("phone_append")):
            return  # already has an address, or an attempt was already paid for

        data = phone_append(from_digits)
        updates = merge_append(data, {
            "address": cur_addr, "city": cur_city, "state": cur_state,
            "zip": cur_zip, "contact_name": cur_name, "contact_email": cur_email,
        })
        flags = merge_flags(data, cur_flags, PHONE_APPEND_PROVIDER)

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
            "RETURNING account_id, property_id, from_digits, tracking_number_id",
            (outcome, duration, CallSid),
        )
        row = cur.fetchone()
        if not row:
            db.rollback()  # duplicate callback (or unknown sid) — nothing to do
            return _twiml(call_logic.build_hangup_twiml())
        account_id, property_id, from_digits, tracking_number_id = row

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
        try:
            _fire_call_event(db, account_id, property_id, outcome, tracking_number_id)
        except Exception:
            db.rollback()
            log.exception("Missed-call event rules failed for lead %s", property_id)

    return _twiml(call_logic.build_hangup_twiml())


# ── Outbound (power dialer) ───────────────────────────────────────────────────

def _outbound_caller_id(db: PGConn, account_id: int) -> tuple[str | None, int | None]:
    """(caller_id, tracking_number_id) for an outbound dial. The account's own
    tracking number first (call-backs then ring this tenant and thread here —
    same reasoning as notifications.account_sms_from), else TWILIO_FROM_NUMBER
    when it is a real number (a Messaging Service SID can't originate voice).
    (None, None) = no legal caller ID; the dial is refused."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, phone_number FROM tracking_numbers "
            "WHERE account_id = %s AND status = 'active' ORDER BY id LIMIT 1",
            (account_id,),
        )
        row = cur.fetchone()
    if row:
        return row[1], row[0]
    from config import TWILIO_FROM_NUMBER
    sender = sms_logic.normalize_sender(TWILIO_FROM_NUMBER)
    if sender and not sms_logic.is_messaging_service(sender) and sender.startswith("+"):
        return sender, None
    return None, None


def _dialable_e164(raw: str | None) -> str | None:
    """The lead's stored free-form phone as a dialable +1XXXXXXXXXX, or None."""
    e164 = sms_logic.normalize_recipient(raw)
    if len(e164) == 12 and e164.startswith("+1") and e164[1:].isdigit():
        return e164
    return None


@public_router.post("/public/twilio/voice/outbound")
async def outbound_call(
    request: Request,
    CallSid: str = Form(""),
    From: str = Form(""),
    lead_id: str = Form(""),          # device.connect custom params ride the
    phone_choice: str = Form("primary"),  # same form body as Twilio's own fields
    db: PGConn = Depends(get_db),
):
    if not dialer_configured():
        return Response(status_code=403, content="Browser calling is not configured")
    if not await _signature_valid(request):
        log.warning("Outbound dial rejected: invalid Twilio signature (From=%s)", From)
        return Response(status_code=403, content="Invalid signature")

    def _reject(reason: str, say: str = "This lead cannot be dialed."):
        # Business-level refusal: 2xx TwiML into the rep's headset, never a
        # non-2xx (Twilio would retry forever). Nothing is logged to the CRM —
        # no call happened.
        log.warning("Outbound dial refused (%s): from=%s lead=%s", reason, From, lead_id)
        return _twiml(call_logic.build_dialer_reject_twiml(say))

    identity = dialer_logic.parse_client_identity(From)
    if not identity or not lead_id.isdigit():
        return _reject("bad identity or lead id")
    account_id, user_id = identity

    # The token's identity carries account/user, but the users table is
    # authoritative — a stale or forged pairing dials nothing.
    with db.cursor() as cur:
        cur.execute("SELECT account_id, is_active FROM users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
    if not user_row or not user_row[1] or user_row[0] != account_id:
        return _reject("identity/user mismatch")

    with db.cursor() as cur:
        cur.execute(
            "SELECT contact_phone, contact_phone_alt, do_not_call "
            "FROM properties WHERE id = %s AND account_id = %s AND archived_at IS NULL",
            (int(lead_id), account_id),
        )
        lead = cur.fetchone()
    if not lead:
        return _reject("unknown lead")
    if lead[2]:
        return _reject("do-not-call lead", "This lead is flagged do not call.")

    to_e164 = _dialable_e164(lead[1] if phone_choice == "alt" else lead[0])
    if not to_e164:
        return _reject("no dialable phone", "This lead has no dialable phone number.")

    caller_id, tracking_number_id = _outbound_caller_id(db, account_id)
    if not caller_id:
        return _reject("no caller id", "No outbound caller I D is configured.")

    dial_twiml = call_logic.build_outbound_dial_twiml(
        to_e164, caller_id,
        f"{_api_base_url(request)}/api/public/twilio/voice/outbound-status",
    )
    if not CallSid:
        return _twiml(dial_twiml)  # can't log without an id; still place the call

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO calls (account_id, property_id, tracking_number_id, call_sid, "
            "                   direction, from_number, from_digits, to_number, user_id) "
            "VALUES (%s, %s, %s, %s, 'outbound', %s, %s, %s, %s) "
            "ON CONFLICT (call_sid) DO NOTHING RETURNING id",
            (account_id, int(lead_id), tracking_number_id, CallSid,
             caller_id, normalize_phone(caller_id), to_e164, user_id),
        )
        if not cur.fetchone():
            # Twilio retry: side effects already ran; same TwiML, rebuilt from
            # the same lead + caller-id lookups above.
            db.rollback()
            return _twiml(dial_twiml)
        # body stays NULL (plain action line, not a chat bubble); the status
        # callback rewrites the action and the disposition endpoint owns the
        # human outcome.
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, channel, "
            "                             direction, body, external_id, created_by) "
            "VALUES (%s, 'Outbound call', NULL, 'call', 'outbound', NULL, %s, %s) "
            "ON CONFLICT (external_id) DO NOTHING",
            (int(lead_id), CallSid, user_id),
        )
        db.commit()

    log.info("Outbound dial: account=%s user=%s lead=%s sid=%s",
             account_id, user_id, lead_id, CallSid)
    return _twiml(dial_twiml)


@public_router.post("/public/twilio/voice/outbound-status")
async def outbound_dial_status(
    request: Request,
    CallSid: str = Form(""),
    DialCallStatus: str = Form(""),
    DialCallDuration: str = Form(""),
    db: PGConn = Depends(get_db),
):
    if not dialer_configured():
        return Response(status_code=403, content="Browser calling is not configured")
    if not await _signature_valid(request):
        log.warning("Outbound dial status rejected: invalid Twilio signature (sid=%s)", CallSid)
        return Response(status_code=403, content="Invalid signature")

    outcome = call_logic.map_outbound_dial_status(DialCallStatus)
    duration = int(DialCallDuration) if DialCallDuration.isdigit() else None

    with db.cursor() as cur:
        cur.execute(
            "UPDATE calls SET status = 'completed', outcome = %s, duration_seconds = %s, "
            "completed_at = NOW() "
            "WHERE call_sid = %s AND status <> 'completed' "
            "RETURNING account_id, property_id",
            (outcome, duration, CallSid),
        )
        if not cur.fetchone():
            db.rollback()  # duplicate callback (or unknown sid) — nothing to do
            return _twiml(call_logic.build_hangup_twiml())
        # COALESCE keeps a human disposition that already landed via
        # POST /api/dialer/dispositions; the mechanical verdict only fills gaps.
        cur.execute(
            "UPDATE contact_history SET action = %s, outcome = COALESCE(outcome, %s) "
            "WHERE external_id = %s",
            (call_logic.outbound_history_action_for(outcome, duration),
             dialer_logic.history_outcome_for("no_answer") if outcome != "answered" else None,
             CallSid),
        )
        db.commit()

    # Deliberately nothing else: no missed-call task, no call_event workflow
    # rules (the missed-call auto-text must never SMS a cold-called lead who
    # didn't pick up), no lead_events — POST /api/dialer/dispositions owns the
    # human semantics for calls the rep placed and watched.
    return _twiml(call_logic.build_hangup_twiml())


def _account_owner_id(db: PGConn, account_id: int) -> int | None:
    """Lookup the account's owner user ID."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE account_id = %s AND role = 'owner' AND is_active = TRUE "
            "ORDER BY id LIMIT 1",
            (account_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _missed_call_task(db: PGConn, account_id: int, property_id: int, from_digits: str | None) -> None:
    """Speed-to-lead for a missed call: an urgent same-day call-back task for
    the account's owner (the task half of public_intake._speed_to_lead_response)."""
    owner_id = _account_owner_id(db, account_id)
    if not owner_id:
        return  # nobody to assign work to — skip quietly
    caller = call_logic.format_phone_display(from_digits or "") or "unknown number"
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO tasks (property_id, title, due_date, priority, created_by, account_id) "
            "VALUES (%s, %s, CURRENT_DATE, 'urgent', %s, %s)",
            (property_id, f"Missed call from {caller} — call back now", owner_id, account_id),
        )
        db.commit()


def _fire_call_event(db: PGConn, account_id: int, property_id: int, outcome: str,
                     tracking_number_id: int | None) -> None:
    """Fire call_event workflow rules for a missed or busy call. Runs with
    extra context about the tracking number for from-number overrides."""
    if outcome == "answered":
        return  # only fire for missed/busy
    owner_id = _account_owner_id(db, account_id)
    if not owner_id:
        return  # no user to attribute the action to
    extra = None
    if tracking_number_id:
        with db.cursor() as cur:
            cur.execute(
                "SELECT phone_number FROM tracking_numbers WHERE id = %s AND status = 'active'",
                (tracking_number_id,),
            )
            row = cur.fetchone()
        if row:
            extra = {"sms_from": row[0]}
    from api.workflow_engine import execute_object_event_rules
    try:
        execute_object_event_rules(
            db, account_id=account_id, lead_id=property_id,
            object_type="call", event=outcome, user_id=owner_id, extra=extra,
        )
    except Exception:
        log.exception("execute_object_event_rules failed for call event")
