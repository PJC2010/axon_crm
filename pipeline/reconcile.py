"""
Reconciliation — compare a stored property row against a fresh RentCast record.

Pure and dependency-free (no DB, no network) so the policy that decides what
gets written can be unit-tested, in the same spirit as pipeline/equity.py and
pipeline/job_value.py. pipeline/backfill.py is the driver that pairs this with
the API and the database.

Two jobs live here:

1. ``map_record`` — one canonical RentCast-record → properties-column mapping.
   pipeline/property.py's per-ZIP enrichment step delegates to it, so the detail
   fetcher and the backfill sweep can never drift apart on field names.

2. ``reconcile`` — a per-field verdict comparing what we stored against what
   RentCast says now, plus the subset that is safe to write back.

The write-back policy is the part that matters. Every field falls into one of
two buckets:

  fill_only   Static facts about the structure — year built, square footage, lot
              size, garage. HCAD (the county appraisal district) is the primary
              record for these and it runs upstream for free. A disagreement is
              a data-quality question, not news, so we record it and keep what we
              have rather than letting an AVM overwrite the assessor.

  refreshable Values that legitimately move — the market estimate, the most
              recent sale, whether the owner still lives there. Here a
              disagreement means our copy is stale and RentCast is the better
              source, so a sweep run in "refresh" mode overwrites.

Nothing is overwritten in the default "fill" mode: gaps get filled, differences
get recorded for review. Overwriting is an explicit opt-in because
estimated_value feeds lead scoring, so a refresh moves grades.
"""
from datetime import date

from config import PROPERTY_VALUE_TOLERANCE_PCT
from pipeline.addr import same_address
from pipeline.equity import estimate_equity

# ── Verdicts ──────────────────────────────────────────────────────────────────
FILL = "fill"           # we have nothing, RentCast does — free win
MATCH = "match"         # both present and in agreement
MISMATCH = "mismatch"   # both present and they disagree
NO_REMOTE = "no_remote"  # RentCast has nothing to say (a structural gap)

# ── Resolutions (what the sweep actually did about a verdict) ─────────────────
FILLED = "filled"
REFRESHED = "refreshed"
KEPT = "kept"

# ── Field policy ──────────────────────────────────────────────────────────────
# kind      how to compare: "number" | "text" | "date" | "bool"
# policy    "fill_only" (never overwrite) | "refreshable" (overwrite in refresh mode)
# tol       fractional tolerance for numeric comparison; 0.0 means exact.
# derived   computed by us from other fields rather than reported by the vendor
#
# Money and square footage get a tolerance because two sources rounding a
# genuinely-equal value differently is noise, not a discrepancy worth a row in
# the audit table.
#
# `derived` fields are the same idea taken further. estimated_equity is an
# amortization curve and ownership_years is a subtraction from today's date, so
# both drift away from any stored copy purely with the passage of time. They
# refresh (they should track the sale data they are computed from) but they are
# never *reported*: an operator reviewing discrepancies wants the cases where two
# sources disagree about the world, not a row telling them a year has gone by.
FIELD_RULES: dict[str, dict] = {
    "year_built":       {"kind": "number", "policy": "fill_only",   "tol": 0.0},
    "square_footage":   {"kind": "number", "policy": "fill_only",   "tol": 0.02},
    "lot_size":         {"kind": "number", "policy": "fill_only",   "tol": 0.05},
    "property_type":    {"kind": "text",   "policy": "fill_only"},
    "garage_spaces":    {"kind": "number", "policy": "fill_only",   "tol": 0.0},
    "garage_type":      {"kind": "text",   "policy": "fill_only"},
    "subdivision":      {"kind": "text",   "policy": "fill_only"},
    "owner_name":       {"kind": "text",   "policy": "fill_only"},
    # Market/ownership state — these move, so RentCast wins in refresh mode.
    "estimated_value":  {"kind": "number", "policy": "refreshable",
                         "tol": PROPERTY_VALUE_TOLERANCE_PCT},
    "estimated_equity": {"kind": "number", "policy": "refreshable",
                         "tol": PROPERTY_VALUE_TOLERANCE_PCT, "derived": True},
    "last_sale_date":   {"kind": "date",   "policy": "refreshable"},
    "last_sale_price":  {"kind": "number", "policy": "refreshable", "tol": 0.0},
    "owner_occupied":   {"kind": "bool",   "policy": "refreshable"},
    "ownership_years":  {"kind": "number", "policy": "refreshable", "tol": 0.0,
                         "derived": True},
    # Geography. Coordinates are only ever filled, never moved: geocode
    # provenance (geocode_source) belongs to whichever step set them, and a
    # silent coordinate shift would relocate a pin on the map.
    "latitude":         {"kind": "number", "policy": "fill_only",   "tol": 0.0},
    "longitude":        {"kind": "number", "policy": "fill_only",   "tol": 0.0},
    "city":             {"kind": "text",   "policy": "fill_only"},
    "state":            {"kind": "text",   "policy": "fill_only"},
}

