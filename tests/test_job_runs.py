"""Tests for api/job_runs.py — the scheduler job-run ledger (migration 0088).

The contract: a tracked tick always leaves a row saying what happened, and the
ledger never changes what the tick does. It must not raise into the tick, must
not swallow the tick's exceptions, and must not be masked by the tick's own
``except Exception`` — which is why ``skip()`` raises a BaseException and
``failed()`` exists. Fake-conn style, no live DB.
"""
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal

import psycopg2
import pytest

from api import job_runs
from tests.fakeconn import Conn, sql_matching

OPEN = "INSERT INTO scheduler_job_runs"
CLOSE = "UPDATE scheduler_job_runs SET finished_at"


@pytest.fixture(autouse=True)
def _clean_registry():
    """The ids the tests below register must not leak into the registry the
    Ops tab classifies with."""
    before = set(job_runs.TRACKED_JOB_IDS)
    yield
    job_runs.TRACKED_JOB_IDS.intersection_update(before)


@pytest.fixture
def ledger(monkeypatch):
    """Every psycopg2.connect() hands back a scripted fake that answers the
    ledger's INSERT with id 17."""
    conns = []

    def _factory(*a, **k):
        conn = Conn(_factory.script)
        conns.append(conn)
        return conn

    _factory.script = [(OPEN, (["id"], [(17,)]))]
    monkeypatch.setattr(psycopg2, "connect", _factory)
    return type("Handle", (), {"conns": conns, "script": _factory.script})()


def _opened(handle):
    (_, params), = sql_matching(handle.conns[0], OPEN)
    return params


def _closes(handle):
    return [p for c in handle.conns for _, p in sql_matching(c, CLOSE)]


def _closed(handle):
    closes = _closes(handle)
    assert len(closes) == 1, closes
    return closes[0]


class TestOutcomes:
    def test_ok_run_opens_then_closes_the_row(self, ledger):
        @job_runs.tracked("t_ok")
        def tick():
            return "did it"

        assert tick() == "did it"
        job_id, host = _opened(ledger)
        assert job_id == "t_ok" and isinstance(host, str) and host
        status, error, detail, row_id = _closed(ledger)
        assert (status, error, row_id) == ("ok", None, 17)
        assert detail.adapted == {}
        # One short-lived connection per write, none held across the tick.
        assert len(ledger.conns) == 2 and all(c.closed for c in ledger.conns)

    def test_escaping_exception_is_recorded_and_re_raised(self, ledger):
        @job_runs.tracked("t_boom")
        def tick():
            raise RuntimeError("db gone")

        with pytest.raises(RuntimeError):
            tick()
        status, error, _, _ = _closed(ledger)
        assert status == "error" and error == "RuntimeError: db gone"

    def test_skip_closes_as_skipped_and_returns_the_result(self, ledger):
        @job_runs.tracked("t_skip")
        def tick():
            job_runs.skip("a run is in progress", result=0)
            raise AssertionError("unreachable")

        assert tick() == 0
        status, error, detail, _ = _closed(ledger)
        assert status == "skipped" and error == "a run is in progress"
        assert detail.adapted == {"reason": "a run is in progress"}

    def test_skip_passes_through_the_ticks_own_except_exception(self, ledger):
        # Every tick swallows its errors with `except Exception`. skip() must
        # still reach the decorator, or a held lock would be recorded as ok.
        swallowed = []

        @job_runs.tracked("t_skip2")
        def tick():
            try:
                job_runs.skip("another worker holds the lock")
            except Exception as exc:                # the tick's own handler
                swallowed.append(exc)
            finally:
                job_runs.note(unlocked=True)        # the tick's cleanup still runs

        assert tick() is None
        assert swallowed == []
        status, _, detail, _ = _closed(ledger)
        assert status == "skipped" and detail.adapted["unlocked"] is True

    def test_failed_inside_a_swallowing_except_marks_the_run_error(self, ledger):
        @job_runs.tracked("t_failed")
        def tick():
            try:
                raise ValueError("bad row")
            except Exception as exc:
                job_runs.failed(exc)
            return "still returns"

        assert tick() == "still returns"
        status, error, _, _ = _closed(ledger)
        assert status == "error" and error == "ValueError: bad row"

    def test_error_text_is_capped(self, ledger):
        @job_runs.tracked("t_long")
        def tick():
            try:
                raise RuntimeError("x" * 5000)
            except Exception as exc:
                job_runs.failed(exc)

        tick()
        _, error, _, _ = _closed(ledger)
        assert len(error) == 2000 and error.startswith("RuntimeError: xxx")


