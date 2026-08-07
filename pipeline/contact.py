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
webhook in api/routes/twilio_voice.py also lives here, configured separately via
PHONE_APPEND_PROVIDER/PHONE_APPEND_API_KEY and dispatched through
PHONE_APPEND_PROVIDERS. Two providers: versium_phone_append (one GET per
number) and batchdata_phone_append (Reverse Skip Trace, up to 100 numbers per
POST, and the only one that returns line type + DNC). Use phone_append /
phone_append_batch rather than a provider function directly.
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

# Default BatchData Reverse Skip Trace endpoint — overridable via
# PHONE_APPEND_BASE_URL. Note the v3: the forward skip-trace above is v1-only
# and the reverse direction is v3-only; there is no /api/v1 reverse route.
_BATCHDATA_REVERSE_URL = "https://api.batchdata.com/api/v3/property/reverse-skip-trace"

# Reverse Skip Trace rejects a body with more than 100 lookups in it.
BATCHDATA_REVERSE_MAX_BATCH = 100


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


def batchdata_phone_append_batch(
    phone_digits: list[str], *, timeout: int = 20, retries: int | None = None,
) -> dict[str, dict | None]:
    """Reverse-append callers via BatchData's Reverse Skip Trace API.

    The batch counterpart of versium_phone_append: up to 100 numbers per HTTP
    call (BATCHDATA_REVERSE_MAX_BATCH — a longer list is rejected outright), so
    the sweep in api/call_append_sweep.py backfills a whole backlog in a few
    requests. Duplicates are collapsed before the call.

    Returns {digits: data-or-None}. A key is present only when the provider
    actually answered for that number, so callers can distinguish "asked, no
    match" (present, None — the query was billed, don't re-ask) from "never
    asked" (absent — a transport failure, safe to retry). `data` carries the
    same fields as versium_phone_append plus the line-type and compliance
    signals only BatchData returns.

    The per-row error model is the trap here: a malformed body is an HTTP 400,
    but a bad *row* comes back inside an HTTP 200 as data[i].meta.error, so a
    2xx alone is not success.
    """
    wanted = list(dict.fromkeys(d for d in phone_digits if _is_us_phone(d)))
    if not wanted or PHONE_APPEND_PROVIDER != "batchdata" or not PHONE_APPEND_API_KEY:
        return {}
    if len(wanted) > BATCHDATA_REVERSE_MAX_BATCH:
        raise ValueError(
            f"reverse skip trace takes at most {BATCHDATA_REVERSE_MAX_BATCH} "
            f"numbers per call, got {len(wanted)}")

    payload = post_json(
        PHONE_APPEND_BASE_URL or _BATCHDATA_REVERSE_URL,
        json={"requests": [{"phone": d} for d in wanted]},
        headers={
            "Authorization": f"Bearer {PHONE_APPEND_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=timeout,
        retries=retries,
    )
    if not payload:
        return {}  # transport failure — nothing was billed, retry later

    records = ((payload.get("result") or {}).get("data")) or []
    if not isinstance(records, list):
        return {}

    out: dict[str, dict | None] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        # data[] runs parallel to requests[], and `input` echoes the number
        # back — trust the echo when it's there, fall back to position.
        echoed = _str((record.get("input") or {}).get("phone"))
        digits = echoed if echoed in wanted else (
            wanted[index] if index < len(wanted) else None)
        if not digits:
            continue

        meta = record.get("meta") or {}
        if meta.get("error"):
            # A rejected row (non-US number, missing input) was never run; log
            # it and leave the key absent so nothing gets flagged as spent.
            log.warning("Reverse skip trace rejected %s: %s",
                        digits, meta.get("errorMessage"))
            continue

        persons = record.get("persons") or []
        person = _ranked_first(persons, prefer_key="propertyOwner")
        out[digits] = _batchdata_person_append(person) if person else None
    return out


def batchdata_phone_append(phone_digits: str) -> dict | None:
    """Single-caller reverse append — the inbound-webhook path.

    A batch of one, with the tight timeout and no retries the Twilio webhook
    window demands (same reasoning as versium_phone_append).
    """
    if PHONE_APPEND_PROVIDER != "batchdata" or not PHONE_APPEND_API_KEY:
        return None
    return batchdata_phone_append_batch(
        [(phone_digits or "").strip()], timeout=8, retries=0,
    ).get((phone_digits or "").strip())


def _batchdata_person_append(person: dict) -> dict | None:
    """Map one reverse-skip-trace person onto our append fields.

    Address preference is deliberate: `property.address` is the parcel BatchData
    tied the caller to — the place the work would happen — whereas addresses[]
    is a ranked history that can lead with a mailing address. Falls back to the
    best-ranked address when there's no property on the record.
    """
    name = person.get("name") or {}
    full = _str(name.get("full")) or _full_name(
        _str(name.get("first")), _str(name.get("last")))

    prop = person.get("property") or {}
    addr = prop.get("address") if isinstance(prop, dict) else None
    if not (isinstance(addr, dict) and addr.get("street")):
        addr = _ranked_first(person.get("addresses") or [],
                             prefer_key="propertyMailingAddress") or {}

    email = _ranked_first(person.get("emails") or [], prefer_key="tested") or {}
    phone = _ranked_first(person.get("phones") or [], prefer_key="reachable") or {}

    out = {
        "contact_name":  full,
        "contact_email": _str(email.get("email")),
        "address":       _str(addr.get("street")),
        "city":          _str(addr.get("city")),
        "state":         _str(addr.get("state")),
        "zip":           _str(addr.get("zip")),
        # Line type and compliance flags have no column of their own — the
        # caller stashes them in enrichment_flags so an SMS follow-up can tell
        # a mobile from a landline before it spends a segment.
        "phone_type":      _str(phone.get("type")),
        "phone_reachable": phone.get("reachable"),
        "phone_dnc":       phone.get("dnc"),
        "litigator":       person.get("litigator"),
        "property_owner":  person.get("propertyOwner"),
    }
    out = {k: v for k, v in out.items() if v not in (None, "")}
    return out or None


def _ranked_first(items, *, prefer_key: str | None = None) -> dict | None:
    """Best entry from one of BatchData's rank-ordered lists.

    Rows flagged with `prefer_key` (propertyOwner, reachable, tested…) sort
    ahead of unflagged ones, then by BatchData's own rank. Rank is 1-based and
    may be missing, so absent ranks sort last rather than winning as 0.
    """
    rows = [i for i in (items or []) if isinstance(i, dict)]
    if not rows:
        return None

    def sort_key(row: dict) -> tuple[int, int]:
        flagged = 0 if (prefer_key and row.get(prefer_key)) else 1
        rank = row.get("rank")
        return (flagged, rank if isinstance(rank, int) else 1 << 30)

    return sorted(rows, key=sort_key)[0]


def _is_us_phone(digits) -> bool:
    """BatchData rejects anything that isn't a 10-digit US number."""
    return isinstance(digits, str) and len(digits.strip()) == 10 \
        and digits.strip().isdigit()


# Reverse-append provider name → single-number lookup function. Keyed on
# PHONE_APPEND_PROVIDER, separate from PROVIDERS above so the batch skip-trace
# and the inbound-call append can run on different vendors.
PHONE_APPEND_PROVIDERS = {
    "batchdata": batchdata_phone_append,
    "versium": versium_phone_append,
}


def phone_append(phone_digits: str) -> dict | None:
    """Reverse-append one caller via whichever provider is configured."""
    lookup = PHONE_APPEND_PROVIDERS.get(PHONE_APPEND_PROVIDER)
    return lookup(phone_digits) if lookup else None


def phone_append_batch(phone_digits: list[str]) -> dict[str, dict | None]:
    """Reverse-append many callers, batching when the provider supports it.

    BatchData answers up to 100 numbers per request; Versium has no batch form,
    so it degrades to one call per number. Same {digits: data-or-None} contract
    as batchdata_phone_append_batch — an absent key means "never asked".
    """
    if PHONE_APPEND_PROVIDER == "batchdata":
        results: dict[str, dict | None] = {}
        wanted = list(dict.fromkeys(phone_digits))
        for start in range(0, len(wanted), BATCHDATA_REVERSE_MAX_BATCH):
            chunk = wanted[start:start + BATCHDATA_REVERSE_MAX_BATCH]
            results.update(batchdata_phone_append_batch(chunk))
        return results

    lookup = PHONE_APPEND_PROVIDERS.get(PHONE_APPEND_PROVIDER)
    if not lookup:
        return {}
    # A per-number provider can't report "asked but no match" separately from a
    # failed call, so every completed loop iteration counts as asked.
    return {digits: lookup(digits) for digits in dict.fromkeys(phone_digits)}


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
