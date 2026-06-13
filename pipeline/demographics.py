"""
Step 9.5 — Household demographics / life-events enrichment (paid, optional).

Enriches leads with owner-level demographic data from a pluggable paid provider
(e.g. Versium). With no provider configured (DEMO_PROVIDER="") this step is a
no-op, identical to how pipeline/contact.py behaves without CONTACT_PROVIDER.

New columns written (migration 028):
  owner_age                 — estimated owner age in years
  length_of_residence_years — years at current address
  est_household_income      — estimated household income (owner-level, finer than zip median)
  life_stage                — categorical: 'new_mover' | 'established' | 'retiree' | 'other'

These columns are model features for a future conversion-probability model; they
are not wired into the rule-based scorer in this iteration.

Cost controls (mirrors pipeline/contact.py):
  - Only processes rows that have an owner_name (need identity for lookup)
  - Capped at DEMO_MAX_ROWS_PER_ZIP per run
  - Optional DEMO_MIN_GRADE gate (e.g. "B" = only A/B leads pay for enrichment)
  - 0.1s delay between API calls
  - selected_only flag for capped/radius runs (only scored leads)

Adding a provider = add a normalizer to PROVIDERS that maps the provider's
response to {"owner_age", "length_of_residence_years", "est_household_income",
"life_stage"}.
"""
import logging
import time

from config import (
    DEMO_PROVIDER, DEMO_API_KEY, DEMO_BASE_URL,
    DEMO_MAX_ROWS_PER_ZIP, DEMO_MIN_GRADE,
)
from pipeline.db import get_conn, fetch_missing_field, upsert_properties
from pipeline.http import get_json

log = logging.getLogger(__name__)

_GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}


def _versium_lookup(row: dict) -> dict | None:
    """Fetch demographic data from the Versium Reach API.

    Maps owner_name + address to: owner_age, length_of_residence_years,
    est_household_income, life_stage.

    Versium Reach B2C endpoint: POST/GET with name + address fields, returns
    a list of matched person records. We take the first match (highest confidence).
    Adjust the response-path mapping here for whichever provider you use.
    """
    resp = get_json(
        DEMO_BASE_URL,
        headers={
            "x-versium-api-key": DEMO_API_KEY,
            "Accept": "application/json",
        },
        params={
            "fn": _first_name(row.get("owner_name", "")),
            "ln": _last_name(row.get("owner_name", "")),
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
    person = results[0] if isinstance(results, list) else results

    age = _safe_int(person.get("age") or person.get("Age"))
    tenure = _safe_int(
        person.get("length_of_residence") or person.get("LengthOfResidence")
        or person.get("years_at_address")
    )
    income = _safe_int(
        person.get("estimated_income") or person.get("EstimatedIncome")
        or person.get("household_income")
    )
    life_stage = _normalize_life_stage(person.get("life_stage") or person.get("LifeStage"), age, tenure)

    if not any([age, tenure, income, life_stage]):
        return None

    return {
        "owner_age":                 age,
        "length_of_residence_years": tenure,
        "est_household_income":      income,
        "life_stage":                life_stage,
    }


PROVIDERS = {
    "versium": _versium_lookup,
    # "smartystreets": _smarty_lookup,  # add more providers here
}


def _first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else ""


def _last_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[-1] if parts else ""


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(",", "").split(".")[0])
    except (ValueError, TypeError):
        return None


def _normalize_life_stage(raw: str | None, age: int | None, tenure: int | None) -> str | None:
    """Map provider life-stage labels to our canonical set; fall back to inference."""
    if raw:
        lowered = raw.lower().replace(" ", "_").replace("-", "_")
        if "new_mover" in lowered or "new_resident" in lowered:
            return "new_mover"
        if "retir" in lowered or "senior" in lowered:
            return "retiree"
        if "establish" in lowered or "long" in lowered:
            return "established"
        if lowered in ("new_mover", "established", "retiree", "other"):
            return lowered
    # Inference fallback when provider returns no life_stage but gave us age/tenure.
    if tenure is not None and tenure <= 2:
        return "new_mover"
    if age is not None and age >= 65:
        return "retiree"
    if tenure is not None and tenure >= 5:
        return "established"
    return "other" if any([age, tenure]) else None


def _passes_grade(row: dict) -> bool:
    if not DEMO_MIN_GRADE:
        return True
    return _GRADE_RANK.get(row.get("score_grade"), 0) >= _GRADE_RANK.get(DEMO_MIN_GRADE, 0)


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
