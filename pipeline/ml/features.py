"""
Feature engineering — turn a property row (or a stored snapshot payload) into a
fixed-order numeric feature vector. Pure: no DB, no third-party ML dependency.

Design goals
------------
* **Stable order.** `feature_names()` is deterministic so a model trained today can
  be applied tomorrow. One-hot vocabularies are fixed (derived from config), with an
  explicit ``__other`` bucket for unseen values.
* **Missing-aware.** Axon leads are enriched incrementally and some accounts never
  buy the Versium life-event block at all. Every optional field emits BOTH a value
  (0 when absent) AND a ``<name>__missing`` indicator, so the model can learn "this
  signal is simply unknown for this lead" instead of treating absent as a real 0.
  A model trained without life-event data therefore stays valid; if the account
  later buys that data, the same feature slots light up.

`snapshot_payload(row)` selects the raw fields to persist (decoupling storage from
engineering); `feature_vector(row)` produces the model input from either a live row
or a snapshot payload (same keys).
"""
from __future__ import annotations

import math
from datetime import date, datetime

from config import VERTICAL_WEIGHTS, CREDIT_GRADE_SCORES, LIFE_STAGE_SCORES

# Raw property columns persisted in lead_feature_snapshots.features. Keep this a
# superset of every field any feature reads, so re-engineering never needs a
# re-snapshot. JSON-serializable (dates are stringified in snapshot_payload).
SNAPSHOT_FIELDS = [
    "year_built", "square_footage", "lot_size", "garage_spaces",
    "estimated_value", "estimated_equity", "last_sale_date", "last_sale_price",
    "owner_occupied", "ownership_years", "zip_median_income", "permit_count_24mo",
    "neighborhood_value_ratio", "neighborhood_value_pctile",
    "has_pool", "has_cracked_slab",
    "last_storm_date", "hail_size_in", "storm_count_24mo",
    "owner_age", "length_of_residence_years", "est_household_income", "life_stage",
    "refi_date", "home_improvement_flag", "credit_rating", "has_children",
    "gardening_flag", "estimated_net_worth", "loan_to_value",
    "senior_in_household", "pets_flag", "decorating_flag", "credit_lines_count",
    "vertical", "lead_source",
]

# Continuous numerics: each emits a standardized value + a "<name>__missing" flag.
# (extractor, field) — the extractor maps the raw field to a float (or None).
_CONTINUOUS: list[tuple[str, str]] = [
    ("home_age", "year_built"),
    ("square_footage", "square_footage"),
    ("lot_size", "lot_size"),
    ("garage_spaces", "garage_spaces"),
    ("log_value", "estimated_value"),
    ("log_equity", "estimated_equity"),
    ("months_since_sale", "last_sale_date"),
    ("zip_median_income", "zip_median_income"),
    ("permit_count_24mo", "permit_count_24mo"),
    ("neighborhood_value_ratio", "neighborhood_value_ratio"),
    ("neighborhood_value_pctile", "neighborhood_value_pctile"),
    ("months_since_storm", "last_storm_date"),
    ("hail_size_in", "hail_size_in"),
    ("storm_count_24mo", "storm_count_24mo"),
    ("ownership_years", "ownership_years"),
    # Life-event / demographic block — frequently absent (no Versium). Missing
    # indicators let the model lean on the property signals above when these are 0.
    ("owner_age", "owner_age"),
    ("length_of_residence_years", "length_of_residence_years"),
    ("est_household_income", "est_household_income"),
    ("loan_to_value", "loan_to_value"),
    ("estimated_net_worth", "estimated_net_worth"),
    ("credit_lines_count", "credit_lines_count"),
    ("months_since_refi", "refi_date"),
]

# Binary flags: value in {0,1} plus a "<name>__missing" indicator when the source
# is None (so "unknown" is distinct from a confirmed "no").
_BINARY: list[tuple[str, str]] = [
    ("absentee", "owner_occupied"),   # inverted below: not owner-occupied => 1
    ("has_pool", "has_pool"),
    ("has_cracked_slab", "has_cracked_slab"),
    ("home_improvement_flag", "home_improvement_flag"),
    ("has_children", "has_children"),
    ("gardening_flag", "gardening_flag"),
    ("senior_in_household", "senior_in_household"),
    ("pets_flag", "pets_flag"),
    ("decorating_flag", "decorating_flag"),
]

# Ordinal lookups (value + missing indicator).
_ORDINAL: list[tuple[str, str, dict]] = [
    ("credit_rating", "credit_rating", CREDIT_GRADE_SCORES),
    ("life_stage", "life_stage", LIFE_STAGE_SCORES),
]

