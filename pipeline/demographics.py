"""
Step 9.5 — Household demographics / life-events enrichment (paid, optional).

Enriches leads with owner-level demographic data from the Versium Demographic
Append API (or any pluggable provider). With no provider configured
(DEMO_PROVIDER="") this step is a no-op, identical to how pipeline/contact.py
behaves without CONTACT_PROVIDER.

Columns written (migrations 028 + 029):

  Scoring signals — wired into the rule-based scorer:
    refi_date              — date of most recent mortgage refinance
    home_improvement_flag  — owner actively buys home-improvement products
    credit_rating          — 'A' | 'B' | 'C' | 'D' (Versium letter grade)
    has_children           — presence of children in household
    gardening_flag         — lifestyle: gardening / outdoor interest

  Model features — captured for a future conversion-probability model:
    age_range              — e.g. '35-44', '45-54'
    estimated_net_worth    — lower bound of Versium net-worth band (USD)
    loan_to_value          — current LTV % (tighter equity signal than estimated_equity)
    marital_status         — e.g. 'Married', 'Single'
    occupation             — e.g. 'Professional/Technical', 'Retired'
    senior_in_household    — True if anyone in the household is 65+
    pets_flag              — household has pets
    decorating_flag        — lifestyle: decorating / furnishing interest
    credit_lines_count     — number of active credit lines
    mortgage_rate_type     — 'Fixed' | 'ARM'

  From migration 028 (still populated here):
    owner_age              — midpoint of age_range or direct age field
    length_of_residence_years
    est_household_income   — lower bound of income band (USD)
    life_stage             — 'new_mover' | 'established' | 'retiree' | 'other'

Cost controls (mirrors pipeline/contact.py):
  - Only processes rows that have an owner_name
  - Capped at DEMO_MAX_ROWS_PER_ZIP per run
  - Optional DEMO_MIN_GRADE grade gate
  - 0.1s delay between API calls
  - selected_only flag for capped/radius runs

Adding a provider = add a normalizer to PROVIDERS that maps the provider's
response to the field dict above.
"""
import logging
import re
import time
from datetime import date

from config import (
    DEMO_PROVIDER, DEMO_API_KEY, DEMO_BASE_URL,
    DEMO_MAX_ROWS_PER_ZIP, DEMO_MIN_GRADE,
)
from pipeline.db import get_conn, fetch_missing_field, upsert_properties
from pipeline.http import get_json

log = logging.getLogger(__name__)

_GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}

# Default Versium Demographic Append endpoint — overridable via DEMO_BASE_URL.
_VERSIUM_DEMO_URL = "https://api.versium.com/v2/demographic"


