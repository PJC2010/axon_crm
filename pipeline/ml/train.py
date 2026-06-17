"""
Training orchestration — fit a model for a scope, evaluate on a leakage-safe
holdout, and promote it only if it beats the current champion.

`train_scope` does one scope (global or one account). `train_all` is what the
nightly scheduler calls: it backfills outcome labels, retrains the global pooled
model, then retrains any account that has enough of its own labeled data.

The time-based split (train on older outcomes, test on newer) is deliberate: a
random split would leak future information and flatter the metrics. We want the
realistic question — "trained on the past, do my top-ranked future leads convert?"
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from config import (
    ML_MIN_TRAINING_LABELS, ML_STALE_OPEN_DAYS, ML_L2, ML_LR, ML_EPOCHS,
)
from pipeline.ml import dataset, features, metrics, registry, snapshot
from pipeline.ml.model import LogisticModel

log = logging.getLogger(__name__)


def _sort_key(example: dict):
    """Order examples by outcome time for the time split; undated sort last."""
    v = example.get("outcome_at")
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v[:19])
        except ValueError:
            return datetime.max
    return datetime.max


def _split(examples: list[dict], test_frac: float = 0.2):
    """Time-based split; fall back to a tail split if timestamps are unusable."""
    ordered = sorted(examples, key=_sort_key)
    cut = max(1, int(len(ordered) * (1 - test_frac)))
    train, test = ordered[:cut], ordered[cut:]
    # Guard: a usable test fold needs both classes; otherwise evaluate on train.
    if not test or len({e["label"] for e in test}) < 2:
        return ordered, ordered
    return train, test


def train_scope(
    conn, account_id: int | None = None, *, now: date | None = None,
) -> dict:
    """Train + (conditionally) promote one scope. Returns a result/metrics dict."""
    scope = registry.global_scope() if account_id is None else registry.account_scope(account_id)
    examples, source = dataset.build_dataset(
        conn, account_id, min_examples=ML_MIN_TRAINING_LABELS,
        stale_open_days=ML_STALE_OPEN_DAYS, now=now,
    )
    if source == "insufficient":
        return {"scope": scope, "trained": False, "reason": "insufficient_labeled_data",
                "n": len(examples)}

    names = features.feature_names()
    train, test = _split(examples)
    Xtr = [features.feature_vector(e["features"]) for e in train]
    ytr = [e["label"] for e in train]
    model = LogisticModel.fit(
        names, Xtr, ytr, l2=ML_L2, lr=ML_LR, epochs=ML_EPOCHS,
        metadata={"scope": scope, "source": source,
                  "trained_at": (now or date.today()).isoformat()},
    )

    Xte = [features.feature_vector(e["features"]) for e in test]
    yte = [e["label"] for e in test]
    pte = [model.predict_proba(x) for x in Xte]
    m = metrics.evaluate(yte, pte)
    m["source"] = source

    # Champion/challenger: promote when there's no incumbent or we beat its AUC.
    incumbent = registry.active_metrics(conn, scope)
    challenger_auc = m.get("roc_auc")
    incumbent_auc = (incumbent or {}).get("roc_auc")
    promote = (
        incumbent is None
        or incumbent_auc is None
        or (challenger_auc is not None and challenger_auc >= incumbent_auc)
    )

    result = {"scope": scope, "trained": True, "promoted": promote,
              "metrics": m, "n_train": len(train), "n_test": len(test)}
    if promote:
        version_id = registry.save_and_activate(
            conn, scope, account_id, model, m, len(train), len(test))
        result["version_id"] = version_id
    else:
        log.info("Scope %s challenger AUC %s did not beat champion %s — kept champion",
                 scope, challenger_auc, incumbent_auc)
    return result


def train_all(conn, *, now: date | None = None) -> dict:
    """Nightly job: refresh labels, retrain global, then eligible per-account models."""
    snapshot.backfill_outcomes(conn, account_id=None, stale_open_days=ML_STALE_OPEN_DAYS, now=now)

    results = [train_scope(conn, None, now=now)]   # global pooled

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, COUNT(*) FROM lead_feature_snapshots "
            "WHERE outcome IS NOT NULL AND account_id IS NOT NULL "
            "GROUP BY account_id HAVING COUNT(*) >= %s",
            (ML_MIN_TRAINING_LABELS,),
        )
        account_ids = [r[0] for r in cur.fetchall()]

    for aid in account_ids:
        try:
            results.append(train_scope(conn, aid, now=now))
        except Exception:
            log.exception("Per-account training failed for account %s", aid)

    promoted = sum(1 for r in results if r.get("promoted"))
    log.info("Retrain complete: %d scope(s), %d promoted", len(results), promoted)
    return {"scopes": results, "promoted": promoted}
