"""Frozen clock for the golden-file suite.

Four scoring-path modules call ``date.today()`` (`pipeline.scoring`,
`pipeline.equity`, `pipeline.reconcile`, `pipeline.hcad_enrichment`, plus
`pipeline.property`'s checked-stamp), so a golden score recomputed a month
later would silently drift — the sale-recency and home-age signals decay with
the wall clock. Every golden expectation is therefore computed at AS_OF, and
both the tests and scripts/regen_golden.py score under this freeze.

The freeze is a plain name-patch of each module's ``date`` binding with a
``date`` subclass whose ``today()`` is pinned. Instances produced by
``FrozenDate.fromisoformat`` are real ``date`` objects (subclass), so every
``isinstance(x, date)`` check and date subtraction in the patched modules
keeps working.

Layer B (the live contract tests) freezes the clock too, on purpose: the
vendors' *data* is what varies live; letting the clock vary as well would
smear time-decay drift into the vendor-drift measurement.
"""
import contextlib
from datetime import date

import pipeline.equity
import pipeline.hcad_enrichment
import pipeline.property
import pipeline.reconcile
import pipeline.scoring

# The date every golden expectation in expected/scores.json was computed at.
# Changing it changes the sale/age/equity signals of the whole corpus, so a
# bump must be paired with `python scripts/regen_golden.py --confirm` and the
# resulting diff reviewed like any other golden change.
AS_OF = date(2026, 8, 1)

CLOCK_MODULES = (
    pipeline.scoring,
    pipeline.equity,
    pipeline.reconcile,
    pipeline.hcad_enrichment,
    pipeline.property,
)


class FrozenDate(date):
    """``datetime.date`` with ``today()`` pinned to AS_OF."""

    @classmethod
    def today(cls):
        return cls(AS_OF.year, AS_OF.month, AS_OF.day)


@contextlib.contextmanager
def frozen_clock():
    """Patch ``date`` to FrozenDate in every scoring-path module, restoring on
    exit. Re-entrant: nested freezes just re-bind the same class."""
    originals = [(m, m.date) for m in CLOCK_MODULES]
    try:
        for module, _ in originals:
            module.date = FrozenDate
        yield FrozenDate
    finally:
        for module, original in originals:
            module.date = original
