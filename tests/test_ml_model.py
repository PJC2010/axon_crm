"""Pure-Python logistic regression + metrics: learning, calibration shape,
serialization round-trip, and an end-to-end train→predict on synthetic leads."""
import random

from pipeline.ml import features, metrics
from pipeline.ml.model import LogisticModel


def _synthetic(n=400, seed=1):
    """Two features; label driven by a known linear rule + noise."""
    rng = random.Random(seed)
    names = ["f0", "f1"]
    X, y = [], []
    for _ in range(n):
        a = rng.gauss(0, 1)
        b = rng.gauss(0, 1)
        z = 2.0 * a - 1.0 * b
        p = 1 / (1 + pow(2.718281828, -z))
        X.append([a, b])
        y.append(1 if rng.random() < p else 0)
    return names, X, y


def test_model_learns_signal():
    names, X, y = _synthetic()
    model = LogisticModel.fit(names, X, y, epochs=400, lr=0.3)
    p = [model.predict_proba(x) for x in X]
    auc = metrics.roc_auc(y, p)
    assert auc is not None and auc > 0.8
    # Coefficient signs recover the generating rule (f0 positive, f1 negative).
    assert model.coef[0] > 0 > model.coef[1]


def test_probabilities_in_range():
    names, X, y = _synthetic(n=100)
    model = LogisticModel.fit(names, X, y, epochs=100)
    for x in X:
        assert 0.0 <= model.predict_proba(x) <= 1.0


def test_serialization_round_trip():
    names, X, y = _synthetic(n=100)
    model = LogisticModel.fit(names, X, y, epochs=50)
    restored = LogisticModel.from_dict(model.to_dict())
    for x in X[:20]:
        assert abs(model.predict_proba(x) - restored.predict_proba(x)) < 1e-12


def test_zero_variance_feature_is_safe():
    # A constant column must not cause a divide-by-zero in standardization.
    names = ["const", "real"]
    X = [[1.0, float(i % 2)] for i in range(40)]
    y = [i % 2 for i in range(40)]
    model = LogisticModel.fit(names, X, y, epochs=50)
    assert 0.0 <= model.predict_proba([1.0, 1.0]) <= 1.0


def test_metrics_lift_and_auc_edges():
    # Perfect ranking → AUC 1.0 and positive lift.
    y = [0, 0, 1, 1]
    p = [0.1, 0.2, 0.8, 0.9]
    assert metrics.roc_auc(y, p) == 1.0
    assert metrics.lift_at_decile(y, p, frac=0.5) >= 1.0
    # Single-class is undefined, not a crash.
    assert metrics.roc_auc([1, 1, 1], [0.5, 0.6, 0.7]) is None


def test_end_to_end_on_lead_shaped_rows():
    """Train on realistic lead dicts via the production feature extractor: leads with
    equity + recent sale + good credit convert; the opposite don't."""
    rng = random.Random(7)
    names = features.feature_names()
    X, y = [], []
    for _ in range(300):
        good = rng.random() < 0.5
        row = {
            "year_built": 2000,
            "estimated_equity": 150000 if good else 5000,
            "last_sale_date": "2024-06-01" if good else None,
            "credit_rating": "A" if good else "D",
            "vertical": "roofing",
            "lead_source": "pipeline",
        }
        X.append(features.feature_vector(row))
        # Noisy label so the model must generalize, not memorize.
        y.append(1 if (good ^ (rng.random() < 0.15)) else 0)

    model = LogisticModel.fit(names, X, y, l2=1.0, lr=0.2, epochs=300)
    p = [model.predict_proba(x) for x in X]
    auc = metrics.roc_auc(y, p)
    assert auc is not None and auc > 0.75

    # A clearly strong lead should outscore a clearly weak one.
    strong = features.feature_vector({
        "estimated_equity": 150000, "last_sale_date": "2024-06-01",
        "credit_rating": "A", "vertical": "roofing", "lead_source": "pipeline",
    })
    weak = features.feature_vector({
        "estimated_equity": 5000, "credit_rating": "D",
        "vertical": "roofing", "lead_source": "pipeline",
    })
    assert model.predict_proba(strong) > model.predict_proba(weak)
