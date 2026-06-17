"""
Evaluation metrics — pure functions over (labels, predicted probabilities).

ROC-AUC and lift@top-decile are the two that matter for lead scoring: AUC measures
ranking quality overall, and lift@decile answers the business question directly —
"do the leads my model ranks in the top 10% actually convert above base rate?"
"""
from __future__ import annotations


def roc_auc(y: list[int], p: list[float]) -> float | None:
    """AUC via the Mann–Whitney U rank-sum (ties handled with average ranks)."""
    pos = sum(1 for v in y if v == 1)
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return None
    order = sorted(range(len(p)), key=lambda i: p[i])
    ranks = [0.0] * len(p)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and p[order[j + 1]] == p[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0   # 1-based average rank for the tie group
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    sum_pos = sum(ranks[i] for i in range(len(y)) if y[i] == 1)
    return (sum_pos - pos * (pos + 1) / 2.0) / (pos * neg)


def lift_at_decile(y: list[int], p: list[float], frac: float = 0.1) -> float | None:
    """Conversion rate among the top `frac` highest-scored, divided by base rate."""
    n = len(y)
    base = (sum(y) / n) if n else 0
    if n == 0 or base == 0:
        return None
    k = max(1, int(round(n * frac)))
    top = sorted(range(n), key=lambda i: p[i], reverse=True)[:k]
    top_rate = sum(y[i] for i in top) / k
    return top_rate / base


def brier(y: list[int], p: list[float]) -> float | None:
    """Mean squared error of probabilities — calibration + sharpness."""
    if not y:
        return None
    return sum((p[i] - y[i]) ** 2 for i in range(len(y))) / len(y)


def evaluate(y: list[int], p: list[float]) -> dict:
    return {
        "n": len(y),
        "pos_rate": round(sum(y) / len(y), 4) if y else None,
        "roc_auc": _r(roc_auc(y, p)),
        "lift_decile": _r(lift_at_decile(y, p)),
        "brier": _r(brier(y, p)),
    }


def _r(v):
    return round(v, 4) if isinstance(v, float) else v
