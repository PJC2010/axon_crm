"""Tests for account-wide non-property scoring (pipeline/account_rescore.py):
the pure roll-up row builders and the rescore_account SQL orchestration.
Fake-conn style — no live DB."""
from datetime import date

import pytest

from pipeline import account_rescore as ar
from pipeline.profiles import PROFILES
from pipeline.scoring import compute_score


TODAY = date(2026, 7, 2)


class _ScriptedCursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    def executemany(self, sql, seq):
        self._conn.executed.append((sql, [list(p) for p in seq]))
        self._current = []

    def fetchall(self):
        return list(self._current)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _ScriptedConn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.commits = 0

    def cursor(self):
        return _ScriptedCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


# ── Pure row builders ─────────────────────────────────────────────────────────

class TestInsuranceRollup:
    def test_perfect_row_scores_100(self):
        row = ar.insurance_rollup_row(date(2026, 7, 17), 1, 2500, today=TODAY)
        assert row == {"days_to_expiration": 15, "policy_count": 1, "premium_in_force": 2500.0}
        assert compute_score(row, PROFILES["insurance_renewal"]) == pytest.approx(100.0, abs=1.0)

    def test_no_active_policy_is_cold(self):
        row = ar.insurance_rollup_row(None, 0, 0, today=TODAY)
        assert row["days_to_expiration"] is None
        assert compute_score(row, PROFILES["insurance_renewal"]) == 0.0

    def test_multi_line_lowers_cross_sell(self):
        one = ar.insurance_rollup_row(date(2026, 7, 17), 1, 2500, today=TODAY)
        many = ar.insurance_rollup_row(date(2026, 7, 17), 3, 2500, today=TODAY)
        assert compute_score(many, PROFILES["insurance_renewal"]) < compute_score(one, PROFILES["insurance_renewal"])


class TestRetailRollup:
    def test_perfect_row_scores_100(self):
        row = ar.retail_rollup_row(TODAY, 6, 1000, today=TODAY)
        assert row == {"days_since_last_order": 0, "order_count_365d": 6, "lifetime_spend": 1000.0}
        assert compute_score(row, PROFILES["retail_rfm"]) == pytest.approx(100.0, abs=1.0)

    def test_never_ordered_is_zero(self):
        row = ar.retail_rollup_row(None, 0, 0, today=TODAY)
        assert row["days_since_last_order"] is None
        assert compute_score(row, PROFILES["retail_rfm"]) == 0.0

    def test_lapsed_customer_decays(self):
        recent = ar.retail_rollup_row(TODAY, 3, 500, today=TODAY)
        lapsed = ar.retail_rollup_row(date(2025, 7, 2), 3, 500, today=TODAY)
        assert compute_score(lapsed, PROFILES["retail_rfm"]) < compute_score(recent, PROFILES["retail_rfm"])


# ── Orchestration ─────────────────────────────────────────────────────────────

class TestRescoreAccount:
    def test_insurance_account_scores_and_writes(self):
        # profile lookup (business_type passed) → roll-up SELECT → UPDATE executemany
        conn = _ScriptedConn([
            [(101, date(2026, 7, 17), 1, 2500), (102, None, 0, 0)],   # roll-up rows
        ])
        updated = ar.rescore_account(conn, 3, business_type="insurance_agency")
        assert updated == 2

        select_sql, select_params = conn.executed[0]
        assert "FROM properties p" in select_sql
        assert "LEFT JOIN policies" in select_sql
        assert select_params == [3]

        update_sql, update_rows = conn.executed[1]
        assert "UPDATE properties SET lead_score" in update_sql
        # Property 101 has an imminent renewal → high score + grade A; 102 cold.
        by_pid = {r[2]: r for r in update_rows}
        assert by_pid[101][0] > 70 and by_pid[101][1] == "A"
        assert by_pid[101][3] == 3           # account scope on the UPDATE
        assert by_pid[102][0] == 0.0 and by_pid[102][1] == "D"

    def test_retail_account_uses_orders_rollup(self):
        conn = _ScriptedConn([[(200, date(2026, 7, 2), 6, 1000)]])
        updated = ar.rescore_account(conn, 5, business_type="retail")
        assert updated == 1
        select_sql, _ = conn.executed[0]
        assert "LEFT JOIN orders" in select_sql

    def test_unscored_business_type_noop(self):
        conn = _ScriptedConn([])
        assert ar.rescore_account(conn, 7, business_type="home_services") == 0
        assert conn.executed == []           # no queries at all

    def test_resolves_business_type_when_not_passed(self):
        conn = _ScriptedConn([
            [("insurance_agency",)],          # accounts lookup
            [(101, date(2026, 7, 17), 1, 2500)],
        ])
        updated = ar.rescore_account(conn, 3)
        assert updated == 1
        assert "SELECT business_type FROM accounts" in conn.executed[0][0]

    def test_empty_account_writes_nothing(self):
        conn = _ScriptedConn([[]])           # no records
        assert ar.rescore_account(conn, 3, business_type="retail") == 0
        assert len(conn.executed) == 1       # only the SELECT, no UPDATE


class TestRescoreAllAccounts:
    def test_per_account_isolation(self, monkeypatch):
        conn = _ScriptedConn([[(3, "insurance_agency"), (5, "retail")]])
        calls = []

        def fake_rescore(c, account_id, business_type):
            calls.append((account_id, business_type))
            if account_id == 3:
                raise RuntimeError("boom")
            return 4

        monkeypatch.setattr(ar, "rescore_account", fake_rescore)
        summary = ar.rescore_all_accounts(conn)
        assert summary == {"accounts": 1, "records": 4}
        assert calls == [(3, "insurance_agency"), (5, "retail")]
        select_sql, select_params = conn.executed[0]
        assert "business_type = ANY(%s)" in select_sql
        assert set(select_params[0]) == {"insurance_agency", "retail"}


class TestProfileKeyLookup:
    def test_maps_scored_types(self):
        conn = _ScriptedConn([[("insurance_agency",)]])
        assert ar.profile_key_for_account(conn, 3) == "insurance_renewal"

    def test_returns_none_for_property_type(self):
        conn = _ScriptedConn([[("home_services",)]])
        assert ar.profile_key_for_account(conn, 3) is None

    def test_returns_none_for_missing_account(self):
        conn = _ScriptedConn([[]])
        assert ar.profile_key_for_account(conn, 999) is None
