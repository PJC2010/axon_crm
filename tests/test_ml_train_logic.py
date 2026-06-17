"""Pure orchestration logic used by training (no DB): the leakage-safe time split
and the dataset usability gate."""
from datetime import datetime

from pipeline.ml import dataset
from pipeline.ml.train import _split, _sort_key


def _ex(label, when):
    return {"label": label, "outcome_at": when, "features": {}}


def test_split_is_time_ordered_train_before_test():
    examples = [
        _ex(1, "2024-01-01"), _ex(0, "2024-02-01"), _ex(1, "2024-03-01"),
        _ex(0, "2024-04-01"), _ex(1, "2024-05-01"), _ex(0, "2024-06-01"),
        _ex(1, "2024-07-01"), _ex(0, "2024-08-01"), _ex(1, "2024-09-01"),
        _ex(0, "2024-10-01"),
    ]
    train, test = _split(examples, test_frac=0.2)
    # Every training outcome precedes every test outcome (no future leakage).
    assert max(_sort_key(e) for e in train) <= min(_sort_key(e) for e in test)
    assert len(test) >= 1


def test_split_falls_back_when_test_fold_single_class():
    # Last fold would be all wins → fall back to evaluating on the full set.
    examples = [_ex(0, "2024-01-01"), _ex(0, "2024-02-01"),
                _ex(1, "2024-03-01"), _ex(1, "2024-04-01")]
    train, test = _split(examples, test_frac=0.25)
    assert train is test or {e["label"] for e in test} == {0, 1}


def test_usable_requires_both_classes_and_min_count():
    both = [{"label": 1}] * 25 + [{"label": 0}] * 25
    assert dataset._usable(both, min_examples=40) is True
    assert dataset._usable(both, min_examples=80) is False          # too few
    one_class = [{"label": 1}] * 50
    assert dataset._usable(one_class, min_examples=40) is False      # single class


def test_sort_key_handles_missing_timestamp():
    # Undated examples sort last (datetime.max), never crash.
    assert _sort_key({"outcome_at": None}) == datetime.max
    assert _sort_key({"outcome_at": "not-a-date"}) == datetime.max
