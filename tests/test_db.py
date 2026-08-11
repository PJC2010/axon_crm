"""Tests for pipeline/db.py pure helpers (no database required)."""
import threading

import pytest

import config
from pipeline.db import (
    UpsertProbe, _record_upsert, clamp_garage_spaces, fetch_missing_any,
)


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


# ── fetch_missing_any ─────────────────────────────────────────────────────────
# The SQL is built by string interpolation from a caller-supplied field list, so
# these assert on the statement itself rather than on query results.

class _RecordingCursor:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.sink["sql"] = " ".join(sql.split())
        self.sink["params"] = list(params)

    def fetchall(self):
        return []


class _RecordingConn:
    def __init__(self):
        self.last = {}

    def cursor(self, **kwargs):
        return _RecordingCursor(self.last)


def _query(**kwargs) -> dict:
    conn = _RecordingConn()
    fetch_missing_any(conn, ["year_built", "owner_name"], 7, **kwargs)
    return conn.last


def test_unknown_column_is_rejected_before_it_reaches_sql():
    with pytest.raises(ValueError):
        fetch_missing_any(_RecordingConn(), ["year_built; DROP TABLE properties"], 7)


def test_query_is_always_scoped_to_the_account():
    assert "account_id = %s" in _query()["sql"]
    assert _query()["params"][0] == 7


def test_no_limit_means_no_order_by_or_limit_clause():
    """Existing callers' query plans must not change."""
    sql = _query()["sql"]
    assert "ORDER BY" not in sql
    assert "LIMIT" not in sql


def test_limit_orders_confirmed_buildings_then_emptiest():
    """A capped, paid run should spend its budget where a vendor is likeliest
    to answer (evidence of a building), then where it fills the most holes.
    Pure emptiest-first sent a 100-call sweep entirely into vacant land."""
    result = _query(limit=25)
    assert ("ORDER BY (COALESCE(year_built, 0) > 0 OR COALESCE(square_footage, 0) > 0) DESC, "
            "((year_built IS NULL)::int + (owner_name IS NULL)::int) DESC"
            in result["sql"])
    assert result["sql"].endswith("LIMIT %s")
    assert result["params"][-1] == 25


def test_building_evidence_is_tested_as_nonzero_not_non_null():
    """HCAD writes a vacant parcel's building_sqft as 0, not NULL, so an
    IS NOT NULL test is true for every HCAD-seeded row and ranks vacant land
    first — the exact failure this ordering exists to prevent."""
    sql = _query(limit=25)["sql"]
    assert "square_footage IS NOT NULL" not in sql
    assert "COALESCE(square_footage, 0) > 0" in sql


def test_no_situs_rows_never_become_paid_candidates():
    """"0 TRUXTON ST" is HCAD's convention for a parcel with no street address —
    unmatchable by every address-keyed vendor, so both fetchers exclude it."""
    from pipeline.db import fetch_missing_field
    assert "!~ '^0+(\\s|$)'" in _query()["sql"]
    conn = _RecordingConn()
    fetch_missing_field(conn, "contact_phone", 7)
    assert "!~ '^0+(\\s|$)'" in conn.last["sql"]


def test_limit_ordering_is_deterministic_across_ties():
    """Without a tiebreak, two rows with equal gaps could swap between pages and
    a resumed sweep would re-bill one while never reaching the other."""
    assert "DESC, id LIMIT" in _query(limit=10)["sql"]


def test_recheck_window_excludes_rows_asked_about_recently():
    result = _query(checked_flag="rentcast_checked", recheck_days=90)
    assert "make_interval(days => %s)" in result["sql"]
    assert result["params"][-1] == 90


def test_zero_recheck_days_asks_each_row_at_most_once():
    result = _query(checked_flag="rentcast_checked", recheck_days=0)
    assert "enrichment_flags->>%s IS NULL" in result["sql"]
    assert "make_interval" not in result["sql"]
