"""Tests for pipeline/addr.py — shared address normalization."""
from pipeline.addr import normalize
from pipeline import hcad_store


def test_lowercase_and_strip_punctuation():
    assert normalize("123 Main St.") == "123 main st"


def test_collapses_whitespace():
    assert normalize("123   Main    St") == "123 main st"


def test_empty_and_none_safe():
    assert normalize("") == ""
    assert normalize(None) == ""


def test_hcad_store_uses_shared_normalize():
    # hcad_store re-exports the same function (single source of truth).
    assert hcad_store.normalize("456 Oak Ave!") == normalize("456 Oak Ave!")
