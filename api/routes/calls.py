"""
Call-tracking management (the `calls` module's authenticated half — the
webhooks live in api/routes/twilio_voice.py and stay public).

Endpoints:
  POST   /calls/activate            — one-click setup (owner-only): business
                                      line in, tracking number + auto-text out
  GET    /calls/settings            — tracking number, forwarding, auto-reply
  PATCH  /calls/settings            — set the forwarding destination, or
                                      toggle/edit the missed-call auto-text
  GET    /calls/numbers/available   — search purchasable local numbers
  POST   /calls/numbers             — buy a specific number (owner-only, one per account)
  DELETE /calls/numbers/{number_id} — release the number (owner-only)
  GET    /calls                     — account-wide call log

**The intended setup path is POST /calls/activate**: the owner types the phone
their business line already rings on, and gets back a tracking number in the
same area code that forwards to it, with missed-call auto-texting on. The
search + POST /calls/numbers pair stays for owners who want to pick the digits
themselves; both end at the same `tracking_numbers` row.

Once a number exists, texting works in both directions with no further setup —
outbound sends resolve the account's own number as the sender
(api/notifications.py::account_sms_from) and inbound replies to it resolve back
to this tenant (api/routes/twilio_inbound.py).

The whole router is gated on the `calls` module in api/main.py. Twilio's REST
client is lazy-imported inside handlers (same as api/notifications.py) so the
API runs fine without the dependency exercised; when TWILIO_* is unset the
number endpoints 503 and GET /calls/settings reports configured=false so the
frontend shows a setup-required state instead of erroring.
"""
import logging

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
from api import call_setup_logic
from api.deps import get_db, get_current_user, require_owner, dict_fetchall, dict_fetchone
from api.routes.twilio_inbound import normalize_phone
from api.routes.twilio_voice import voice_configured, dialer_configured, _api_base_url

log = logging.getLogger(__name__)

router = APIRouter()


class CallSettingsUpdate(BaseModel):
    # All optional: a PATCH may change the forwarding destination, the
    # missed-call auto-text, or both. An empty body is a 400 rather than a
    # silent no-op.
    forward_to: str | None = None
    auto_reply: bool | None = None
    auto_reply_body: str | None = None


class NumberPurchase(BaseModel):
    phone_number: str          # E.164 from the availability search
    forward_to: str | None = None  # optionally set the destination in one step


class CallActivation(BaseModel):
    """One-click activation: everything the owner has to decide, which is
    almost nothing — the business line to ring, and whether missed callers get
    an automatic text back."""
    forward_to: str                    # the business line calls forward to
    area_code: str | None = None       # override; defaults to forward_to's own
    auto_reply: bool = True            # seed the missed-call auto-text
    auto_reply_body: str | None = None # override the default wording


def _twilio_client():
    if not voice_configured():
        raise HTTPException(status_code=503, detail="Call tracking is not configured (TWILIO_* env vars)")
    from twilio.rest import Client
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _active_number(db: PGConn, account_id: int) -> dict | None:
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, phone_number, friendly_name, forward_to, created_at "
            "FROM tracking_numbers WHERE account_id = %s AND status = 'active' "
            "ORDER BY id LIMIT 1",
            (account_id,),
        )
        return dict_fetchone(cur)


def _validated_forward_to(raw: str) -> str:
    forward_to = raw.strip()
    if len(normalize_phone(forward_to)) != 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit US phone number to forward calls to")
    return forward_to


# ── Missed-call auto-text ─────────────────────────────────────────────────────
#
# Two rows working together: an SMS message_templates row holding the wording,
# and a `call_event` workflow_rules row that sends it when a call comes back
# missed. Both are looked up by the fixed names in api/call_setup_logic.py, so
# the owner can still edit either one in Settings → Automation afterwards and
# this stays pointed at their edit rather than resurrecting the default.
#
# The engine runs call_event rules straight from the voice webhook, so the
# auto-text does not depend on the `automation` module being enabled — it ships
# with `calls`.

