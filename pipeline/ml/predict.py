"""
Inference — load the active model for a scope and score / explain a lead.

Model selection precedence (mirrors the plan):
    account-specific model  →  global pooled model  →  None (caller uses rules).

`score_and_store` is the batch entry point used by the scoring step; `explain_lead`
backs the score-explanation endpoint. Both no-op gracefully (return None / 0) when
no model has been trained yet, so the deterministic scorer always remains the floor.
"""
from __future__ import annotations

import logging

from config import GRADE_BANDS
from pipeline.ml import features, registry
from pipeline.ml.model import LogisticModel

log = logging.getLogger(__name__)

# Friendlier labels for the explanation UI; unmapped features fall back to a
# title-cased name. The "__missing" indicators are hidden from the user-facing
# breakdown (they carry little narrative value).
_LABELS = {
    "home_age": "Home age",
    "log_value": "Home value",
    "log_equity": "Home equity",
    "months_since_sale": "Recent sale",
    "months_since_storm": "Recent storm",
    "months_since_refi": "Recent refinance",
    "zip_median_income": "Area income",
    "neighborhood_value_ratio": "Neighborhood value",
    "neighborhood_value_pctile": "Neighborhood rank",
    "permit_count_24mo": "Permit activity",
    "storm_count_24mo": "Storm activity",
    "garage_spaces": "Garage space",
    "ownership_years": "Ownership tenure",
    "owner_age": "Owner age",
    "est_household_income": "Household income",
    "loan_to_value": "Loan-to-value",
    "credit_rating": "Credit quality",
    "life_stage": "Life stage",
    "has_pool": "Pool present",
    "has_cracked_slab": "Cracked slab",
    "home_improvement_flag": "Home-improvement buyer",
    "has_children": "Children in home",
    "gardening_flag": "Gardening interest",
    "absentee": "Absentee owner",
    "crm_touches": "Outreach so far",
    "days_in_pipeline": "Days in pipeline",
    "quotes_sent": "Quotes sent",
}


def _grade(prob: float) -> str:
    score = prob * 100
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return "D"


def load_model(conn, account_id: int) -> tuple[int, LogisticModel] | None:
    """Active account model if present, else the global pooled model, else None."""
    return (registry.load_active(conn, registry.account_scope(account_id))
            or registry.load_active(conn, registry.global_scope()))


def surface_ready(conn, account_id: int) -> bool:
    """Whether an account has enough labeled outcomes for the learned score to be
    shown to its users (config.ML_MIN_OUTCOMES_TO_SURFACE). Below the threshold
    the model keeps training/scoring silently, but user-facing surfaces keep the
    deterministic heuristic only, so small accounts never see model noise."""
    from config import ML_MIN_OUTCOMES_TO_SURFACE
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM lead_feature_snapshots "
            "WHERE account_id = %s AND outcome IS NOT NULL",
            (account_id,),
        )
        (labeled,) = cur.fetchone()
    return (labeled or 0) >= ML_MIN_OUTCOMES_TO_SURFACE


def predict_row(model: LogisticModel, row: dict) -> float:
    return model.predict_proba(features.feature_vector(row))


def explain(model: LogisticModel, version_id: int, row: dict) -> dict:
    """Per-feature breakdown of a lead's learned conversion probability."""
    prob = predict_row(model, row)
    contribs = model.contributions(features.feature_vector(row))
    factors = []
    for name, contribution in contribs.items():
        if name.endswith("__missing") or abs(contribution) < 1e-9:
            continue
        factors.append({
            "key": name,
            "label": _LABELS.get(name, name.replace("_", " ").title()),
            "contribution": round(contribution, 4),
        })
    factors.sort(key=lambda f: f["contribution"], reverse=True)
    top_drivers = [f["key"] for f in factors[:3] if f["contribution"] > 0]
    return {
        "ml_conversion_prob": round(prob, 4),
        "ml_grade": _grade(prob),
        "ml_model_version": version_id,
        "ml_factors": factors,
        "ml_top_drivers": top_drivers,
    }


def score_and_store(conn, account_id: int, rows: list[dict]) -> int:
    """Compute the learned probability for each lead and persist it on properties.
    Returns the number of rows updated. No-op (0) when no model is available."""
    loaded = load_model(conn, account_id)
    if not loaded:
        return 0
    version_id, model = loaded
    updates = [
        (model.predict_proba(features.feature_vector(r)), version_id, r["id"], account_id)
        for r in rows if r.get("id") is not None
    ]
    if not updates:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE properties SET ml_conversion_prob = %s, ml_model_version = %s "
            "WHERE id = %s AND account_id = %s",
            updates,
        )
    conn.commit()
    return len(updates)
