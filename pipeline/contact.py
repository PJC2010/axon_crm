"""
Step — Contact / skip-trace enrichment.

Fills contact_name / contact_phone / contact_email by matching a property's
owner_name + address against a skip-trace provider. Provider-pluggable: set
CONTACT_PROVIDER + CONTACT_API_KEY in the environment. With no provider
configured the step is a no-op (and reports skipped_no_key) so the rest of the
pipeline is unaffected.

Cost controls: only rows that already have an owner_name are processed (a
skip-trace needs an identity), capped at CONTACT_MAX_ROWS_PER_ZIP, and
optionally gated to leads at/above CONTACT_MIN_GRADE.

Adding a provider = add a normalizer to PROVIDERS that maps the provider's
response to {"contact_name", "contact_phone", "contact_email"}.
"""
import logging
import time

from config import (
    CONTACT_PROVIDER, CONTACT_API_KEY, CONTACT_BASE_URL,
    CONTACT_MAX_ROWS_PER_ZIP, CONTACT_MIN_GRADE,
)
from pipeline.db import get_conn, fetch_missing_field, upsert_properties
from pipeline.http import get_json

log = logging.getLogger(__name__)

# Grade ordering for the optional min-grade gate (A best).
_GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}


def _batchdata_lookup(row: dict) -> dict | None:
    """Skip-trace via a BatchData-style property/owner endpoint.

    Mapping is intentionally defensive: providers differ, so adjust the response
    paths here for whichever provider you point CONTACT_BASE_URL at.
    """
    payload = get_json(
        CONTACT_BASE_URL,
        headers={"Authorization": f"Bearer {CONTACT_API_KEY}",
                 "Accept": "application/json"},
        params={
            "name": row.get("owner_name", ""),
            "address": row.get("address", ""),
            "city": row.get("city", ""),
            "state": row.get("state", ""),
            "zip": row.get("zip", ""),
        },
        timeout=15,
    )
    if not payload:
        return None
    person = (payload.get("person") or payload.get("result") or payload) or {}
    phones = person.get("phones") or person.get("phoneNumbers") or []
    emails = person.get("emails") or person.get("emailAddresses") or []
    phone = phones[0] if isinstance(phones, list) and phones else person.get("phone")
    email = emails[0] if isinstance(emails, list) and emails else person.get("email")
    if isinstance(phone, dict):
        phone = phone.get("number")
    if isinstance(email, dict):
        email = email.get("address")
    name = person.get("name") or row.get("owner_name")
    if not (phone or email):
        return None
    return {
        "contact_name":  name,
        "contact_phone": phone,
        "contact_email": email,
    }


# provider name → lookup function
PROVIDERS = {
    "batchdata": _batchdata_lookup,
    # "endato": _endato_lookup,   # add more providers here
}


def _passes_grade(row: dict) -> bool:
    if not CONTACT_MIN_GRADE:
        return True
    return _GRADE_RANK.get(row.get("score_grade"), 0) >= _GRADE_RANK.get(CONTACT_MIN_GRADE, 0)


def enrich_contact(zip_code: str | None = None, selected_only: bool = False) -> dict:
    """Skip-trace owners missing a phone. Returns a source counter dict.

    When `selected_only` is True (capped/radius runs), only rows the selection
    step kept (enrichment_selected = TRUE) are skip-traced.
    """
    counter = {"ok": 0, "fail": 0, "updated": 0, "skipped_no_key": False}

    lookup = PROVIDERS.get(CONTACT_PROVIDER)
    if not CONTACT_PROVIDER or not CONTACT_API_KEY or lookup is None:
        counter["skipped_no_key"] = True
        if CONTACT_PROVIDER and lookup is None:
            log.warning("Unknown CONTACT_PROVIDER %r — skipping contact enrichment.",
                        CONTACT_PROVIDER)
        else:
            log.info("Contact provider not configured — skipping contact enrichment.")
        return counter

    conn = get_conn()
    try:
        rows = fetch_missing_field(conn, "contact_phone", zip_code,
                                   selected_only=selected_only)
        # Need an identity to skip-trace, and respect optional grade gate.
        rows = [r for r in rows if r.get("owner_name") and _passes_grade(r)]
        rows = rows[:CONTACT_MAX_ROWS_PER_ZIP]
        if not rows:
            return counter

        log.info("Contact enriching %d properties via %s…", len(rows), CONTACT_PROVIDER)
        updates = []
        for row in rows:
            data = lookup(row)
            if data:
                counter["ok"] += 1
                data.update({"address": row["address"], "zip": row["zip"],
                             "enrichment_flags": {"contact": CONTACT_PROVIDER}})
                updates.append(data)
            else:
                counter["fail"] += 1
            time.sleep(0.1)
        counter["updated"] = upsert_properties(conn, updates)
    finally:
        conn.close()
    return counter