def _auto_reply_state(db: PGConn, account_id: int) -> dict:
    """Whether the missed-call auto-text is on, and what it says."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT r.id AS rule_id, r.is_active, t.id AS template_id, t.body "
            "FROM workflow_rules r "
            "LEFT JOIN message_templates t "
            "  ON t.account_id = r.account_id AND t.name = %s "
            "WHERE r.account_id = %s AND r.trigger_type = 'call_event' AND r.name = %s "
            "ORDER BY r.id LIMIT 1",
            (call_setup_logic.AUTO_REPLY_TEMPLATE_NAME, account_id,
             call_setup_logic.AUTO_REPLY_RULE_NAME),
        )
        row = dict_fetchone(cur)
    if not row:
        return {"enabled": False, "rule_id": None, "template_id": None, "body": None}
    return {
        "enabled": bool(row["is_active"]),
        "rule_id": row["rule_id"],
        "template_id": row["template_id"],
        "body": row["body"],
    }


def _enable_auto_reply(db: PGConn, account_id: int, user_id: int,
                       body: str | None = None) -> dict:
    """Create (or re-enable) the missed-call auto-text. Idempotent.

    ``body`` overwrites the template's wording when given; None leaves an
    existing template alone, so re-enabling never clobbers an owner's edit.
    """
    with db.cursor() as cur:
        cur.execute("SELECT name FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
    business_name = row[0] if row else None
    default_body = call_setup_logic.default_auto_reply_body(business_name)

    with db.cursor() as cur:
        # COALESCE(%s, …) on the conflict path: an explicit body wins, otherwise
        # whatever is already stored survives.
        cur.execute(
            "INSERT INTO message_templates (account_id, name, channel, body, created_by) "
            "VALUES (%s, %s, 'sms', %s, %s) "
            "ON CONFLICT (account_id, name) DO UPDATE "
            "SET body = COALESCE(%s, message_templates.body) "
            "RETURNING id",
            (account_id, call_setup_logic.AUTO_REPLY_TEMPLATE_NAME,
             body or default_body, user_id, body),
        )
        template_id = cur.fetchone()[0]

        # workflow_rules has no unique key on (account_id, name), so this is a
        # look-then-write rather than an upsert.
        cur.execute(
            "SELECT id FROM workflow_rules "
            "WHERE account_id = %s AND trigger_type = 'call_event' AND name = %s "
            "ORDER BY id LIMIT 1",
            (account_id, call_setup_logic.AUTO_REPLY_RULE_NAME),
        )
        existing = cur.fetchone()
        trigger_cfg = psycopg2.extras.Json(call_setup_logic.auto_reply_trigger_config())
        action_cfg = psycopg2.extras.Json(call_setup_logic.auto_reply_action_config(template_id))
        if existing:
            cur.execute(
                "UPDATE workflow_rules SET is_active = TRUE, trigger_config = %s, "
                "action_config = %s, updated_at = NOW() WHERE id = %s RETURNING id",
                (trigger_cfg, action_cfg, existing[0]),
            )
        else:
            cur.execute(
                "INSERT INTO workflow_rules (account_id, name, trigger_type, trigger_config, "
                "                            action_type, action_config, is_active, created_by) "
                "VALUES (%s, %s, 'call_event', %s, 'send_template', %s, TRUE, %s) RETURNING id",
                (account_id, call_setup_logic.AUTO_REPLY_RULE_NAME,
                 trigger_cfg, action_cfg, user_id),
            )
        rule_id = cur.fetchone()[0]
        db.commit()

    log.info("Missed-call auto-text enabled for account %s (rule=%s template=%s)",
             account_id, rule_id, template_id)
    return _auto_reply_state(db, account_id)


def _disable_auto_reply(db: PGConn, account_id: int) -> dict:
    """Stop auto-texting missed callers. The rule and its template are kept, so
    flipping it back on restores the owner's wording."""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE workflow_rules SET is_active = FALSE, updated_at = NOW() "
            "WHERE account_id = %s AND trigger_type = 'call_event' AND name = %s",
            (account_id, call_setup_logic.AUTO_REPLY_RULE_NAME),
        )
        db.commit()
    return _auto_reply_state(db, account_id)