# Every column a RentCast lookup can speak to, in a stable order.
RECONCILED_FIELDS = list(FIELD_RULES)

# Location columns: reconciled, but never reported and never written by the
# per-ZIP detail step below.
_LOCATION_FIELDS = ("latitude", "longitude", "city", "state")

# Fields whose disagreement is worth surfacing to an operator. Location is
# excluded — a 0.0001° drift or "HOUSTON" vs "Houston" is noise that would bury
# real findings — and so are derived fields, which drift on their own.
REPORTED_FIELDS = [
    f for f, rule in FIELD_RULES.items()
    if f not in _LOCATION_FIELDS and not rule.get("derived")
]

# Columns the per-ZIP detail step (pipeline/property.py) writes back.
#
# Narrower than the full mapping on purpose. That step overwrites every column
# it returns, so handing it coordinates would let RentCast move a pin the
# geocode step had already placed — and leave geocode_source describing a
# provider that no longer set the value. The backfill sweep fills those columns
# safely instead, because it only ever writes into a NULL.
DETAIL_FIELDS = [f for f in RECONCILED_FIELDS if f not in _LOCATION_FIELDS]


# ── RentCast record → property columns ────────────────────────────────────────

def map_record(record: dict) -> dict:
    """Map one RentCast `/properties` record onto our column names.

    Returns every column the record can speak to; values it has nothing for come
    back as None. Callers write non-NULL only (pipeline.db.upsert_properties), so
    a sparse record never clobbers a populated row.

    Two shapes here are easy to get wrong and were confirmed against live
    responses: garage data is nested under `features`, and the owner's name is a
    list under `owner.names` — there is no flat `ownerName` on current records,
    though it is still read as a fallback for older cached payloads.
    """
    features = record.get("features") or {}
    owner = record.get("owner") or {}
    names = owner.get("names")
    owner_name = (names[0] if isinstance(names, list) and names
                  else record.get("ownerName"))

    value = record.get("price")
    sale_price = record.get("lastSalePrice")
    sale_date = record.get("lastSaleDate")

    return {
        "year_built":       record.get("yearBuilt"),
        "square_footage":   record.get("squareFootage"),
        "lot_size":         record.get("lotSize") or features.get("lotSize"),
        "property_type":    record.get("propertyType"),
        "garage_spaces":    features.get("garageSpaces"),
        "garage_type":      features.get("garageType"),
        "subdivision":      record.get("subdivision"),
        "owner_name":       owner_name,
        "estimated_value":  value,
        "estimated_equity": estimate_equity(value, sale_price, sale_date),
        "last_sale_date":   sale_date,
        "last_sale_price":  sale_price,
        "owner_occupied":   record.get("ownerOccupied"),
        "ownership_years":  years_owned(sale_date),
        "latitude":         record.get("latitude"),
        "longitude":        record.get("longitude"),
        "city":             record.get("city"),
        "state":            record.get("state"),
    }


def record_address(record: dict) -> str | None:
    """The street address a RentCast record claims to describe.

    `addressLine1` is the street line; `formattedAddress` is the whole thing
    ("123 Main St, Houston, TX 77396"), so its first comma-separated segment is
    the same street line. Returns None when the record carries neither, which
    callers must treat as unverifiable rather than as a match.
    """
    line = (record.get("addressLine1") or "").strip()
    if line:
        return line
    formatted = (record.get("formattedAddress") or "").strip()
    return formatted.split(",")[0].strip() or None if formatted else None


def verify_record(record: dict, requested_address: str) -> str | None:
    """Check a record describes the property we asked about.

    Returns None when it does, or the address the vendor actually answered with
    when it does not.

    The lookup is by address string and the vendor's own parser decides what that
    resolves to — we send "500 W 12TH 1/2 ST" and get back whatever it matched,
    with `limit=1` hiding any ambiguity. Without this check a neighbouring
    parcel's year built, value and owner land on our row silently, and the row
    still gets stamped as enriched. `same_address` is deliberately lenient, so a
    rejection here means the two are clearly different properties.
    """
    answered = record_address(record)
    if answered is None:
        return "(no address on record)"
    return None if same_address(requested_address, answered) else answered


