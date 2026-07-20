"""
Call-tracking management (the `calls` module's authenticated half — the
webhooks live in api/routes/twilio_voice.py and stay public).

Endpoints:
  GET    /calls/settings            — tracking number + forwarding config
  PATCH  /calls/settings            — set the forwarding destination
  GET    /calls/numbers/available   — search purchasable local numbers
  POST   /calls/numbers             — buy a number (owner-only, one per account)
  DELETE /calls/numbers/{number_id} — release the number (owner-only)
  GET    /calls                     — account-wide call log

The whole router is gated on the `calls` module in api/main.py. Twilio's REST
client is lazy-imported inside handlers (same as api/notifications.py) so the
API runs fine without the dependency exercised; when TWILIO_* is unset the
number endpoints 503 and GET /calls/settings reports configured=false so the
frontend shows a setup-required state instead of erroring.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
from api.deps import get_db, get_current_user, require_owner, dict_fetchall, dict_fetchone
from api.routes.twilio_inbound import normalize_phone
from api.routes.twilio_voice import voice_configured, _api_base_url

log = logging.getLogger(__name__)

router = APIRouter()


class CallSettingsUpdate(BaseModel):
    forward_to: str


class NumberPurchase(BaseModel):
    phone_number: str          # E.164 from the availability search
    forward_to: str | None = None  # optionally set the destination in one step


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


@router.get("/calls/settings")
def get_call_settings(
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    return {
        "configured": voice_configured(),
        "number": _active_number(db, current_user["account_id"]),
    }


@router.patch("/calls/settings")
def update_call_settings(
    payload: CallSettingsUpdate,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    forward_to = _validated_forward_to(payload.forward_to)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE tracking_numbers SET forward_to = %s "
            "WHERE account_id = %s AND status = 'active' RETURNING id",
            (forward_to, current_user["account_id"]),
        )
        updated = cur.fetchone()
        db.commit()
    if not updated:
        raise HTTPException(status_code=404, detail="No active tracking number to configure")
    return {"ok": True, "number": _active_number(db, current_user["account_id"])}


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

    base_url = _api_base_url(request)
    try:
        purchased = client.incoming_phone_numbers.create(
            phone_number=payload.phone_number,
            voice_url=f"{base_url}/api/public/twilio/voice",
            voice_method="POST",
            # Texts to the tracking number thread into the same tenant-scoped
            # inbound-SMS webhook (unknown senders become leads there too).
            sms_url=f"{base_url}/api/public/twilio/sms",
            sms_method="POST",
        )
    except Exception as exc:
        log.warning("Twilio number purchase failed for account %s: %s", account_id, exc)
        raise HTTPException(status_code=502, detail=f"Twilio could not purchase that number: {exc}")

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
        # Real money was spent; don't strand a number we failed to record.
        db.rollback()
        log.exception("Recording purchased number %s failed; releasing it", purchased.sid)
        try:
            client.incoming_phone_numbers(purchased.sid).delete()
        except Exception:
            log.exception("Release of stranded number %s also failed — release it in the Twilio console", purchased.sid)
        raise HTTPException(status_code=500, detail="Purchase could not be recorded; the number was released")

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
    outcome: str | None = Query(None, pattern="^(answered|missed|busy)$"),
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    account_id = current_user["account_id"]
    where = "c.account_id = %(account_id)s"
    params: dict = {"account_id": account_id, "limit": limit, "offset": offset}
    if outcome:
        where += " AND c.outcome = %(outcome)s"
        params["outcome"] = outcome

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM calls c WHERE {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT c.id, c.property_id, c.from_number, c.from_digits, c.caller_name, "
            "       c.status, c.outcome, c.duration_seconds, c.lead_created, c.started_at, "
            "       p.contact_name "
            "FROM calls c LEFT JOIN properties p ON p.id = c.property_id "
            f"WHERE {where} "
            "ORDER BY c.started_at DESC "
            "LIMIT %(limit)s OFFSET %(offset)s",
            params,
        )
        items = dict_fetchall(cur)
    return {"items": items, "total": total}