@router.get("/calls/settings")
def get_call_settings(
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    return {
        "configured": voice_configured(),
        # Browser calling (the power dialer) needs the API-key/TwiML-App env
        # vars on top; false = the dialer page falls back to tel: links.
        "voice_dialing": dialer_configured(),
        "number": _active_number(db, current_user["account_id"]),
        "auto_reply": _auto_reply_state(db, current_user["account_id"]),
    }


@router.patch("/calls/settings")
def update_call_settings(
    payload: CallSettingsUpdate,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    account_id = current_user["account_id"]
    touches_auto_reply = payload.auto_reply is not None or payload.auto_reply_body is not None
    if payload.forward_to is None and not touches_auto_reply:
        raise HTTPException(status_code=400, detail="Nothing to update")
    # Forwarding is an operational setting any user can fix; the auto-text is an
    # automation that sends on the account's behalf, so it follows the same
    # owner-only rule as the rest of api/routes/workflows.py.
    if touches_auto_reply and current_user["role"] not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner access required to change the missed-call auto-text")

    try:
        body = call_setup_logic.clean_auto_reply_body(payload.auto_reply_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if payload.forward_to is not None:
        forward_to = _validated_forward_to(payload.forward_to)
        with db.cursor() as cur:
            cur.execute(
                "UPDATE tracking_numbers SET forward_to = %s "
                "WHERE account_id = %s AND status = 'active' RETURNING id",
                (forward_to, account_id),
            )
            updated = cur.fetchone()
            db.commit()
        if not updated:
            raise HTTPException(status_code=404, detail="No active tracking number to configure")

    # Wording is written first, then the switch is applied — so a PATCH that
    # rewrites the text *and* turns it off keeps the rewrite for next time
    # instead of silently dropping it.
    if body is not None or payload.auto_reply is True:
        # A body edit on its own implies "keep it on": nobody rewrites the
        # wording of a text they mean to leave switched off.
        _enable_auto_reply(db, account_id, current_user["id"], body=body)
    if payload.auto_reply is False:
        _disable_auto_reply(db, account_id)

    return {
        "ok": True,
        "number": _active_number(db, account_id),
        "auto_reply": _auto_reply_state(db, account_id),
    }


@router.get("/calls/numbers/available")
def search_available_numbers(
    area_code: str | None = Query(None, min_length=3, max_length=3),
    contains: str | None = Query(None, max_length=10),
    current_user: dict = Depends(get_current_user),
):
    client = _twilio_client()
    try:
        found = client.available_phone_numbers("US").local.list(
            area_code=int(area_code) if area_code and area_code.isdigit() else None,
            contains=contains or None,
            voice_enabled=True,
            # Outbound texts and the inbound-SMS webhook both hang off this
            # number, so a voice-only one would buy a number that can't message.
            sms_enabled=True,
            limit=20,
        )
    except Exception as exc:
        log.warning("Twilio number search failed: %s", exc)
        raise HTTPException(status_code=502, detail="Number search failed — try a different area code")
    return {
        "numbers": [
            {
                "phone_number": n.phone_number,
                "friendly_name": n.friendly_name,
                "locality": n.locality,
                "region": n.region,
            }
            for n in found
        ]
    }


def _buy_number(client, phone_number: str, base_url: str):
    """Buy one number from Twilio with both webhooks already pointed at us.

    Doing it here rather than by hand in the console is what makes a tracking
    number work the moment it's bought: voice reaches the forwarding webhook,
    and texts to it reach the tenant-scoped inbound-SMS webhook (which is what
    makes two-way texting work on the account's own number).
    """
    return client.incoming_phone_numbers.create(
        phone_number=phone_number,
        voice_url=f"{base_url}/api/public/twilio/voice",
        voice_method="POST",
        sms_url=f"{base_url}/api/public/twilio/sms",
        sms_method="POST",
    )


def _record_number(db: PGConn, client, account_id: int, purchased,
                   forward_to: str | None) -> None:
    """Persist a just-bought number, releasing it if the insert fails.

    Real money was spent by the time this runs, so a failed insert must not
    strand the number on the Twilio project with nothing in the DB pointing at
    it — the webhook resolves tenants through `tracking_numbers`, so an
    unrecorded number would ring nowhere and still bill monthly.
    """
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO tracking_numbers (account_id, phone_number, phone_digits, "
                "                              twilio_sid, forward_to, friendly_name) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (account_id, purchased.phone_number, normalize_phone(purchased.phone_number),
                 purchased.sid, forward_to, purchased.friendly_name),
            )
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Recording purchased number %s failed; releasing it", purchased.sid)
        try:
            client.incoming_phone_numbers(purchased.sid).delete()
        except Exception:
            log.exception("Release of stranded number %s also failed — release it in the Twilio console", purchased.sid)
        raise HTTPException(status_code=500, detail="Purchase could not be recorded; the number was released")


@router.post("/calls/activate")
def activate_call_tracking(
    payload: CallActivation,
    request: Request,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    """Turn on call tracking in one request: business line in, working number out.

    The owner types the phone their business already rings on and accepts; this
    picks a number for them (same area code as that line, so it reads local),
    buys it with both webhooks wired, points it at their line, and — unless they
    opted out — switches on the missed-call auto-text.

    Number inventory is live: a number in the search results can be sold to
    someone else a second later, and an area code can be empty entirely. So this
    walks candidates (api/call_setup_logic.py::search_area_codes) and only fails
    once every area code, including "anywhere in the US", comes up empty.
    """
    client = _twilio_client()
    account_id = current_user["account_id"]
    if _active_number(db, account_id):
        raise HTTPException(status_code=409, detail="This account already has a tracking number")
    forward_to = _validated_forward_to(payload.forward_to)
    try:
        auto_reply_body = call_setup_logic.clean_auto_reply_body(payload.auto_reply_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    base_url = _api_base_url(request)
    purchased = None
    last_error: Exception | None = None
    searched: list[str] = []

    for area_code in call_setup_logic.search_area_codes(payload.forward_to, payload.area_code):
        searched.append(area_code or "any")
        try:
            found = client.available_phone_numbers("US").local.list(
                area_code=int(area_code) if area_code else None,
                voice_enabled=True,
                # Outbound texts and the inbound-SMS webhook both hang off this
                # number, so a voice-only one can't do two-way texting.
                sms_enabled=True,
                limit=call_setup_logic.CANDIDATE_LIMIT,
            )
        except Exception as exc:
            last_error = exc
            log.warning("Twilio number search failed for area code %s: %s", area_code, exc)
            continue

        for candidate in found:
            try:
                purchased = _buy_number(client, candidate.phone_number, base_url)
                break
            except Exception as exc:
                # Almost always "someone bought it first" — move to the next.
                last_error = exc
                log.info("Tracking number %s unavailable, trying the next: %s",
                         candidate.phone_number, exc)
        if purchased:
            break

    if not purchased:
        detail = (f"No tracking number could be provisioned (tried area code(s): "
                  f"{', '.join(searched)})")
        if last_error:
            detail += f" — {last_error}"
        log.warning("Call-tracking activation failed for account %s: %s", account_id, detail)
        raise HTTPException(status_code=502, detail=detail)

    _record_number(db, client, account_id, purchased, forward_to)
    log.info("Account %s activated call tracking on %s → %s",
             account_id, purchased.phone_number, forward_to)

    auto_reply = _auto_reply_state(db, account_id)
    if payload.auto_reply:
        # Best-effort: the number is bought, wired and forwarding by now. A
        # failure here costs an auto-text the owner can switch on from settings,
        # and must not read as "activation failed".
        try:
            auto_reply = _enable_auto_reply(db, account_id, current_user["id"],
                                            body=auto_reply_body)
        except Exception:
            db.rollback()
            log.exception("Auto-reply setup failed for account %s (number is live)", account_id)

    return {
        "ok": True,
        "number": _active_number(db, account_id),
        "auto_reply": auto_reply,
    }


@router.post("/calls/numbers")
def purchase_number(
    payload: NumberPurchase,
    request: Request,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    client = _twilio_client()
    account_id = current_user["account_id"]
    if _active_number(db, account_id):
        raise HTTPException(status_code=409, detail="This account already has a tracking number")
    forward_to = _validated_forward_to(payload.forward_to) if payload.forward_to else None

    try:
        purchased = _buy_number(client, payload.phone_number, _api_base_url(request))
    except Exception as exc:
        log.warning("Twilio number purchase failed for account %s: %s", account_id, exc)
        raise HTTPException(status_code=502, detail=f"Twilio could not purchase that number: {exc}")

    _record_number(db, client, account_id, purchased, forward_to)
    log.info("Account %s purchased tracking number %s", account_id, purchased.phone_number)
    return {"ok": True, "number": _active_number(db, account_id)}


@router.delete("/calls/numbers/{number_id}")
def release_number(
    number_id: int,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    client = _twilio_client()
    with db.cursor() as cur:
        cur.execute(
            "SELECT twilio_sid FROM tracking_numbers "
            "WHERE id = %s AND account_id = %s AND status = 'active'",
            (number_id, current_user["account_id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tracking number not found")

    try:
        client.incoming_phone_numbers(row[0]).delete()
    except Exception as exc:
        # Already gone in Twilio (released via console) is fine — still mark
        # released locally so the webhook stops resolving it.
        log.warning("Twilio release of %s reported: %s", row[0], exc)

    with db.cursor() as cur:
        cur.execute(
            "UPDATE tracking_numbers SET status = 'released', released_at = NOW() "
            "WHERE id = %s AND account_id = %s",
            (number_id, current_user["account_id"]),
        )
        db.commit()
    return {"ok": True}


@router.get("/calls")
def list_calls(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    outcome: str | None = Query(None, pattern="^(answered|missed|busy|no_answer|failed|canceled)$"),
    direction: str | None = Query(None, pattern="^(inbound|outbound)$"),
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    account_id = current_user["account_id"]
    where = "c.account_id = %(account_id)s"
    params: dict = {"account_id": account_id, "limit": limit, "offset": offset}
    if outcome:
        where += " AND c.outcome = %(outcome)s"
        params["outcome"] = outcome
    if direction:
        where += " AND c.direction = %(direction)s"
        params["direction"] = direction

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM calls c WHERE {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT c.id, c.property_id, c.direction, c.from_number, c.from_digits, "
            "       c.to_number, c.caller_name, c.status, c.outcome, c.disposition, "
            "       c.duration_seconds, c.lead_created, c.started_at, "
            "       p.contact_name "
            "FROM calls c LEFT JOIN properties p ON p.id = c.property_id "
            f"WHERE {where} "
            "ORDER BY c.started_at DESC "
            "LIMIT %(limit)s OFFSET %(offset)s",
            params,
        )
        items = dict_fetchall(cur)
    return {"items": items, "total": total}