def map_detail(record: dict) -> dict:
    """`map_record` narrowed to DETAIL_FIELDS — what the per-ZIP step writes."""
    mapped = map_record(record)
    return {f: mapped[f] for f in DETAIL_FIELDS}


def years_owned(sale_date) -> int | None:
    """Whole years since the last sale, or None when the date is unusable.

    Deliberately coarse (calendar-year difference) — it feeds a scoring signal
    that buckets tenure, not an amortization schedule.
    """
    iso = _as_date(sale_date)
    if iso is None:
        return None
    years = date.today().year - iso.year
    return years if years >= 0 else None


# ── Comparison ────────────────────────────────────────────────────────────────

def reconcile(stored: dict, record: dict, *, mode: str = "fill",
              fields: list[str] | None = None) -> dict:
    """Compare a stored property row against a RentCast record.

    `mode` is "fill" (write only into NULLs) or "refresh" (also overwrite a
    refreshable field whose stored value disagrees).

    Returns::

        {
          "verdicts":  {field: FILL | MATCH | MISMATCH | NO_REMOTE},
          "updates":   {field: value}   # safe to write, per mode
          "findings":  [ {field, stored, remote, verdict, resolution}, … ]
        }

    `updates` never contains a field the mode does not allow us to touch, so the
    caller can hand it straight to upsert_properties.
    """
    if mode not in ("fill", "refresh"):
        raise ValueError(f"mode must be 'fill' or 'refresh', got {mode!r}")

    remote = map_record(record)
    verdicts: dict[str, str] = {}
    updates: dict[str, object] = {}
    findings: list[dict] = []

    for field in (fields or RECONCILED_FIELDS):
        rule = FIELD_RULES.get(field)
        if rule is None:
            continue
        mine, theirs = stored.get(field), remote.get(field)

        if theirs is None or theirs == "":
            verdicts[field] = NO_REMOTE
            continue
        if mine is None or mine == "":
            verdicts[field] = FILL
            updates[field] = theirs
            findings.append(_finding(field, mine, theirs, FILL, FILLED))
            continue

        if _equal(mine, theirs, rule):
            verdicts[field] = MATCH
            continue

        verdicts[field] = MISMATCH
        refresh = mode == "refresh" and rule["policy"] == "refreshable"
        if refresh:
            updates[field] = theirs
        findings.append(_finding(field, mine, theirs, MISMATCH,
                                 REFRESHED if refresh else KEPT))

    return {"verdicts": verdicts, "updates": updates, "findings": findings}


def _finding(field, stored, remote, verdict, resolution) -> dict:
    return {
        "field": field,
        "stored": _as_text(stored),
        "remote": _as_text(remote),
        "verdict": verdict,
        "resolution": resolution,
    }


# ── Typed comparison helpers ──────────────────────────────────────────────────

def _equal(mine, theirs, rule: dict) -> bool:
    kind = rule["kind"]
    if kind == "number":
        return _numbers_equal(mine, theirs, rule.get("tol", 0.0))
    if kind == "date":
        return _as_date(mine) == _as_date(theirs)
    if kind == "bool":
        return _as_bool(mine) == _as_bool(theirs)
    return _norm_text(mine) == _norm_text(theirs)


def _numbers_equal(mine, theirs, tol: float) -> bool:
    """Equal within a fractional tolerance of the larger magnitude.

    Scaling by magnitude rather than using a flat epsilon keeps one tolerance
    meaningful across a $12,000 lot and a $1.2M house.
    """
    a, b = _as_number(mine), _as_number(theirs)
    if a is None or b is None:
        # A value we cannot parse is not evidence of a difference — treat it as
        # agreement so unparseable junk never floods the discrepancy report.
        return True
    if a == b:
        return True
    if tol <= 0:
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b))


def _as_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _as_date(value) -> date | None:
    """Parse a date, a datetime, or an ISO-ish string down to a calendar day."""
    if isinstance(value, date):
        # datetime is a date subclass; .date() would lose nothing we compare on.
        return date(value.year, value.month, value.day)
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "t", "yes", "y", "1"):
        return True
    if text in ("false", "f", "no", "n", "0"):
        return False
    return None


def _norm_text(value) -> str:
    """Case- and whitespace-insensitive form for text comparison.

    Sources differ freely on casing and internal spacing ("Single Family" vs
    "SINGLE  FAMILY"); neither is a real discrepancy.
    """
    return " ".join(str(value).split()).upper()


def _as_text(value) -> str | None:
    """Render a value for the audit trail. Stored as text so one column can hold
    a year, a price, and a garage type without a type per field."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()[:10]
    return str(value)
