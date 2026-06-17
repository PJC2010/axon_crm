"""
Predictive-model management & insights.

GET  /api/ml/status          — scorer mode, active models, labeled-data counts
POST /api/ml/retrain         — (owner) backfill labels + retrain this account's model
GET  /api/ml/insights/leads  — account-level predictive findings + pipeline forecast

The numeric prediction is computed in-process (pipeline/ml); these endpoints are the
thin HTTP surface over it, scoped to the caller's account like the rest of the API.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user, require_owner
from config import SCORER_MODE, ML_MIN_TRAINING_LABELS, ML_STALE_OPEN_DAYS
from pipeline.ml import registry

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/ml/status")
def ml_status(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    account_id = user["account_id"]
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE outcome IS NOT NULL), "
            "       COUNT(*) FILTER (WHERE outcome = 1), "
            "       COUNT(*) "
            "FROM lead_feature_snapshots WHERE account_id = %s",
            (account_id,),
        )
        labeled, won, total = cur.fetchone()

    account_model = registry.active_metrics(db, registry.account_scope(account_id))
    global_model = registry.active_metrics(db, registry.global_scope())
    active_scope = "account" if account_model else ("global" if global_model else None)

    return {
        "scorer_mode": SCORER_MODE,
        "min_labels_to_train": ML_MIN_TRAINING_LABELS,
        "snapshots_total": total,
        "snapshots_labeled": labeled,
        "snapshots_won": won,
        "ready_to_train": (labeled or 0) >= ML_MIN_TRAINING_LABELS,
        "active_model_scope": active_scope,
        "account_model_metrics": account_model,
        "global_model_metrics": global_model,
    }


@router.post("/ml/retrain")
def ml_retrain(db: PGConn = Depends(get_db), user: dict = Depends(require_owner)):
    """Backfill outcome labels and retrain this account's model (and the global
    pooled model if one doesn't exist yet). Synchronous — fine at per-tenant scale."""
    account_id = user["account_id"]
    from pipeline.ml import snapshot, train

    snapshot.backfill_outcomes(db, account_id=account_id, stale_open_days=ML_STALE_OPEN_DAYS)
    results = [train.train_scope(db, account_id)]
    if registry.active_metrics(db, registry.global_scope()) is None:
        snapshot.backfill_outcomes(db, account_id=None, stale_open_days=ML_STALE_OPEN_DAYS)
        results.append(train.train_scope(db, None))
    return {"results": results}


@router.get("/ml/insights/leads")
def ml_lead_insights(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Predictive findings for the business owner, derived from learned probabilities
    cross-referenced with pipeline activity. Returns Insight-shaped cards plus a
    revenue forecast (Σ probability × estimated job value over open leads)."""
    account_id = user["account_id"]
    insights: list[dict] = []

    with db.cursor() as cur:
        # High-probability leads that have never been worked.
        cur.execute(
            """
            SELECT id, address, ml_conversion_prob, estimated_job_value
            FROM properties p
            WHERE account_id = %s AND archived_at IS NULL
              AND ml_conversion_prob IS NOT NULL
              AND status IN ('new', 'contacted')
              AND ml_conversion_prob >= 0.6
              AND NOT EXISTS (SELECT 1 FROM contact_history h WHERE h.property_id = p.id)
            ORDER BY ml_conversion_prob DESC
            LIMIT 25
            """,
            (account_id,),
        )
        hot_untouched = dict_fetchall(cur)

        # Pipeline forecast over open, model-scored leads.
        cur.execute(
            """
            SELECT COALESCE(SUM(ml_conversion_prob * COALESCE(estimated_job_value, 0)), 0),
                   COUNT(*)
            FROM properties
            WHERE account_id = %s AND archived_at IS NULL
              AND ml_conversion_prob IS NOT NULL
              AND status NOT IN ('won', 'lost', 'not_interested')
            """,
            (account_id,),
        )
        forecast_value, open_scored = cur.fetchone()

    if hot_untouched:
        insights.append({
            "id": "hot_untouched_leads",
            "severity": "action",
            "category": "conversion",
            "title": f"{len(hot_untouched)} high-probability leads not yet worked",
            "message": (f"{len(hot_untouched)} leads the model predicts are most likely to "
                        f"close have no logged outreach yet."),
            "recommended_action": "Prioritize these in today's call list before they cool off.",
            "supporting_metric": {
                "label": "Top untouched lead",
                "value": f"{round((hot_untouched[0]['ml_conversion_prob'] or 0) * 100)}% likely",
            },
            "lead_ids": [r["id"] for r in hot_untouched],
        })

    return {
        "scorer_mode": SCORER_MODE,
        "forecast_value": round(float(forecast_value or 0), 2),
        "open_scored_leads": open_scored,
        "insights": insights,
    }
