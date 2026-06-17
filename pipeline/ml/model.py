"""
Dependency-free logistic-regression model.

Why pure Python (no scikit-learn/numpy as a hard dependency)?
* The repo already follows "degrade gracefully if a lib isn't installed"
  (see the uszipcode note in requirements.txt). For a linear model at Axon's
  per-tenant data scale (hundreds–thousands of leads) a hand-rolled, L2-regularized
  gradient-descent fit trains in milliseconds and needs nothing extra.
* It keeps prediction in-process and the model artifact a plain JSON blob (stored in
  model_versions.artifact), reinforcing the data-sovereignty story and making
  versioning/diffing trivial.
* The class boundary is deliberately the same shape a scikit-learn / LightGBM model
  would expose (`predict_proba`, `contributions`, `to_dict`/`from_dict`), so swapping
  in a gradient-boosted model later is a drop-in — train.py and predict.py don't
  change. That upgrade path is the one noted in the plan for higher data volumes.

The model outputs a probability and per-feature signed contributions (coefficient ×
standardized value), which map directly onto the existing score-explanation UI.
"""
from __future__ import annotations

import math


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class LogisticModel:
    def __init__(
        self,
        feature_names: list[str],
        mean: list[float],
        std: list[float],
        coef: list[float],
        intercept: float,
        *,
        algo: str = "logreg",
        metadata: dict | None = None,
    ):
        self.feature_names = feature_names
        self.mean = mean
        self.std = std
        self.coef = coef
        self.intercept = intercept
        self.algo = algo
        self.metadata = metadata or {}

    # ── Fit ───────────────────────────────────────────────────────────────────
    @classmethod
    def fit(
        cls,
        feature_names: list[str],
        X: list[list[float]],
        y: list[int],
        *,
        l2: float = 1.0,
        lr: float = 0.1,
        epochs: int = 600,
        metadata: dict | None = None,
    ) -> "LogisticModel":
        n = len(X)
        if n == 0:
            raise ValueError("cannot fit on an empty dataset")
        d = len(feature_names)

        # Standardize each column (zero-variance columns get std=1 => contribute 0).
        mean = [0.0] * d
        for row in X:
            for j in range(d):
                mean[j] += row[j]
        mean = [m / n for m in mean]
        var = [0.0] * d
        for row in X:
            for j in range(d):
                diff = row[j] - mean[j]
                var[j] += diff * diff
        std = [math.sqrt(v / n) or 1.0 for v in var]
        std = [s if s > 1e-9 else 1.0 for s in std]

        Xs = [[(row[j] - mean[j]) / std[j] for j in range(d)] for row in X]

        coef = [0.0] * d
        intercept = 0.0
        for _ in range(epochs):
            grad_w = [0.0] * d
            grad_b = 0.0
            for i in range(n):
                z = intercept + sum(coef[j] * Xs[i][j] for j in range(d))
                err = _sigmoid(z) - y[i]
                grad_b += err
                xi = Xs[i]
                for j in range(d):
                    grad_w[j] += err * xi[j]
            intercept -= lr * (grad_b / n)
            for j in range(d):
                # L2 regularization on weights only (not the intercept).
                coef[j] -= lr * (grad_w[j] / n + (l2 / n) * coef[j])

        return cls(feature_names, mean, std, coef, intercept,
                   algo="logreg", metadata=metadata)

    # ── Predict ───────────────────────────────────────────────────────────────
    def _standardize(self, x: list[float]) -> list[float]:
        return [(x[j] - self.mean[j]) / self.std[j] for j in range(len(self.coef))]

    def predict_proba(self, x: list[float]) -> float:
        xs = self._standardize(x)
        z = self.intercept + sum(self.coef[j] * xs[j] for j in range(len(self.coef)))
        return _sigmoid(z)

    def contributions(self, x: list[float]) -> dict[str, float]:
        """Signed log-odds contribution of each feature (coef × standardized value)."""
        xs = self._standardize(x)
        return {self.feature_names[j]: self.coef[j] * xs[j] for j in range(len(self.coef))}

    # ── Serialization (JSON-safe; stored in model_versions.artifact) ──────────
    def to_dict(self) -> dict:
        return {
            "algo": self.algo,
            "feature_names": self.feature_names,
            "mean": self.mean,
            "std": self.std,
            "coef": self.coef,
            "intercept": self.intercept,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LogisticModel":
        return cls(
            d["feature_names"], d["mean"], d["std"], d["coef"], d["intercept"],
            algo=d.get("algo", "logreg"), metadata=d.get("metadata", {}),
        )