class TestNeverBreaksTheTick:
    def test_connect_failure_leaves_the_tick_running(self, monkeypatch):
        def refuse(*a, **k):
            raise psycopg2.OperationalError("no route to host")
        monkeypatch.setattr(psycopg2, "connect", refuse)
        ran = []

        @job_runs.tracked("t_noconn")
        def tick():
            ran.append(True)
            job_runs.note(a=1)
            return 3

        assert tick() == 3 and ran == [True]

    def test_insert_that_returns_nothing_means_no_close(self, ledger):
        # A fake that does not answer the INSERT: no id, so nothing to close —
        # and nothing to raise about either.
        ledger.script.clear()

        @job_runs.tracked("t_noid")
        def tick():
            return 1

        assert tick() == 1
        assert _closes(ledger) == []

    def test_a_zero_row_id_is_still_a_row(self, ledger):
        ledger.script[0] = (OPEN, (["id"], [(0,)]))

        @job_runs.tracked("t_zero")
        def tick():
            return 1

        tick()
        assert _closed(ledger)[3] == 0

    def test_update_failure_is_swallowed(self, ledger):
        ledger.script.append((CLOSE, psycopg2.OperationalError("gone")))

        @job_runs.tracked("t_updfail")
        def tick():
            return 1

        assert tick() == 1


class TestNote:
    def test_merges_dicts_kwargs_and_scalars(self, ledger):
        @job_runs.tracked("t_note")
        def tick():
            job_runs.note({"accounts": 3, "when": datetime(2026, 9, 1, tzinfo=timezone.utc)},
                          changed=Decimal("2"))
            job_runs.note(7)
            job_runs.note(None)

        tick()
        _, _, detail, _ = _closed(ledger)
        assert detail.adapted["accounts"] == 3 and detail.adapted["result"] == 7
        # Dates and Decimals out of a summary dict serialise via default=str
        # instead of failing the UPDATE.
        stored = json.loads(detail.dumps(detail.adapted))
        assert stored["when"] == "2026-09-01 00:00:00+00:00" and stored["changed"] == "2"

    def test_is_a_no_op_outside_a_tick(self):
        job_runs.note(x=1)                          # must not raise
        job_runs.failed(RuntimeError("x"))         # nor this
        assert job_runs._current() is None

    def test_another_thread_never_sees_this_run(self, ledger):
        # APScheduler runs ticks in a pool: the run is thread-local.
        seen = []

        def other():
            job_runs.note(leak=True)
            seen.append(job_runs._current())

        @job_runs.tracked("t_thread")
        def tick():
            t = threading.Thread(target=other)
            t.start()
            t.join()
            job_runs.note(mine=True)

        tick()
        assert seen == [None]
        assert _closed(ledger)[2].adapted == {"mine": True}


class TestContext:
    def test_context_is_restored_after_the_tick(self, ledger):
        @job_runs.tracked("t_ctx")
        def tick():
            assert job_runs._current().job_id == "t_ctx"

        tick()
        assert job_runs._current() is None

    def test_context_is_restored_after_an_escaping_error(self, ledger):
        @job_runs.tracked("t_ctx2")
        def tick():
            raise KeyError("k")

        with pytest.raises(KeyError):
            tick()
        assert job_runs._current() is None

    def test_nested_ticks_restore_the_outer_run(self, ledger):
        inner_ids = []

        @job_runs.tracked("t_inner")
        def inner():
            inner_ids.append(job_runs._current().job_id)

        @job_runs.tracked("t_outer")
        def outer():
            inner()
            job_runs.note(after_inner=job_runs._current().job_id)

        outer()
        assert inner_ids == ["t_inner"]
        outer_close = [p for p in _closes(ledger) if p[2].adapted.get("after_inner")]
        assert outer_close[0][2].adapted["after_inner"] == "t_outer"


class TestRegistry:
    def test_decorator_exposes_its_ids(self):
        @job_runs.tracked("t_reg", manual_id="t_reg_manual")
        def tick(triggered_by="schedule"):
            return triggered_by

        assert tick.__job_id__ == "t_reg"
        assert tick.__job_ids__ == ("t_reg", "t_reg_manual")
        assert {"t_reg", "t_reg_manual"} <= job_runs.TRACKED_JOB_IDS
        assert tick.__name__ == "tick"

    def test_manual_id_is_used_when_triggered_by_is_not_schedule(self, ledger):
        @job_runs.tracked("t_man", manual_id="t_man_manual")
        def tick(triggered_by="schedule"):
            return triggered_by

        tick()
        tick("admin")
        tick(triggered_by="schedule")
        opened = [p[0] for c in ledger.conns for _, p in sql_matching(c, OPEN)]
        assert opened == ["t_man", "t_man_manual", "t_man"]

    def test_without_a_manual_id_the_argument_changes_nothing(self, ledger):
        @job_runs.tracked("t_plain")
        def tick(triggered_by="schedule"):
            return triggered_by

        assert tick("admin") == "admin"
        assert _opened(ledger)[0] == "t_plain"
