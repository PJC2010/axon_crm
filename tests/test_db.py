"""Tests for pipeline/db.py pure helpers (no database required)."""
import config
from pipeline.db import clamp_garage_spaces


def test_clamp_caps_implausible_counts():
    # Regression: HCAD square footage leaking in as a "space" count.
    assert clamp_garage_spaces(462) == config.MAX_GARAGE_SPACES


def test_clamp_leaves_plausible_counts_alone():
    assert clamp_garage_spaces(1) == 1
    assert clamp_garage_spaces(2) == 2
    assert clamp_garage_spaces(config.MAX_GARAGE_SPACES) == config.MAX_GARAGE_SPACES


def test_clamp_passes_through_none_and_non_numeric():
    assert clamp_garage_spaces(None) is None
    assert clamp_garage_spaces("2") == "2"


def test_clamp_floors_negatives_at_zero():
    assert clamp_garage_spaces(-3) == 0