def _versium_lookup(row: dict) -> dict | None:
    """Fetch full demographic data from the Versium Demographic Append API.

    Input: owner_name + address fields.
    Output: all scoring-signal and model-feature columns from the response.

    Response parsing is intentionally defensive — field names vary across
    Versium API versions (spaces vs underscores, different capitalisation).
    We normalise keys to lowercase+underscore before lookup to handle both.
    """
    url = DEMO_BASE_URL or _VERSIUM_DEMO_URL
    resp = get_json(
        url,
        headers={
            "x-versium-api-key": DEMO_API_KEY,
            "Accept": "application/json",
        },
        params={
            "first":   _first_name(row.get("owner_name", "")),
            "last":    _last_name(row.get("owner_name", "")),
            "address": row.get("address", ""),
            "city":    row.get("city", ""),
            "state":   row.get("state", ""),
            "zip":     row.get("zip", ""),
        },
        timeout=15,
    )
    if not resp:
        return None

    results = resp.get("versium", {}).get("results") or resp.get("results") or []
    if not results:
        return None
    raw = results[0] if isinstance(results, list) else results

    # Normalise all keys: "Length Of Residence" → "length_of_residence"
    p = {re.sub(r"[\s/]+", "_", k).lower(): v for k, v in raw.items()}

    # ── Scoring-signal fields ──────────────────────────────────────────────────
    refi_date           = _parse_ym_date(p.get("refinance_date") or p.get("refi_date"))
    home_improvement    = _yn(p.get("home_improvement"))
    credit_rating       = _credit_grade(p.get("credit_rating") or p.get("credit_card_rating"))
    has_children        = _yn(p.get("presence_of_children") or p.get("children_present"))
    gardening           = _yn(p.get("gardening"))

    # ── Model-feature fields ───────────────────────────────────────────────────
    age_range           = _str(p.get("age_range") or p.get("age"))
    net_worth           = _band_lower(p.get("estimated_net_worth") or p.get("net_worth"))
    ltv                 = _safe_float(p.get("loan_to_value") or p.get("ltv"))
    marital_status      = _str(p.get("marital_status") or p.get("marital"))
    occupation          = _str(p.get("occupation"))
    senior              = _yn(p.get("senior_in_household") or p.get("senior"))
    pets                = _yn(p.get("pets") or p.get("pets_indicator"))
    decorating          = _yn(p.get("decorating_furnishing") or p.get("decorating"))
    credit_lines        = _safe_int(p.get("number_of_credit_lines") or p.get("num_credit_lines")
                                    or p.get("credit_lines_count"))
    rate_type           = _mortgage_rate_type(p.get("mortgage_rate_type")
                                               or p.get("mortgage_purchase_rate_type"))

    # ── Migration-028 fields (still populated here) ───────────────────────────
    tenure              = _safe_int(p.get("length_of_residence") or p.get("length_of_residence_years"))
    income              = _band_lower(p.get("household_income") or p.get("estimated_income"))
    owner_age           = _age_midpoint(age_range)
    life_stage          = _normalize_life_stage(None, owner_age, tenure, senior)

    result = {
        # Scoring signals
        "refi_date":              refi_date,
        "home_improvement_flag":  home_improvement,
        "credit_rating":          credit_rating,
        "has_children":           has_children,
        "gardening_flag":         gardening,
        # Model features
        "age_range":              age_range,
        "estimated_net_worth":    net_worth,
        "loan_to_value":          ltv,
        "marital_status":         marital_status,
        "occupation":             occupation,
        "senior_in_household":    senior,
        "pets_flag":              pets,
        "decorating_flag":        decorating,
        "credit_lines_count":     credit_lines,
        "mortgage_rate_type":     rate_type,
        # Migration-028
        "owner_age":              owner_age,
        "length_of_residence_years": tenure,
        "est_household_income":   income,
        "life_stage":             life_stage,
    }
    # Drop None values — upsert_properties skips None so no field is clobbered.
    result = {k: v for k, v in result.items() if v is not None}
    return result or None


# ── Provider registry ─────────────────────────────────────────────────────────

PROVIDERS = {
    "versium": _versium_lookup,
    # "melissa": _melissa_lookup,  # add more providers here
}


# ── Response parsing helpers ──────────────────────────────────────────────────

def _first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else ""


def _last_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[-1] if parts else ""


def _yn(value) -> bool | None:
    """Map 'Y'/'Yes'/True → True, 'N'/'No'/False → False, else None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().upper()
    if s in ("Y", "YES", "1", "TRUE"):
        return True
    if s in ("N", "NO", "0", "FALSE"):
        return False
    return None


def _str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(",", "").split(".")[0])
    except (ValueError, TypeError):
        return None


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def _band_lower(value) -> int | None:
    """Extract lower bound from a dollar-band string like '$75,000-$99,999'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\$?([\d,]+)", str(value))
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_ym_date(value) -> date | None:
    """Parse 'YYYY-MM', 'YYYY-MM-DD', or 'YYYY' into a date (1st of month)."""
    if not value:
        return None
    s = str(value).strip()
    for fmt, parser in [
        (r"^\d{4}-\d{2}-\d{2}$", lambda x: date.fromisoformat(x)),
        (r"^\d{4}-\d{2}$",        lambda x: date(int(x[:4]), int(x[5:7]), 1)),
        (r"^\d{4}$",              lambda x: date(int(x), 1, 1)),
    ]:
        if re.match(fmt, s):
            try:
                return parser(s)
            except (ValueError, TypeError):
                pass
    return None


