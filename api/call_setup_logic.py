"""Pure logic for one-click call-tracking activation and the missed-call
auto-text it turns on.

Dependency-free (no DB, no config, no twilio import) so it unit-tests directly —
same split as api/call_logic.py, which owns the *runtime* half (TwiML, dial
outcomes). This module owns the *setup* half:

  * which area codes to shop for a tracking number, given the business line the
    owner typed in, and
  * the default missed-call auto-reply — its template name, its body, and the
    workflow-rule config that wires it to the `call_event` trigger.

The names below are the join key between the three rows activation creates
(a message_templates row, a workflow_rules row, and the tracking_numbers row).
api/routes/calls.py looks the first two up by name to report and toggle the
auto-text later, so renaming either constant orphans existing accounts' rows.
"""

# The message_templates row the auto-text sends, and the workflow_rules row that
# fires it. Looked up by (account_id, name) — message_templates has a UNIQUE on
# that pair (migration 0044); workflow_rules doesn't, so its lookup is also
# scoped by trigger_type.
AUTO_REPLY_TEMPLATE_NAME = "Missed call auto-reply"
AUTO_REPLY_RULE_NAME = "Missed call → auto-text the caller"

# Twilio truncates nothing, but a long auto-reply silently becomes several
# billed segments. 480 chars ≈ 3 GSM-7 segments — generous for a courtesy text
# and short enough that a paste accident can't cost real money.
AUTO_REPLY_MAX_CHARS = 480

# How many candidate numbers to pull per area code. Activation buys the first
# one Twilio accepts; the rest are only there so a number sold out from under
# the search doesn't fail the whole request.
CANDIDATE_LIMIT = 5


def area_code_of(phone: str | None) -> str:
    """The 3-digit area code of a US phone number, or '' when it isn't one.

    Works off the last 10 digits so +1-prefixed, punctuated, and bare 10-digit
    forms all agree — the same last-10 convention as
    api/routes/twilio_inbound.py::normalize_phone.
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) < 10:
        return ""
    return digits[-10:][:3]


def search_area_codes(forward_to: str | None, requested: str | None = None) -> list[str | None]:
    """Ordered area codes to shop for a tracking number, most-local first.

    A tracking number reads as local when it shares an area code with the
    business line the owner just typed in, so that's the default. An explicitly
    requested area code outranks it. The list always ends in ``None`` — "any US
    local number" — because activation must not dead-end when a single area code
    is sold out; a number in the wrong area code still tracks calls.
    """
    candidates: list[str | None] = []
    for value in (requested, area_code_of(forward_to)):
        code = (value or "").strip()
        if len(code) == 3 and code.isdigit() and code not in candidates:
            candidates.append(code)
    candidates.append(None)
    return candidates


def default_auto_reply_body(business_name: str | None) -> str:
    """The missed-call auto-text a freshly activated account starts with.

    ``{{business_name}}`` is left as a merge field rather than baked in, so
    renaming the account updates the text (api/messaging.py resolves it). It is
    dropped entirely when the account has no name — an empty merge field would
    leave "This is ." mid-sentence.

    Deliberately no ``{{first_name}}``: a lead auto-created from an unknown
    caller is named "Caller (713) 555-0142" (api/call_logic.py::new_lead_row),
    so the greeting would read "Hi Caller".
    """
    name = (business_name or "").strip()
    if name:
        return ("Sorry we missed your call! This is {{business_name}}. "
                "Reply to this text and we'll get right back to you.")
    return ("Sorry we missed your call! Reply to this text and we'll get "
            "right back to you.")


def clean_auto_reply_body(raw: str | None) -> str | None:
    """Normalize a user-supplied auto-reply body, or None when not being set.

    Returns None for None (the "leave it alone" signal on PATCH); raises
    ValueError for a body that is blank or too long, so the route can turn it
    into a 400 rather than storing a template that texts nothing.
    """
    if raw is None:
        return None
    body = raw.strip()
    if not body:
        raise ValueError("The auto-reply text can't be empty")
    if len(body) > AUTO_REPLY_MAX_CHARS:
        raise ValueError(
            f"Keep the auto-reply under {AUTO_REPLY_MAX_CHARS} characters "
            f"({len(body)} given) — longer texts bill as extra segments"
        )
    return body


def auto_reply_trigger_config() -> dict:
    """Fire on a missed call only. 'busy' is a separate outcome
    (api/call_logic.py::map_dial_status) and gets no auto-text: the line was
    engaged, so someone was already there."""
    return {"event": "missed"}


def auto_reply_action_config(template_id: int) -> dict:
    """Send the auto-reply template immediately.

    No ``delay_minutes``: the whole point is that the caller gets a reply while
    they still have the phone in their hand. The engine sends from the tracking
    number the caller dialed (the ``sms_from`` override in
    api/routes/twilio_voice.py::_fire_call_event), so the text arrives from the
    number already on their screen and their reply threads back to this tenant.
    """
    return {"template_id": int(template_id)}
