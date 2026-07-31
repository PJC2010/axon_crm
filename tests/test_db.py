"""Tests for pipeline/db.py pure helpers (no database required)."""
import threading

import config
from pipeline.db import UpsertProbe, _record_upsert, clamp_garage_spaces


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


# ── UpsertProbe ───────────────────────────────────────────────────────────────

def test_recording_without_an_installed_probe_is_a_no_op():
    """The default path must stay free — no probe, nothing recorded, no error."""
    UpsertProbe.uninstall()
    _record_upsert(3, 100, 1.0)   # must not raise


def test_probe_accumulates_calls_groups_rows_and_seconds():
    probe = UpsertProbe.install()
    try:
        _record_upsert(4, 500, 1.25)
        _record_upsert(2, 250, 0.75)
        assert probe.read() == {"calls": 2, "groups": 6, "rows": 750, "seconds": 2.0}
    finally:
        UpsertProbe.uninstall()


def test_probe_reset_clears_counters_between_steps():
    probe = UpsertProbe.install()
    try:
        _record_upsert(4, 500, 1.0)
        probe.reset()
        _record_upsert(1, 10, 0.5)
        assert probe.read() == {"calls": 1, "groups": 1, "rows": 10, "seconds": 0.5}
    finally:
        UpsertProbe.uninstall()


def test_probe_reads_none_when_the_step_did_no_upserts():
    """Steps that never write (storm misses, skipped providers) omit the block."""
    probe = UpsertProbe.install()
    try:
        assert probe.read() is None
    finally:
        UpsertProbe.uninstall()


def test_probe_counters_are_isolated_per_thread():
    """APScheduler runs pipeline jobs in a pool — concurrent runs must not mix."""
    probe = UpsertProbe.install()
    other = {}

    def worker():
        # A second thread with its own probe must not see this thread's counters.
        UpsertProbe.install()
        _record_upsert(1, 7, 0.1)
        other["stats"] = UpsertProbe().read()
        UpsertProbe.uninstall()

    try:
        _record_upsert(5, 900, 3.0)
        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert other["stats"] == {"calls": 1, "groups": 1, "rows": 7, "seconds": 0.1}
        assert probe.read() == {"calls": 1, "groups": 5, "rows": 900, "seconds": 3.0}
    finally:
        UpsertProbe.uninstall()


def test_recording_in_a_thread_with_no_probe_is_a_no_op():
    UpsertProbe.install()
    errors = []

    def worker():
        try:
            _record_upsert(1, 1, 0.1)   # this thread never installed a probe
        except Exception as e:          # pragma: no cover - failure path
            errors.append(e)

    try:
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert not errors
    finally:
        UpsertProbe.uninstall()
