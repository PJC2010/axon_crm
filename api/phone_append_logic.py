"""
Pure logic for applying a reverse phone-append result to a lead.

No DB, no network — both callers of the reverse append (the inbound-call
webhook in api/routes/twilio_voice.py and the backfill sweep in
api/call_append_sweep.py) need the same "which columns may this fill?" rules,
and those rules are worth testing on their own (tests/test_phone_append_logic.py).

The rules, in one place:
  - only empty columns are filled — a human's edit always outranks the provider
  - contact_name additionally overwrites call_logic's "Caller ..." placeholder
  - line-type / compliance signals have no column, so they ride in
    enrichment_flags.phone_append_meta
  - enrichment_flags.phone_append is stamped after any *completed* attempt,
    match or no-match, because the provider charged for the query either way
"""

# Columns a reverse phone append may fill — never user-editable-only fields.
APPEND_FIELDS = ("address", "city", "state", "zip", "contact_email")

# Provider fields with no column of their own, kept as enrichment metadata.
META_FIELDS = ("phone_type", "phone_reachable", "phone_dnc", "litigator",
               "property_owner")

# call_logic.new_lead_row's placeholder name for an unknown caller.
_PLACEHOLDER_NAME_PREFIX = "Caller "


def merge_append(data: dict | None, current: dict) -> dict:
    """Column updates a phone-append result should write onto a lead.

    `current` is the lead's present values keyed by column name; a missing key
    is treated as empty. Returns only the columns that should change, so an
    empty dict means the row needs no UPDATE.
    """
    data = data or {}
    updates = {
        field: data[field] for field in APPEND_FIELDS
        if data.get(field) and not current.get(field)
    }
    name = data.get("contact_name")
    current_name = current.get("contact_name") or ""
    if name and (not current_name
                 or current_name.startswith(_PLACEHOLDER_NAME_PREFIX)):
        updates["contact_name"] = name
    return updates


def merge_flags(data: dict | None, current_flags: dict | None,
                provider: str) -> dict:
    """The lead's enrichment_flags after a completed append attempt.

    Stamps `phone_append` with the provider so a repeat caller never re-spends
    (the guard both callers read), and files any line-type/compliance signals
    under `phone_append_meta`. A no-match still stamps the provider — the query
    was billed. Never mutates the dict it was given.
    """
    flags = dict(current_flags or {})
    flags["phone_append"] = provider
    meta = {field: (data or {})[field] for field in META_FIELDS
            if (data or {}).get(field) is not None}
    if meta:
        flags["phone_append_meta"] = meta
    return flags
