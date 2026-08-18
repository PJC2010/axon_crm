"""Layer A (synthetic) — pin GRADE_BANDS inclusivity at every band edge.

These are the tests that catch an off-by-one in a refactor. Two levels:

* ``_grade`` called with exact literals pins the band rule itself:
  A >= 75, B >= 55, C >= 35, D below — every threshold is INCLUSIVE of the
  grade above it.

* Six synthetic boundary rows drive the full ``_compute_score`` engine to a
  composite at each edge (34.9 / 35.0 / 54.9 / 55.0 / 74.9 / 75.0), pinning
  the engine + bands together. Factor values are injected directly — no
  vendor payloads (the point is the arithmetic, not the cascade).

Rounding is pinned the way production stores it: ``round(score, 2)`` —
Python 3 round-half-even — applied by pipeline/scorer.py before the value is
written. The GRADE, however, is computed from the UNROUNDED float
(scoring._grade runs before any rounding), and float summation order matters
at a band edge: the "75.0" row below actually sums to 75.00008 and grades A,
while a row summing to 74.99999999999999 would *display* as 75.0 yet grade B.
The raw-float assertions pin that behavior explicitly, so a refactor that
reorders the weighted sum can't silently move a displayed-75.0 lead across
the A/B line.
"""
import pytest

import config
from pipeline.scoring import _compute_score, _grade

from tests.golden.clock import AS_OF


def _boundary_row(income, *, equity=100000, garage=2, permit=2, ratio=1.3):
    """A row whose non-income factors sit at exact signal values (1.0 or
    missing), with zip_median_income as the fine-grained dial: its signal is
    income/75000, so the composite is tunable in 0.00008-point steps."""
    return {
        "year_built": AS_OF.year - 20,      # age 20: inside the 15-30 sweet spot
        "last_sale_date": None,             # sale factor held at 0
        "estimated_equity": equity,
        "garage_spaces": garage,
        "permit_count_24mo": permit,
        "neighborhood_value_ratio": ratio,
        "zip_median_income": income,
    }


# (label, row kwargs, expected stored score, expected grade,
#  raw-float band the score must fall in)
BOUNDARY_CASES = [
    ("34.9", dict(income=23750, equity=None, garage=None, ratio=None), 34.9, "D"),
    ("35.0", dict(income=25000, equity=None, garage=None, ratio=None), 35.0, "C"),
    ("54.9", dict(income=11250, equity=None), 54.9, "C"),
    ("55.0", dict(income=12500, equity=None), 55.0, "B"),
    ("74.9", dict(income=36250), 74.9, "B"),
    ("75.0", dict(income=37501), 75.0, "A"),
]


class TestGradeBandInclusivity:
    """The band rule itself, at exact literals — no float accumulation."""

    @pytest.mark.parametrize("score,grade", [
        (100.0, "A"), (75.0, "A"),          # A is >= 75, inclusive
        (74.9, "B"), (55.0, "B"),           # B is >= 55, inclusive
        (54.9, "C"), (35.0, "C"),           # C is >= 35, inclusive
        (34.9, "D"), (0.0, "D"), (-1.0, "D"),
    ])
    def test_band_edges(self, score, grade):
        assert _grade(score) == grade

    def test_bands_match_config(self):
        # The literals above are meaningful only while config agrees.
        assert config.GRADE_BANDS == [(75, "A"), (55, "B"), (35, "C"), (0, "D")]


class TestEngineAtBoundaries:
    """Full engine on synthetic rows landing at each band edge."""

    @pytest.mark.parametrize("label,kwargs,expected,grade", BOUNDARY_CASES,
                             ids=[c[0] for c in BOUNDARY_CASES])
    def test_boundary_row(self, frozen, label, kwargs, expected, grade):
        raw = _compute_score(_boundary_row(**kwargs), config.DEFAULT_WEIGHTS)
        assert round(raw, 2) == expected
        assert _grade(raw) == grade

    def test_74_9_vs_75_0_is_the_a_line(self, frozen):
        """The acceptance-criteria pair: 74.9 -> B, 75.0 -> A."""
        below = _compute_score(_boundary_row(income=36250), config.DEFAULT_WEIGHTS)
        at = _compute_score(_boundary_row(income=37501), config.DEFAULT_WEIGHTS)
        assert (round(below, 2), _grade(below)) == (74.9, "B")
        assert (round(at, 2), _grade(at)) == (75.0, "A")
        # The raw floats sit strictly on opposite sides of the threshold —
        # this is what actually decides the grade, not the rounded display.
        assert below < 75.0 <= at
