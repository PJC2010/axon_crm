"""Pure SMS helpers: sender normalization and Twilio error translation.

DB- and network-free so it unit-tests without credentials (tests/test_sms_logic.py),
following the same pure-logic split as api/messaging.py and api/invoice_logic.py.

Two jobs, both aimed at the same failure mode — a sender number Twilio won't
accept:

1. ``normalize_sender`` turns a loosely-written env var ("(346) 601-6971",
   "3466016971", a value pasted with quotes) into the E.164 Twilio requires,
   so a formatting slip never reads as an ownership problem.
2. ``describe_send_failure`` turns Twilio's terse REST error into a sentence
   that names the actual misconfiguration. Twilio 21659 in particular ("not a
   Twilio phone number or Short Code country mismatch") means the *credentials
   and the number belong to different Twilio projects* — nothing about the
   message is wrong, so the raw text sends people hunting in the wrong place.
"""

# A Messaging Service SID is a valid sender, but it goes in ``messaging_service_sid``
# rather than ``from_`` — sending through a service is what A2P 10DLC campaign
# registration (migration 0064) actually attaches to.
MESSAGING_SERVICE_PREFIX = "MG"


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def is_messaging_service(sender: str | None) -> bool:
    """Whether the sender is a Twilio Messaging Service SID (MG + 32 hex)."""
    s = (sender or "").strip()
    return len(s) == 34 and s.startswith(MESSAGING_SERVICE_PREFIX)


def normalize_sender(raw: str | None) -> str:
    """A Twilio-acceptable sender from however it was written in config.

    US 10-digit and 1-prefixed 11-digit numbers become E.164; Messaging Service
    SIDs, short codes and alphanumeric sender IDs pass through untouched. An
    empty/blank value returns "" so callers can treat it as "not configured".
    """
    s = (raw or "").strip().strip("\"'").strip()
    if not s:
        return ""
    if is_messaging_service(s):
        return s
    if any(ch.isalpha() for ch in s):
        return s  # alphanumeric sender ID — not ours to reformat
    digits = _digits(s)
    if not digits:
        return s
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if not s.startswith("+") and len(digits) <= 8:
        return digits  # short code — carries no country prefix
    return f"+{digits}"


def normalize_recipient(raw: str | None) -> str:
    """E.164 for a US destination number; anything else is passed through.

    Contact phones arrive from CSV imports and skip-trace vendors in every
    format going ("(713) 555-0142", "713-555-0142"), and Twilio rejects those.
    """
    s = (raw or "").strip()
    if not s or any(ch.isalpha() for ch in s):
        return s
    digits = _digits(s)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if s.startswith("+") and digits:
        return f"+{digits}"
    return s


# Twilio error code → what is actually wrong, in terms of this app's config.
# {sender} is filled with the sender we tried. Codes:
# twilio.com/docs/api/errors
_ERROR_HINTS: dict[int, str] = {
    20003: (
        "Twilio rejected the credentials themselves. TWILIO_ACCOUNT_SID / "
        "TWILIO_AUTH_TOKEN are wrong, rotated, or belong to a different Twilio project."
    ),
    21212: (
        "Twilio could not parse {sender} as a sender. TWILIO_FROM_NUMBER must be "
        "E.164 (+1 then 10 digits), a short code, or a Messaging Service SID (MG…)."
    ),
    21606: (
        "{sender} exists but is not SMS-capable on this Twilio project — it is "
        "voice-only, or it is not a number this Account SID owns. Check Phone "
        "Numbers → Manage → Active numbers and confirm the SMS capability is on."
    ),
    21608: (
        "This is a Twilio trial project: it can only text verified numbers. "
        "Verify the recipient in the console, or upgrade the project."
    ),
    21610: (
        "The recipient replied STOP to {sender} and is unsubscribed. Only their "
        "START/UNSTOP reply can re-open the thread — Twilio blocks sends until then."
    ),
    21611: "{sender} has exceeded its Twilio queue limit; the send was throttled.",
    21612: (
        "Twilio cannot route from {sender} to that destination — the number is "
        "not reachable from this sender (often a landline or an unsupported country)."
    ),
    21614: "The destination is not a valid mobile number and cannot receive SMS.",
    21659: (
        "{sender} is not a phone number on the Twilio project that "
        "TWILIO_ACCOUNT_SID identifies. Either TWILIO_FROM_NUMBER names a number "
        "bought under a different project/subaccount (or since released), or the "
        "SID/auth-token pair points at the wrong project. Open Phone Numbers → "
        "Manage → Active numbers while signed into that exact Account SID: the "
        "sender must appear in that list."
    ),
    21660: (
        "{sender} is inbound-only on this project and cannot originate messages."
    ),
    30034: (
        "{sender} is an unregistered 10DLC long code. US A2P traffic needs the "
        "number attached to a registered campaign — register it and send through "
        "the campaign's Messaging Service."
    ),
}

# Codes that mean "the sender is the problem" — the diagnostics endpoint uses
# this to decide whether to point the operator at their number config.
SENDER_ERROR_CODES = frozenset({21212, 21606, 21659, 21660, 30034})


def twilio_error_code(exc: BaseException) -> int | None:
    """Twilio's numeric error code, when the exception carries one."""
    code = getattr(exc, "code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def twilio_error_hint(exc: BaseException, *, sender: str = "") -> str | None:
    """An operator-readable cause for a Twilio failure, or None if unmapped."""
    code = twilio_error_code(exc)
    if code is None:
        return None
    hint = _ERROR_HINTS.get(code)
    return hint.format(sender=sender or "the sender number") if hint else None


def describe_send_failure(exc: BaseException, *, sender: str = "") -> str:
    """The message an SMS send failure should surface to the caller.

    Keeps Twilio's own wording (it names the offending value) and appends what
    that error means for this deployment's configuration when we know.
    """
    base = str(exc).strip() or exc.__class__.__name__
    hint = twilio_error_hint(exc, sender=sender)
    return f"{base} — {hint}" if hint else base