# Fixed one-hot vocabularies. Unseen values fall into "<feature>__other".
_VERTICAL_VOCAB = sorted(VERTICAL_WEIGHTS.keys())
_LEAD_SOURCE_VOCAB = ["pipeline", "csv_import", "facebook", "instagram", "manual", "referral"]

# Behavioral CRM features injected at scoring time (not persisted in the snapshot,
# since they evolve). Absent => 0, which is meaningful (no activity yet), so these
# carry NO missing indicator.
_BEHAVIORAL = ["crm_touches", "days_in_pipeline", "quotes_sent", "appointments"]


def _f(v) -> float | None:
    """Coerce to float, treating None/blank/unparseable as missing."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _months_since(v) -> float | None:
    """Whole months between a date (date/datetime/ISO string) and today."""
    if not v:
        return None
    d = None
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    elif isinstance(v, str):
        try:
            d = date.fromisoformat(v[:10])
        except ValueError:
            return None
    if d is None:
        return None
    return max(0.0, (date.today() - d).days / 30.44)


def _continuous_value(name: str, field: str, row: dict) -> float | None:
    """Raw (pre-standardization) value for a continuous feature, or None if missing."""
    raw = row.get(field)
    if name == "home_age":
        yb = _f(raw)
        return (date.today().year - yb) if yb else None
    if name in ("months_since_sale", "months_since_storm", "months_since_refi"):
        return _months_since(raw)
    if name == "log_value" or name == "log_equity":
        val = _f(raw)
        return math.log1p(val) if val and val > 0 else None
    return _f(raw)


def feature_names() -> list[str]:
    """The fixed, ordered list of feature names the model is trained/scored on."""
    names: list[str] = []
    for name, _ in _CONTINUOUS:
        names.append(name)
        names.append(f"{name}__missing")
    for name, _ in _BINARY:
        names.append(name)
        names.append(f"{name}__missing")
    for name, _, _ in _ORDINAL:
        names.append(name)
        names.append(f"{name}__missing")
    for v in _VERTICAL_VOCAB:
        names.append(f"vertical__{v}")
    names.append("vertical__other")
    for s in _LEAD_SOURCE_VOCAB:
        names.append(f"lead_source__{s}")
    names.append("lead_source__other")
    names.extend(_BEHAVIORAL)
    return names


def feature_dict(row: dict) -> dict[str, float]:
    """Map a property row / snapshot payload to {feature_name: value}."""
    out: dict[str, float] = {}

    for name, field in _CONTINUOUS:
        v = _continuous_value(name, field, row)
        out[name] = v if v is not None else 0.0
        out[f"{name}__missing"] = 0.0 if v is not None else 1.0

    for name, field in _BINARY:
        raw = row.get(field)
        if raw is None:
            out[name] = 0.0
            out[f"{name}__missing"] = 1.0
        else:
            b = bool(raw)
            if name == "absentee":          # owner_occupied False => absentee 1
                b = (raw is False) or (str(raw).lower() in ("false", "f", "0", "no"))
            out[name] = 1.0 if b else 0.0
            out[f"{name}__missing"] = 0.0

    for name, field, lookup in _ORDINAL:
        raw = row.get(field)
        key = str(raw).strip() if raw is not None else None
        if name == "credit_rating" and key:
            key = key.upper()
        if name == "life_stage" and key:
            key = key.lower()
        val = lookup.get(key) if key else None
        out[name] = val if val is not None else 0.0
        out[f"{name}__missing"] = 0.0 if val is not None else 1.0

    vertical = (row.get("vertical") or "").strip()
    matched = False
    for v in _VERTICAL_VOCAB:
        hit = 1.0 if vertical == v else 0.0
        out[f"vertical__{v}"] = hit
        matched = matched or bool(hit)
    out["vertical__other"] = 0.0 if (matched or not vertical) else 1.0

    source = (row.get("lead_source") or "").strip().lower()
    matched = False
    for s in _LEAD_SOURCE_VOCAB:
        hit = 1.0 if source == s else 0.0
        out[f"lead_source__{s}"] = hit
        matched = matched or bool(hit)
    out["lead_source__other"] = 0.0 if (matched or not source) else 1.0

    for b in _BEHAVIORAL:
        out[b] = _f(row.get(b)) or 0.0

    return out


def feature_vector(row: dict) -> list[float]:
    """Dense, fixed-order feature vector for `row` (aligned to feature_names())."""
    d = feature_dict(row)
    return [d[name] for name in feature_names()]


def snapshot_payload(row: dict) -> dict:
    """The raw, JSON-serializable subset of `row` persisted in a feature snapshot."""
    out: dict = {}
    for f in SNAPSHOT_FIELDS:
        v = row.get(f)
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        out[f] = v
    return out
