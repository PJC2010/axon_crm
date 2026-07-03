"""Message templates — merge-field rendering for contact-level messaging.

Pure, DB-free so it's unit-testable. Templates use ``{{field}}`` placeholders;
only the known merge fields below are substituted (unknown placeholders are left
untouched rather than blanked, so a stray brace never silently eats text).
"""
import re
from datetime import date, datetime

# Merge fields a template may reference, resolved from the record + account.
MERGE_FIELDS = ("contact_name", "first_name", "address", "owner_name", "business_name")

# Policy merge fields (renewal reminders): resolved from a policies row when the
# send carries one — a policy-expiration workflow firing or a per-policy manual
# send. Without a policy they render as empty strings, matching how missing
# record fields already behave.
POLICY_MERGE_FIELDS = ("policy_number", "carrier", "policy_type", "premium",
                       "effective_date", "expiration_date")

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _fmt_date(value) -> str:
    """Human date for message bodies ("July 15, 2026"). Accepts date/datetime
    or ISO strings (JSONB round-trips give strings)."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, (date, datetime)):
        return f"{value:%B} {value.day}, {value.year}"
    return str(value)


def _fmt_money(value) -> str:
    if value is None:
        return ""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def build_context(record: dict, business_name: str | None,
                  policy: dict | None = None) -> dict[str, str]:
    """Merge-field values for a record. Missing values render as empty strings.

    ``policy`` (a policies row) adds the POLICY_MERGE_FIELDS with dates and
    premium formatted for prose; without it they resolve to empty strings so a
    policy template sent without policy context degrades rather than leaking
    raw ``{{placeholders}}``.
    """
    contact_name = (record.get("contact_name") or "").strip()
    first_name = contact_name.split()[0] if contact_name else ""
    ctx = {
        "contact_name": contact_name,
        "first_name": first_name,
        "address": record.get("address") or "",
        "owner_name": record.get("owner_name") or "",
        "business_name": business_name or "",
    }
    policy = policy or {}
    ctx.update({
        "policy_number": policy.get("policy_number") or "",
        "carrier": policy.get("carrier") or "",
        "policy_type": policy.get("policy_type") or "",
        "premium": _fmt_money(policy.get("premium")),
        "effective_date": _fmt_date(policy.get("effective_date")),
        "expiration_date": _fmt_date(policy.get("expiration_date")),
    })
    return ctx


_ALL_FIELDS = frozenset(MERGE_FIELDS) | frozenset(POLICY_MERGE_FIELDS)


def render_template(text: str | None, context: dict[str, str]) -> str:
    """Substitute known ``{{field}}`` placeholders; leave unknown ones as-is."""
    if not text:
        return ""

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return context.get(key, match.group(0)) if key in _ALL_FIELDS else match.group(0)

    return _PLACEHOLDER.sub(_sub, text)


def recipient_for_channel(record: dict, channel: str) -> str | None:
    """The record's contact address for a channel, or None if it has none."""
    if channel == "sms":
        return record.get("contact_phone")
    return record.get("contact_email")


# Delivery modes for multi-channel template sends (send_template workflow
# action). "single" is the legacy one-template shape.
DELIVERY_MODES = ("sms_first", "email_first", "both")


def channel_order(delivery: str) -> tuple[list[str], bool]:
    """(channels in priority order, send_all) for a delivery mode.

    send_all=True means attempt every channel ("both"); False means stop after
    the first successful send (fallback semantics).
    """
    if delivery == "email_first":
        return ["email", "sms"], False
    if delivery == "both":
        return ["sms", "email"], True
    # default / "sms_first"
    return ["sms", "email"], False
