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
from datetime import date

from config import (
    ML_MIN_TRAINING_LABELS, ML_STALE_OPEN_DAYS, ML_L2, ML_LR, ML_EPOCHS,
    ML_MAX_TRAINING_ROWS, ML_MAX_FIT_ROWS,
)
from pipeline.ml import dataset, features, labels, metrics, registry, snapshot
from pipeline.ml.model import LogisticModel

log = logging.getLogger(__name__)


def _sort_key(example: dict):
    """Order examples by outcome time for the time split; undated sort last."""
    return labels.outcome_sort_key(example.get("outcome_at"))


def _subsample(rows: list[dict], max_rows: int) -> list[dict]:
    """Evenly-spaced subsample that preserves order (and so the time span).

    The trainer is full-batch gradient descent in pure Python: cost is
    epochs x rows x features, on one core, in the process that is also serving
    HTTP. Because each step averages its gradient over the batch, thinning the
    batch shifts the fitted coefficients far less than it cuts the runtime.
    Evenly-spaced indices (rather than a random draw) keep the class mix and the
    chronology of the window intact, and are deterministic across nights. Indices
    are computed proportionally rather than as a fixed `rows[::stride]`, so a set
    one row over the cap loses one row instead of half of them.
    """
    n = len(rows)
    if max_rows <= 0 or n <= max_rows:
        return rows
    return [rows[i * n // max_rows] for i in range(max_rows)]


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
        max_rows=ML_MAX_TRAINING_ROWS,
    )
    if source == "insufficient":
        return {"scope": scope, "trained": False, "reason": "insufficient_labeled_data",
                "n": len(examples)}

    names = features.feature_names()
    train, test = _split(examples)
    n_train = len(train)
    # Drop the caller's handle on the full set before building vectors: `train` and
    # `test` already reference every example dict we still need, and the row dicts
    # are the bulk of the footprint.
    del examples

    fit_rows = _subsample(train, ML_MAX_FIT_ROWS)
    n_fit = len(fit_rows)
    if n_fit < n_train:
        log.info("Scope %s fitting on %d of %d training row(s) (ML_MAX_FIT_ROWS)",
                 scope, n_fit, n_train)
    Xtr = [features.feature_vector(e["features"]) for e in fit_rows]
    ytr = [e["label"] for e in fit_rows]
    # `train` is `test` when _split fell back to evaluating on the full set, in
    # which case these names just drop a reference and the dicts stay alive.
    del fit_rows, train

    model = LogisticModel.fit(
        names, Xtr, ytr, l2=ML_L2, lr=ML_LR, epochs=ML_EPOCHS,
        metadata={"scope": scope, "source": source,
                  "trained_at": (now or date.today()).isoformat()},
    )
    del Xtr, ytr

    Xte = [features.feature_vector(e["features"]) for e in test]
    yte = [e["label"] for e in test]
    n_test = len(test)
    del test
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

    # n_train is what the model actually saw (post-subsample); n_train_available
    # is how much the window held, so a capped run is visible rather than silent.
    result = {"scope": scope, "trained": True, "promoted": promote,
              "metrics": m, "n_train": n_fit, "n_train_available": n_train,
              "n_test": n_test}
    if promote:
        version_id = registry.save_and_activate(
            conn, scope, account_id, model, m, n_fit, n_test)
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
