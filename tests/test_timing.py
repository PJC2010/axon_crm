"""
Tests for pipeline/timing.py — per-step pipeline timing.

Uses a fake clock throughout so the tests are deterministic and never sleep.
These must pass without a database connection.
"""
import pytest

from pipeline.timing import StepTimer, _sec_per_1k, _fmt_upsert


class FakeClock:
    """Monotonic clock the test drives by hand."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeProbe:
    """Stands in for the DB upsert probe: counts resets, returns canned stats."""

    def __init__(self, stats=None):
        self.resets = 0
        self.reads = 0
        self._stats = stats

    def reset(self):
        self.resets += 1

    def read(self):
        self.reads += 1
        return self._stats


# ── Basic recording ───────────────────────────────────────────────────────────

def test_records_elapsed_seconds_per_step():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed"):
        clock.advance(12.5)

    assert timer.steps() == [
        {"step": "seed", "seconds": 12.5, "rows": None, "sec_per_1k": None}
    ]


def test_preserves_step_order():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    for name, secs in [("seed", 3.0), ("census", 1.0), ("geocode", 2.0)]:
        with timer.step(name):
            clock.advance(secs)

    assert [e["step"] for e in timer.steps()] == ["seed", "census", "geocode"]


def test_rows_are_recorded_from_the_handle():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed") as s:
        clock.advance(10.0)
        s.rows = 5000

    entry = timer.steps()[0]
    assert entry["rows"] == 5000
    assert entry["sec_per_1k"] == 2.0


# ── The property that matters most for diagnosing a slow run ──────────────────

def test_step_that_raises_still_records_its_duration():
    """A run that dies partway is exactly when the numbers matter most."""
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with pytest.raises(RuntimeError):
        with timer.step("property"):
            clock.advance(42.0)
            raise RuntimeError("provider blew up")

    assert timer.steps() == [
        {"step": "property", "seconds": 42.0, "rows": None, "sec_per_1k": None}
    ]


def test_rows_set_before_a_raise_are_kept():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with pytest.raises(ValueError):
        with timer.step("hcad") as s:
            s.rows = 250
            clock.advance(5.0)
            raise ValueError("boom")

    assert timer.steps()[0]["rows"] == 250


# ── sec_per_1k math and division safety ───────────────────────────────────────

@pytest.mark.parametrize("elapsed,rows,expected", [
    (10.0, 5000, 2.0),        # 10s over 5k rows = 2s per 1k
    (1.0, 1000, 1.0),
    (0.5, 250, 2.0),
    (30.0, 15243, 1.968),     # realistic Houston-ZIP shape, rounded to 3dp
])
def test_sec_per_1k_math(elapsed, rows, expected):
    assert _sec_per_1k(elapsed, rows) == expected


@pytest.mark.parametrize("rows", [None, 0, -1])
def test_sec_per_1k_is_none_without_a_meaningful_row_count(rows):
    """Guards the division: steps that report no rows must not blow up."""
    assert _sec_per_1k(10.0, rows) is None


def test_zero_row_step_does_not_raise():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("storm") as s:
        clock.advance(1.0)
        s.rows = 0

    assert timer.steps()[0]["sec_per_1k"] is None


# ── slowest ranking ───────────────────────────────────────────────────────────

def test_slowest_ranks_by_seconds_descending():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    for name, secs in [("seed", 5.0), ("census", 90.0), ("geocode", 1.0),
                       ("hcad", 40.0), ("score", 12.0)]:
        with timer.step(name):
            clock.advance(secs)

    assert timer.slowest() == ["census", "hcad", "score"]
    assert timer.slowest(2) == ["census", "hcad"]


def test_slowest_on_empty_timer_is_empty():
    assert StepTimer(clock=FakeClock()).slowest() == []


# ── as_dict ───────────────────────────────────────────────────────────────────

def test_as_dict_shape():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed") as s:
        clock.advance(20.0)
        s.rows = 10000
    with timer.step("census") as s:
        clock.advance(80.0)
        s.rows = 10000

    out = timer.as_dict()
    assert out["total_seconds"] == 100.0
    assert out["step_seconds"] == 100.0
    assert out["slowest"] == ["census", "seed"]
    assert [e["step"] for e in out["steps"]] == ["seed", "census"]
    assert out["steps"][1]["sec_per_1k"] == 8.0


def test_total_seconds_is_wall_clock_not_the_step_sum():
    """The gap between the two is itself a signal (GC, swap, CPU contention)."""
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed"):
        clock.advance(10.0)
    clock.advance(25.0)          # time spent outside any step
    with timer.step("score"):
        clock.advance(5.0)

    out = timer.as_dict()
    assert out["step_seconds"] == 15.0
    assert out["total_seconds"] == 40.0


# ── probe wiring ──────────────────────────────────────────────────────────────

def test_probe_is_reset_at_step_start_and_read_at_step_end():
    clock = FakeClock()
    probe = FakeProbe(stats={"calls": 2, "groups": 37, "rows": 900, "seconds": 4.0})
    timer = StepTimer(clock=clock, probe=probe)

    with timer.step("seed"):
        clock.advance(1.0)

    assert probe.resets == 1
    assert probe.reads == 1
    assert timer.steps()[0]["upsert"] == {
        "calls": 2, "groups": 37, "rows": 900, "seconds": 4.0
    }


def test_probe_is_reset_per_step_so_counters_do_not_accumulate():
    clock = FakeClock()
    probe = FakeProbe(stats={"calls": 1, "groups": 1, "rows": 1, "seconds": 0.1})
    timer = StepTimer(clock=clock, probe=probe)

    for name in ("seed", "census", "score"):
        with timer.step(name):
            clock.advance(1.0)

    assert probe.resets == 3
    assert probe.reads == 3


def test_probe_returning_none_omits_the_upsert_key():
    clock = FakeClock()
    timer = StepTimer(clock=clock, probe=FakeProbe(stats=None))

    with timer.step("storm"):
        clock.advance(1.0)

    assert "upsert" not in timer.steps()[0]


def test_probe_is_read_even_when_the_step_raises():
    clock = FakeClock()
    probe = FakeProbe(stats={"calls": 1, "groups": 4, "rows": 10, "seconds": 0.5})
    timer = StepTimer(clock=clock, probe=probe)

    with pytest.raises(RuntimeError):
        with timer.step("seed"):
            clock.advance(2.0)
            raise RuntimeError("boom")

    assert timer.steps()[0]["upsert"]["groups"] == 4


def test_no_probe_means_no_upsert_key():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed"):
        clock.advance(1.0)

    assert "upsert" not in timer.steps()[0]


# ── format_table ──────────────────────────────────────────────────────────────

def test_format_table_includes_every_step_and_the_total():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed") as s:
        clock.advance(30.0)
        s.rows = 15243
    with timer.step("census") as s:
        clock.advance(90.0)
        s.rows = 15243

    table = timer.format_table(title="ZIP 77396")
    assert "ZIP 77396" in table
    assert "seed" in table and "census" in table
    assert "15,243" in table          # thousands separator
    assert "TOTAL" in table
    assert "slowest: census, seed" in table


def test_format_table_flags_a_large_unaccounted_gap():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed"):
        clock.advance(5.0)
    clock.advance(60.0)              # not inside any step

    assert "(unaccounted)" in timer.format_table()


def test_format_table_omits_the_gap_line_when_steps_account_for_the_time():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("seed"):
        clock.advance(5.0)

    assert "(unaccounted)" not in timer.format_table()


def test_format_table_on_empty_timer():
    assert "no steps recorded" in StepTimer(clock=FakeClock()).format_table()


def test_format_table_renders_missing_rows_as_a_dash():
    clock = FakeClock()
    timer = StepTimer(clock=clock)

    with timer.step("signals"):
        clock.advance(1.0)

    assert "—" in timer.format_table()


# ── upsert formatting ─────────────────────────────────────────────────────────

def test_fmt_upsert_renders_counters():
    out = _fmt_upsert({"calls": 3, "groups": 128, "rows": 15243, "seconds": 42.5})
    assert "3 calls" in out
    assert "128 groups" in out
    assert "15,243 rows" in out
    assert "42.50s" in out


@pytest.mark.parametrize("stats", [None, {}])
def test_fmt_upsert_is_blank_without_stats(stats):
    assert _fmt_upsert(stats) == ""
