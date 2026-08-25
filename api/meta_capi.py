"""
Meta Conversions API (CAPI) — server-side conversion emitter.

The browser Pixel (frontend/components/MetaPixel.tsx) can only report what a
loaded page can see. The conversions that decide the ad strategy — above all the
trial→paid **Subscribe**, which happens on a Stripe webhook with no browser in
the loop — have to come from the server. This module is that path.

Design mirrors the other best-effort side-effect emitters (api/auth_events.py,
the lead_events hooks):

  * **Best-effort.** Every public function swallows its own errors and returns a
    bool. A tracking failure — misconfig, Meta 5xx, network — must never break
    the host request (a subscription webhook, a signup). Measurement is a
    side effect, never a gate.
  * **Self-gating.** With META_PIXEL_ID / META_CAPI_TOKEN unset, every emit is a
    silent no-op — same "missing key = feature skipped" convention as the Pixel
    tag and the GA helpers.
  * **Dedup-ready.** Callers pass a deterministic event_id; when the browser
    Pixel fires the same logical event it uses the same id, and Meta keeps one.
    A deterministic id (e.g. the Stripe subscription id) is also idempotent
    across webhook retries.

Match keys drive Event Match Quality (EMQ); Meta hashes-then-matches, so we send
SHA-256 of normalized PII (email/phone/zip/external_id) and raw fbp/fbc/ip/ua.
More keys present = higher EMQ = lower CPA.

Pure stdlib (urllib) on purpose — no new dependency, and the payload is small.

Lives at api/ top level rather than in the old api/connectors/ package: that
package existed for the Meta *export parsers*, which were removed for good in
a3e3e3a. CAPI is an outbound event emitter, not an import connector.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request

from config import (
    APP_BASE_URL,
    META_CAPI_API_VERSION,
    META_CAPI_TOKEN,
    META_PIXEL_ID,
    META_TEST_EVENT_CODE,
)

log = logging.getLogger(__name__)

CURRENCY = "USD"
_TIMEOUT = 10  # seconds; measurement must never hang a request for long


def capi_configured() -> bool:
    """True when server-side conversions can actually be sent."""
    return bool(META_PIXEL_ID and META_CAPI_TOKEN)


# ── Normalize + hash (Meta advanced-matching spec) ────────────────────────────

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hashed(value: str | None, *, digits_only: bool = False, first5: bool = False) -> list[str] | None:
    if not value:
        return None
    norm = value.strip().lower()
    if digits_only:
        norm = "".join(ch for ch in value if ch.isdigit())
    if first5:
        norm = norm[:5]
    if not norm:
        return None
    return [_sha256(norm)]


def build_user_data(*, email: str | None = None, phone: str | None = None,
                    zip_code: str | None = None, external_id: str | None = None,
                    fbp: str | None = None, fbc: str | None = None,
                    client_ip: str | None = None, client_ua: str | None = None) -> dict:
    """Assemble a Meta user_data block. Every key present lifts EMQ."""
    ud: dict = {}
    for key, val in (
        ("em", _hashed(email)),
        ("ph", _hashed(phone, digits_only=True)),
        ("zp", _hashed(zip_code, first5=True)),
        ("external_id", _hashed(external_id)),
    ):
        if val:
            ud[key] = val
    # Not hashed: Meta matches these directly.
    for key, val in (("fbp", fbp), ("fbc", fbc),
                     ("client_ip_address", client_ip), ("client_user_agent", client_ua)):
        if val:
            ud[key] = val
    return ud


# ── Send ──────────────────────────────────────────────────────────────────────

def send_event(event_name: str, user_data: dict, *, event_id: str,
               action_source: str = "website", custom_data: dict | None = None,
               event_source_url: str | None = None) -> bool:
    """Post one event to the Conversions API. Best-effort: never raises."""
    if not capi_configured():
        return False
    if not user_data:
        # No match keys → EMQ 0 and an unusable event. Skip rather than pollute.
        log.warning("meta_capi: skipping %s with no match keys", event_name)
        return False

    event: dict = {
        "event_name": event_name,
        "event_time": int(time.time()),
        "action_source": action_source,
        "event_id": event_id,
        "user_data": user_data,
    }
    if event_source_url or action_source == "website":
        event["event_source_url"] = event_source_url or APP_BASE_URL
    if custom_data:
        event["custom_data"] = custom_data

    body: dict = {"data": [event], "access_token": META_CAPI_TOKEN}
    if META_TEST_EVENT_CODE:
        body["test_event_code"] = META_TEST_EVENT_CODE

    url = f"https://graph.facebook.com/{META_CAPI_API_VERSION}/{META_PIXEL_ID}/events"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            payload = json.load(resp)
        log.info("meta_capi: %s sent (received=%s, event_id=%s)",
                 event_name, payload.get("events_received"), event_id)
        return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        log.warning("meta_capi: %s rejected (HTTP %s): %s", event_name, exc.code, detail)
    except Exception:
        log.warning("meta_capi: %s send failed", event_name, exc_info=True)
    return False


# ── Event-ladder helpers ──────────────────────────────────────────────────────

def track_start_trial(*, email: str | None, external_id: str | None, event_id: str,
                      fbp: str | None = None, fbc: str | None = None,
                      client_ip: str | None = None, client_ua: str | None = None,
                      event_source_url: str | None = None) -> bool:
    """Self-serve signup = trial start (an Axon trial needs no card, so creating a
    workspace *is* StartTrial — the funnel event ads optimize toward before the
    paid Subscribe). Fired from the signup route so the event carries hashed
    email + external_id and the browser's fbp/fbc/ip/ua: the browser Pixel alone
    only has fbp/fbc, so this is where StartTrial's EMQ actually comes from. Shares
    `event_id` with the browser StartTrial (same value the client generates), so
    Meta dedups the pair into one. external_id is the account id — the same key
    track_subscribe uses, so Meta links this trial to its later paid conversion."""
    ud = build_user_data(email=email, external_id=external_id,
                         fbp=fbp, fbc=fbc, client_ip=client_ip, client_ua=client_ua)
    return send_event("StartTrial", ud, event_id=event_id,
                      custom_data={"content_name": "self_serve_signup",
                                 "currency": CURRENCY, "value": 0},
                      event_source_url=event_source_url)


def track_subscribe(*, email: str | None, value: float | int | None,
                    event_id: str, external_id: str | None = None) -> bool:
    """trial→paid conversion. Fired from the billing webhook so Meta optimizes on
    paying subscribers, not just leads. `value` is the plan's monthly price."""
    ud = build_user_data(email=email, external_id=external_id)
    custom = {"currency": CURRENCY, "content_name": "trial_to_paid"}
    if value is not None:
        custom["value"] = round(float(value), 2)
    return send_event("Subscribe", ud, event_id=event_id, custom_data=custom)
