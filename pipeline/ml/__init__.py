"""
Predictive lead-scoring package.

Layers, mirroring the repo's "pure math, thin DB wrapper" convention:

  Pure (DB-free, unit-tested):
    features.py — property row → numeric feature vector (missing-aware)
    labels.py   — property/outcome row → conversion label (1/0/None)
    model.py    — dependency-free logistic regression + JSON (de)serialization
    metrics.py  — ROC-AUC, lift@decile, Brier score

  DB-aware (thin orchestration over the pure layer):
    registry.py — model_versions table (save/activate/load, champion-challenger)
    dataset.py  — assemble labeled training rows from snapshots (+ backfill)
    snapshot.py — write point-in-time feature snapshots; backfill outcomes
    predict.py  — load the active model, score & explain a lead
    train.py    — fit, evaluate on a time-based holdout, promote if it wins

The learned scorer is selected behind the SCORER_MODE seam (config.py); when no
model is trained yet, every entry point falls back to the deterministic scorer in
pipeline/scoring.py, so the system always produces a score.
"""
