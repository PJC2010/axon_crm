"""Pure call-tracking logic: TwiML builders, dial-outcome mapping, and the
shape of a lead auto-created from an unknown caller.

Dependency-free on purpose (no DB, no config, no twilio import) so it can be
unit-tested directly — same split as api/messaging.py and api/lead_logic.py.
The webhook routes in api/routes/twilio_voice.py are thin wrappers over this.
"""
from xml.sax.saxutils import escape, quoteattr

# DialCallStatus (Twilio's verdict on the forwarded leg) -> our call outcome.
# 'completed'/'answered' mean the business picked up; everything else — no
# answer, failed, canceled, or an unrecognized future value — is a missed call
# the owner should chase, except 'busy' which gets its own label.
_DIAL_STATUS_OUTCOMES = {
    "completed": "answered",
    "answered": "answered",
    "busy": "busy",
}


def build_dial_twiml(forward_to: str, action_url: str, timeout: int = 25) -> str:
    """TwiML that forwards the inbound call to the business's real phone.

    answerOnBridge keeps the caller hearing ringback (not silence) until the
    business picks up; the action URL receives DialCallStatus/DialCallDuration
    after the leg ends. No callerId attribute — Twilio then presents the
    original caller's number to the business phone.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Dial answerOnBridge="true" timeout="{int(timeout)}" '
        f'action={quoteattr(action_url)}>'
        f'<Number>{escape(forward_to)}</Number>'
        "</Dial></Response>"
    )


def build_hangup_twiml() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'


def build_unconfigured_twiml() -> str:
    """Played when a call reaches a number with no active forwarding target
    (e.g. released number, or forward_to never set). Polite dead end."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Say>This number is not currently in service. Goodbye.</Say>"
        "<Hangup/></Response>"
    )


def map_dial_status(dial_call_status: str | None) -> str:
    return _DIAL_STATUS_OUTCOMES.get((dial_call_status or "").strip().lower(), "missed")


def format_phone_display(digits: str) -> str:
    """(713) 555-0142 from a 10-digit string; anything else passes through."""
    if len(digits) == 10 and digits.isdigit():
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return digits


def new_lead_row(from_number: str, digits: str, caller_name: str | None = None,
                 *, channel: str = "call") -> dict:
    """Column -> value dict for a lead auto-created from an unknown caller
    (channel='call') or an unknown texter (channel='sms').

    status 'new' is the properties-table default vocabulary (migration 0000) —
    not public_intake's 'prospect', which is insurance-preset-specific. The
    caller's CNAM name is used when Twilio sent one; otherwise a recognizable
    placeholder built from the number.
    """
    name = (caller_name or "").strip() or f"Caller {format_phone_display(digits)}"
    return {
        "contact_name": name,
        "contact_phone": from_number,
        "status": "new",
        "lead_source": "inbound_call" if channel == "call" else "inbound_sms",
        "enrichment_flags": {"source": "call_tracking" if channel == "call" else "sms_tracking"},
    }


def format_duration(seconds: int | None) -> str:
    """'2m 14s' / '45s' — human-scale call length for history lines."""
    total = max(int(seconds or 0), 0)
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def history_action_for(outcome: str, duration_seconds: int | None) -> str:
    """The contact_history action line the timeline shows for a finished call."""
    if outcome == "answered":
        return f"Inbound call — answered ({format_duration(duration_seconds)})"
    if outcome == "busy":
        return "Missed call — line busy"
    return "Missed call"
