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

The reverse lookup (caller phone → name/address/email) used by the inbound-call
webhook in api/routes/twilio_voice.py also lives here — versium_phone_append,
configured separately via PHONE_APPEND_PROVIDER/PHONE_APPEND_API_KEY.
"""
import logging
import re
import time

from config import (
    CONTACT_PROVIDER, CONTACT_API_KEY, CONTACT_BASE_URL,
    CONTACT_MAX_ROWS_PER_ZIP, CONTACT_MIN_GRADE,
    PHONE_APPEND_PROVIDER, PHONE_APPEND_API_KEY, PHONE_APPEND_BASE_URL,
)
from pipeline.db import get_conn, fetch_missing_field, upsert_properties
from pipeline.http import get_json, post_json

log = logging.getLogger(__name__)

# Grade ordering for the optional min-grade gate (A best).
_GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}

# Default Versium Contact Append endpoint — overridable via CONTACT_BASE_URL.
_VERSIUM_CONTACT_URL = "https://api.versium.com/v2/contact"

# Default BatchData Skip Trace endpoint — overridable via CONTACT_BASE_URL.
_BATCHDATA_SKIPTRACE_URL = "https://api.batchdata.com/api/v1/property/skip-trace"


def _batchdata_lookup(row: dict) -> dict | None:
    """Skip-trace via BatchData's Property Skip Trace API.

    POSTs the property address (+ owner name when parseable) and reads the
    first person match's phone/email back out. Response parsing is defensive —
    BatchData nests results under results.persons[] with phoneNumbers[]/emails[].
    """
    url = CONTACT_BASE_URL or _BATCHDATA_SKIPTRACE_URL

    # BatchData matches on the property address; a structured first/last name
    # (when the county owner_name is a parseable person) sharpens the match.
    request: dict = {
        "propertyAddress": {
            "street": row.get("address", ""),
            "city":   row.get("city", ""),
            "state":  row.get("state", ""),
            "zip":    row.get("zip", ""),
        }
    }
    candidates = _owner_name_candidates(row.get("owner_name", ""))
    if candidates:
        first, last = candidates[0]
        request["name"] = {"first": first, "last": last}

    payload = post_json(
        url,
        json={"requests": [request]},
        headers={
            "Authorization": f"Bearer {CONTACT_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=20,
    )
    if not payload:
        return None

    # results.persons[] is the documented shape; fall back gracefully if the
    # account returns a flatter structure.
    results = payload.get("results") or payload
    persons = results.get("persons") or results.get("person") or []
    if isinstance(persons, dict):
        persons = [persons]
    if not persons:
        return None
    person = persons[0]

    phones = person.get("phoneNumbers") or person.get("phones") or []
    emails = person.get("emails") or person.get("emailAddresses") or []
    phone = _first_value(phones[0], ("number", "phone", "value")) if isinstance(phones, list) and phones and isinstance(phones[0], dict) \
        else (phones[0] if isinstance(phones, list) and phones else person.get("phone"))
    email = _first_value(emails[0], ("email", "address", "value")) if isinstance(emails, list) and emails and isinstance(emails[0], dict) \
        else (emails[0] if isinstance(emails, list) and emails else person.get("email"))

    name = person.get("name")
    if isinstance(name, dict):
        name = name.get("full") or _full_name(name.get("first"), name.get("last"))
    name = name or row.get("owner_name")

    if not (phone or email):
        return None
    return {
        "contact_name":  name,
        "contact_phone": phone,
        "contact_email": email,
    }


def _versium_lookup(row: dict) -> dict | None:
    """Skip-trace via the Versium Contact Append API.

    Input: owner_name (split into first/last) + address fields.
    Output: {"contact_name", "contact_phone", "contact_email"} or None.

    Response parsing is intentionally defensive — Versium field names vary across
    API versions (spaces vs underscores, numbered keys like "Phone 1"). We
    normalise keys to lowercase+underscore, then pick the first phone/email found.
    """
    # County owner names are messy (multi-owner, business entities, Last-First
    # order). Build the ordered (first, last) candidates to try.
    candidates = _owner_name_candidates(row.get("owner_name", ""))
    if not candidates:
        return None  # business entity or unparseable — no consumer to skip-trace

    # Try each candidate ordering until one matches. The swapped ordering only
    # costs an extra call when the first ordering misses.
    for first, last in candidates:
        data = _versium_query(first, last, row)
        if data:
            return data
    return None


def _versium_query(first: str, last: str, row: dict) -> dict | None:
    """One Versium Contact Append call for a given first/last name."""
    url = CONTACT_BASE_URL or _VERSIUM_CONTACT_URL
    resp = get_json(
        url,
        headers={
            "x-versium-api-key": CONTACT_API_KEY,
            "Accept": "application/json",
        },
        params={
            # output[] is mandatory — it selects which contact fields to append.
            # (Only one phone type per query: phone_mobile here.)
            "output[]": ["phone_mobile", "email"],
            "first":   first,
            "last":    last,
            "address": row.get("address", ""),
            "city":    row.get("city", ""),
            "state":   row.get("state", ""),
            "zip":     row.get("zip", ""),
        },
        timeout=15,
    )
    if not resp:
        return None

    # Versium may return one result per matched contact; scan all and take the
    # first with a phone/email rather than assuming the first record has both.
    results = resp.get("versium", {}).get("results") or resp.get("results") or []
    if isinstance(results, dict):
        results = [results]
    phone = email = matched_name = None
    for raw in results:
        # Normalise keys: "Email Address" → "email_address", "Mobile Phone" → "mobile_phone".
        p = {re.sub(r"[\s/]+", "_", k).lower(): v for k, v in raw.items()}
        phone = phone or _first_value(p, (
            "mobile_phone", "phone_mobile", "phone", "phone_1", "phones",
            "phone_number", "mobile",
        ))
        email = email or _first_value(p, (
            "email", "email_1", "email_address", "email_address_1", "emails",
        ))
        # Prefer Versium's own normalised name from the matched record.
        matched_name = matched_name or _full_name(
            _str(p.get("first_name")), _str(p.get("last_name")))
        if phone and email:
            break

    if not (phone or email):
        return None
    # Store the cleaned, matched name — fall back to the queried name, then the
    # raw owner_name, so contact_name is never blank.
    name = matched_name or _full_name(first.capitalize(), last.capitalize()) \
        or row.get("owner_name")
    return {
        "contact_name":  name,
        "contact_phone": phone,
        "contact_email": email,
    }


def versium_phone_append(phone_digits: str) -> dict | None:
    """Reverse append: a caller's phone number → name/address/email.

    The inverse of _versium_lookup — used by the inbound-call webhook to turn an
    unknown caller into a lead with an address. Configured independently of the
    forward skip-trace via PHONE_APPEND_PROVIDER/PHONE_APPEND_API_KEY, so the two
    directions can run on different providers. One GET with a tight timeout and
    no retries: it runs inside Twilio's 15s webhook window, so latency matters
    more than resilience. Returns only the non-empty fields among
    {"contact_name", "contact_email", "address", "city", "state", "zip"},
    or None when unconfigured or nothing usable came back.
    """
    digits = (phone_digits or "").strip()
    if PHONE_APPEND_PROVIDER != "versium" or not PHONE_APPEND_API_KEY \
            or len(digits) != 10:
        return None

    url = PHONE_APPEND_BASE_URL or _VERSIUM_CONTACT_URL
    resp = get_json(
        url,
        headers={
            "x-versium-api-key": PHONE_APPEND_API_KEY,
            "Accept": "application/json",
        },
        params={
            # Address is the point of the call; email rides along in the same
            # query (Versium's own docs pair them). Only one phone-type output
            # is allowed per query, and here the phone is the input.
            "output[]": ["address", "email"],
            "phone": digits,
        },
        timeout=8,
        retries=0,
    )
    if not resp:
        return None

    results = resp.get("versium", {}).get("results") or resp.get("results") or []
    if isinstance(results, dict):
        results = [results]

    # Scan every matched record and keep the first non-empty value per field,
    # same defensive normalisation as _versium_query ("First Name" → first_name).
    out: dict = {}
    for raw in results:
        p = {re.sub(r"[\s/]+", "_", k).lower(): v for k, v in raw.items()}
        out.setdefault("contact_name", _full_name(
            _str(p.get("first_name")), _str(p.get("last_name"))))
        out.setdefault("contact_email", _first_value(p, (
            "email", "email_1", "email_address", "email_address_1", "emails",
        )))
        out.setdefault("address", _first_value(p, (
            "address", "address_1", "street", "street_address",
        )))
        out.setdefault("city", _str(p.get("city")))
        out.setdefault("state", _str(p.get("state")))
        out.setdefault("zip", _first_value(p, ("zip", "zip_code", "postal_code")))
        # Drop the Nones setdefault leaves behind on later records.
        out = {k: v for k, v in out.items() if v}
        if {"address", "city", "state", "zip"} <= out.keys():
            break
    return out or None


def _full_name(first: str | None, last: str | None) -> str | None:
    """Join first/last into a display name, ignoring blanks."""
    parts = [p for p in (first, last) if p]
    return " ".join(parts) or None


# provider name → lookup function
PROVIDERS = {
    "batchdata": _batchdata_lookup,
    "versium": _versium_lookup,
    # "endato": _endato_lookup,   # add more providers here
}


# Tokens that mark an owner_name as a business/trust rather than a person.
_BUSINESS_TOKENS = {
    "LLC", "LLLP", "INC", "CORP", "CO", "COMPANY", "LP", "LLP", "LTD",
    "TRUST", "TR", "TRUSTEE", "TTEE", "ESTATE", "EST", "REALTY", "PROPERTIES",
    "PROPERTY", "HOLDINGS", "INVESTMENTS", "INVESTMENT", "ENTERPRISES", "GROUP",
    "PARTNERS", "PARTNERSHIP", "ASSOCIATION", "ASSOC", "ASSN", "CHURCH", "BANK",
    "FUND", "MANAGEMENT", "MGMT", "HOMES", "DEVELOPMENT", "FOUNDATION",
    "MINISTRIES", "SERVICES", "RENTALS", "CITY", "COUNTY", "AUTHORITY", "DISTRICT",
}

# Generational suffixes and honorifics to strip from a person's name.
_NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}
_NAME_TITLES = {"MR", "MRS", "MS", "DR", "REV"}


def _is_business(owner_name: str) -> bool:
    tokens = re.split(r"[\s.,]+", owner_name.upper())
    return any(t in _BUSINESS_TOKENS for t in tokens)


def _clean_person_tokens(name: str) -> list[str]:
    """Reduce a single person's name to its significant word tokens.

    Strips honorifics (Mr/Dr), generational suffixes (Jr/III), single-letter
    middle initials, and any leftover punctuation — leaving the words that
    matter for a name match. Title-cases so 'GRETA' → 'Greta'.
    """
    raw = re.split(r"[\s.,]+", name)
    out = []
    for tok in raw:
        word = re.sub(r"[^A-Za-z'\-]", "", tok)
        if not word:
            continue
        upper = word.upper()
        if upper in _NAME_TITLES or upper in _NAME_SUFFIXES:
            continue
        if len(word) == 1:  # middle initial
            continue
        out.append(word.capitalize() if word.isupper() or word.islower() else word)
    return out


def _owner_name_candidates(owner_name: str) -> list[tuple[str, str]]:
    """Turn a raw county owner_name into ordered (first, last) candidates to try.

    Handles the messiness of appraisal-district names:
      - business entities (LLC, TRUST…) → return [] (no person to skip-trace)
      - multi-owner ("A & B", "A AND B") → use only the first owner
      - "Last, First" comma form         → respected as authoritative order
      - honorifics / suffixes / initials → stripped
      - ambiguous First/Last order       → return BOTH orderings to try in turn
    """
    name = (owner_name or "").strip()
    if not name or _is_business(name):
        return []

    # Multiple owners are joined by '&' or ' AND ' — keep the first only.
    name = re.split(r"\s*&\s*|\s+\bAND\b\s+", name, flags=re.IGNORECASE)[0].strip()

    # "Last, First [Middle]" — the comma tells us the order unambiguously.
    if "," in name:
        last_part, first_part = name.split(",", 1)
        last_toks = _clean_person_tokens(last_part)
        first_toks = _clean_person_tokens(first_part)
        if first_toks and last_toks:
            return [(first_toks[0], last_toks[-1])]
        # Fall through to positional handling if one side was empty.

    tokens = _clean_person_tokens(name)
    if len(tokens) < 2:
        return []

    a, b = tokens[0], tokens[-1]
    # Order is ambiguous without a comma ("Greta Fisher" is First-Last,
    # "Portela Raul" is Last-First), so try both orderings in turn.
    return [(a, b), (b, a)]


def _str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _first_value(data: dict, keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty value among `keys`, unwrapping lists/dicts.

    Handles Versium shapes where a field may be a scalar, a list of values, or a
    list of {"number": ...} / {"address": ...} dicts.
    """
    for key in keys:
        value = data.get(key)
        if not value:
            continue
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("number") or value.get("address") or value.get("value")
        if value:
            return str(value).strip()
    return None


def _passes_grade(row: dict) -> bool:
    if not CONTACT_MIN_GRADE:
        return True
    return _GRADE_RANK.get(row.get("score_grade"), 0) >= _GRADE_RANK.get(CONTACT_MIN_GRADE, 0)


def enrich_contact(zip_code: str, account_id: int, selected_only: bool = False) -> dict:
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
        rows = fetch_missing_field(conn, "contact_phone", account_id, zip_code,
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
        counter["updated"] = upsert_properties(conn, updates, account_id)
    finally:
        conn.close()
    return counter