def _credit_grade(value) -> str | None:
    """Normalise to 'A' | 'B' | 'C' | 'D'."""
    if not value:
        return None
    s = str(value).strip().upper()
    if s in ("A", "B", "C", "D"):
        return s
    # Map text descriptions to letter grades
    low = s.lower()
    if "excellent" in low or "premium" in low:
        return "A"
    if "good" in low:
        return "B"
    if "fair" in low or "average" in low:
        return "C"
    if "poor" in low or "bad" in low:
        return "D"
    return None


def _mortgage_rate_type(value) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    low = s.lower()
    if "fix" in low:
        return "Fixed"
    if "arm" in low or "variable" in low or "adjust" in low:
        return "ARM"
    return None


def _age_midpoint(age_range: str | None) -> int | None:
    """Extract midpoint integer from '35-44' → 39, '65+' → 65, or plain int."""
    if not age_range:
        return None
    # Two-number range: '35-44' → 39
    m = re.match(r"(\d+)[^\d]+(\d+)", str(age_range))
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    # Open-ended: '65+' → 65
    m = re.match(r"(\d+)\+", str(age_range))
    if m:
        return int(m.group(1))
    try:
        return int(str(age_range).strip())
    except ValueError:
        return None


def _normalize_life_stage(raw: str | None, age: int | None, tenure: int | None,
                           senior: bool | None) -> str | None:
    """Infer life stage from available demographic signals."""
    if raw:
        low = raw.lower().replace(" ", "_").replace("-", "_")
        if "new_mover" in low or "new_resident" in low:
            return "new_mover"
        if "retir" in low or "senior" in low:
            return "retiree"
        if "establish" in low or "long" in low:
            return "established"
        if low in ("new_mover", "established", "retiree", "other"):
            return low
    if senior:
        return "retiree"
    if tenure is not None and tenure <= 2:
        return "new_mover"
    if age is not None and age >= 65:
        return "retiree"
    if tenure is not None and tenure >= 5:
        return "established"
    return "other" if any(x is not None for x in [age, tenure]) else None


# ── Grade gate ────────────────────────────────────────────────────────────────

def _passes_grade(row: dict) -> bool:
    if not DEMO_MIN_GRADE:
        return True
    return _GRADE_RANK.get(row.get("score_grade"), 0) >= _GRADE_RANK.get(DEMO_MIN_GRADE, 0)


# ── Public entry point ────────────────────────────────────────────────────────

def enrich_demographics(zip_code: str, account_id: int, selected_only: bool = False) -> dict:
    """Enrich owner demographics for leads missing the data. Returns a counter dict.

    When `selected_only` is True (capped/radius runs), only rows the selection step
    kept (enrichment_selected = TRUE) are enriched — same pattern as contact step.
    """
    counter = {"ok": 0, "fail": 0, "updated": 0, "skipped_no_key": False}

    lookup = PROVIDERS.get(DEMO_PROVIDER)
    if not DEMO_PROVIDER or not DEMO_API_KEY or lookup is None:
        counter["skipped_no_key"] = True
        if DEMO_PROVIDER and lookup is None:
            log.warning("Unknown DEMO_PROVIDER %r — skipping demographics enrichment.", DEMO_PROVIDER)
        else:
            log.info("Demographics provider not configured — skipping demographics enrichment.")
        return counter

    conn = get_conn()
    try:
        # Use owner_age as the sentinel — any record without it needs enrichment.
        rows = fetch_missing_field(conn, "owner_age", account_id, zip_code,
                                   selected_only=selected_only)
        rows = [r for r in rows if r.get("owner_name") and _passes_grade(r)]
        rows = rows[:DEMO_MAX_ROWS_PER_ZIP]
        if not rows:
            return counter

        log.info("Demographics enriching %d properties via %s…", len(rows), DEMO_PROVIDER)
        updates = []
        for row in rows:
            data = lookup(row)
            if data:
                counter["ok"] += 1
                data.update({
                    "address": row["address"],
                    "zip": row["zip"],
                    "enrichment_flags": {"demographics": DEMO_PROVIDER},
                })
                updates.append(data)
            else:
                counter["fail"] += 1
            time.sleep(0.1)
        counter["updated"] = upsert_properties(conn, updates, account_id)
    finally:
        conn.close()
    return counter
