"""Message templates — merge-field rendering for contact-level messaging.

Pure, DB-free so it's unit-testable. Templates use ``{{field}}`` placeholders;
only the known merge fields below are substituted (unknown placeholders are left
untouched rather than blanked, so a stray brace never silently eats text).
"""
import re

# Merge fields a template may reference, resolved from the record + account.
MERGE_FIELDS = ("contact_name", "first_name", "address", "owner_name", "business_name")

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def build_context(record: dict, business_name: str | None) -> dict[str, str]:
    """Merge-field values for a record. Missing values render as empty strings."""
    contact_name = (record.get("contact_name") or "").strip()
    first_name = contact_name.split()[0] if contact_name else ""
    return {
        "contact_name": contact_name,
        "first_name": first_name,
        "address": record.get("address") or "",
        "owner_name": record.get("owner_name") or "",
        "business_name": business_name or "",
    }


def render_template(text: str | None, context: dict[str, str]) -> str:
    """Substitute known ``{{field}}`` placeholders; leave unknown ones as-is."""
    if not text:
        return ""

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return context.get(key, match.group(0)) if key in MERGE_FIELDS else match.group(0)

    return _PLACEHOLDER.sub(_sub, text)


def recipient_for_channel(record: dict, channel: str) -> str | None:
    """The record's contact address for a channel, or None if it has none."""
    if channel == "sms":
        return record.get("contact_phone")
    return record.get("contact_email")
