"""Tests for recurring invoices (Phase 7): pure cadence date math and the
generate_due_invoices clone-and-advance orchestration. Fake-conn, no live DB."""
from datetime import date

import pytest

from api import recurring_invoices as ri


class TestDateMath:
    @pytest.mark.parametrize("d,rec,expected", [
        (date(2026, 1, 15), "weekly",    date(2026, 1, 22)),
        (date(2026, 1, 15), "monthly",   date(2026, 2, 15)),
        (date(2026, 1, 15), "quarterly", date(2026, 4, 15)),
        (date(2026, 1, 15), "annual",    date(2027, 1, 15)),
    ])
    def test_advance(self, d, rec, expected):
        assert ri.advance(d, rec) == expected

    def test_month_end_clamps(self):
        assert ri.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)   # non-leap
        assert ri.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)   # leap
        assert ri.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)  # year rollover

    def test_advance_unknown_raises(self):
        with pytest.raises(ValueError):
            ri.advance(date(2026, 1, 1), "fortnightly")

    def test_next_after_skips_backlog(self):
        # A monthly template last due Jan 10, evaluated Apr 5, jumps straight to
        # the next future occurrence (Apr 10) rather than replaying Feb/Mar.
        nxt = ri.next_after(date(2026, 1, 10), "monthly", today=date(2026, 4, 5))
        assert nxt == date(2026, 4, 10)

    def test_next_after_normal_case(self):
        assert ri.next_after(date(2026, 4, 1), "monthly", today=date(2026, 4, 1)) == date(2026, 5, 1)

    def test_series_ended(self):
        assert ri.series_ended(date(2026, 6, 1), date(2026, 5, 1)) is True
        assert ri.series_ended(date(2026, 6, 1), date(2026, 12, 1)) is False
        assert ri.series_ended(date(2026, 6, 1), None) is False


# ── fake DB ─────────────────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    def fetchall(self): return list(self._current)
    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _Conn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.commits = 0
    def cursor(self): return _Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): pass


def _template_row(recurrence="monthly", rec_next=date(2026, 4, 1), rec_end=None,
                  issue=date(2026, 3, 1), due=date(2026, 3, 15)):
    # Matches the SELECT column order in _generate_one.
    return (7, "Ada Client", None, "ada@x.com", "1 St",
            0.0, 100.0, 0.0, 100.0, issue, due, "Membership", 9,
            recurrence, rec_next, rec_end)


class TestGenerate:
    def test_clones_and_advances(self):
        today = date(2026, 4, 2)
        conn = _Conn([
            [(50, 3)],                 # due templates: (id, account_id)
            [_template_row()],         # _generate_one: template SELECT
            [(900,)],                  # clone INSERT RETURNING id
            [],                        # line-items copy
            [],                        # advance UPDATE
        ])
        summary = ri.generate_due_invoices(conn, today=today)
        assert summary == {"generated": 1, "templates": 1, "failures": 0}

        insert_sql, insert_params = conn.executed[2]
        assert "INSERT INTO invoices" in insert_sql
        assert "'sent'" in insert_sql
        assert insert_params[-1] == 50            # recurring_source_id = template id
        # Clone issue date = the template's recurrence_next (2026-04-01);
        # due preserves the 14-day issue→due gap.
        assert date(2026, 4, 1) in insert_params
        assert date(2026, 4, 15) in insert_params

        copy_sql, _ = conn.executed[3]
        assert "INSERT INTO invoice_line_items" in copy_sql and "SELECT" in copy_sql

        adv_sql, adv_params = conn.executed[4]
        assert "recurrence_next = %s" in adv_sql
        assert adv_params[0] == date(2026, 5, 1)  # advanced one month
        assert conn.commits == 1

    def test_deactivates_when_past_end(self):
        today = date(2026, 4, 2)
        conn = _Conn([
            [(50, 3)],
            [_template_row(rec_next=date(2026, 4, 1), rec_end=date(2026, 4, 15))],
            [(900,)],
            [],
            [],
        ])
        ri.generate_due_invoices(conn, today=today)
        adv_sql, _ = conn.executed[4]
        # Next would be 2026-05-01 > end 2026-04-15 → series turned off.
        assert "recurrence_next = NULL" in adv_sql and "recurrence = NULL" in adv_sql

    def test_no_due_templates_noop(self):
        conn = _Conn([[]])
        summary = ri.generate_due_invoices(conn, today=date(2026, 4, 2))
        assert summary == {"generated": 0, "templates": 0, "failures": 0}

    def test_per_template_isolation(self, monkeypatch):
        conn = _Conn([[(50, 3), (51, 3)]])
        calls = []

        def boom_first(c, template_id, account_id, today):
            calls.append(template_id)
            if template_id == 50:
                raise RuntimeError("boom")
            return 1

        monkeypatch.setattr(ri, "_generate_one", boom_first)
        summary = ri.generate_due_invoices(conn, today=date(2026, 4, 2))
        assert summary == {"generated": 1, "templates": 2, "failures": 1}
        assert calls == [50, 51]
