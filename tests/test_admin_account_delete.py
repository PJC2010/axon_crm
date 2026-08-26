"""Tests for DELETE /admin/accounts/{id} (api/routes/admin.py).

The endpoint's correctness rules (cascade owns the ordering, auth_events by
hand, purge assertion before commit) were always covered by the guards in
api/admin_logic.py. What is covered here is the shape that made a real org
undeletable in production: a cascade is per-row trigger work, so the single
``DELETE FROM accounts`` grew with the org until it exceeded statement_timeout
and Postgres cancelled it. Same fake-conn style as test_admin_accounts_create —
no live DB; the conn answers whitespace-normalized SQL by first-matching
substring, and records every statement so ordering can be asserted.
"""
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

from config import ACCOUNT_DELETE_BATCH, ACCOUNT_DELETE_TIMEOUT_MS  # noqa: E402
from api.routes.admin import (  # noqa: E402
    _delete_account_leads, admin_delete_account,
)


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self.rowcount = -1
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self._conn.executed.append((flat, params))
        # The lead batches are answered from a shrinking counter rather than
        # the script: the loop's exit condition is a rowcount, so a canned
        # answer would either never end or end after one batch.
        if flat.startswith("DELETE FROM properties"):
            _account_id, limit = params
            self.rowcount = min(limit, self._conn.leads_remaining)
            self._conn.leads_remaining -= self.rowcount
            self.description, self._rows = None, []
            return
        for pattern, response in self._conn.script:
            if pattern in flat:
                if callable(response):
                    response = response(self._conn)
                if isinstance(response, Exception):
                    raise response
                cols, rows = response
                self.description = [(c,) for c in cols] if cols else None
                self._rows = list(rows)
                self.rowcount = len(self._rows)
                return
        self.description = None
        self._rows = []
        self.rowcount = 0

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = list(self._rows), []
        return rows


class _Conn:
    def __init__(self, script, leads=0):
        self.script = list(script)
        self.leads_remaining = leads
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1
        self.executed.append(("COMMIT", None))

    def rollback(self):
        self.rollbacks += 1
        self.executed.append(("ROLLBACK", None))


class _BatchCursor:
    """A cursor that owns a shrinking pile of leads, so the loop's own exit
    condition — DELETE reporting zero rows — is what ends it."""

    def __init__(self, remaining: int):
        self.remaining = remaining
        self.calls: list[tuple] = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        _account_id, limit = params
        self.rowcount = min(limit, self.remaining)
        self.remaining -= self.rowcount


ADMIN = {"id": 7, "username": "pete", "account_id": 1}
ACCOUNT = {"id": 42, "name": "Doomed Roofing", "business_type": "home_services"}

_COUNT_COLS = ["leads", "tasks", "invoices", "quotes", "expenses", "calls",
               "messages", "pipeline_runs", "workflow_rules",
               "scoring_reveals_month"]


def _script(leads: int = 0):
    """Everything the endpoint asks the database, in no particular order."""
    return [
        ("FROM accounts WHERE id",
         (["id", "name", "business_type", "created_at", "review_link"],
          [(42, "Doomed Roofing", "home_services", "2026-08-26", None)])),
        ("SELECT stripe_subscription_id", (None, [(None,)])),
        ("AND is_platform_admin", (None, [])),
        ("SELECT COUNT(*) FROM users WHERE account_id", (None, [(3,)])),
        ("DELETE FROM auth_events", (None, [(1,)] * 9)),
        ("SELECT table_name FROM information_schema.columns", (None, [("tasks",)])),
        ("WHERE EXISTS", (None, [])),          # nothing survived the purge
        ("INSERT INTO admin_audit_log", (None, [])),
        # The counts query, anchored on a column only it projects — a bare
        # "SELECT" here would match the lead batch's subquery as well.
        ("AS leads", (_COUNT_COLS, [(leads, 2, 1, 0, 0, 4, 7, 3, 1, 0)])),
    ]


def _statements(conn):
    return [sql for sql, _ in conn.executed]


class TestDeleteAccountLeads:
    """The batch loop. Its whole job is that no single statement's cost scales
    with the org, so these assert on the statements, not on a row count."""

    def test_deletes_every_lead_across_batches(self):
        cur = _BatchCursor(remaining=25_000)
        assert _delete_account_leads(cur, 42, 5_000) == 25_000
        assert cur.remaining == 0

    def test_each_statement_is_capped_at_the_batch_size(self):
        cur = _BatchCursor(remaining=25_000)
        _delete_account_leads(cur, 42, 5_000)
        assert all(params == (42, 5_000) for _, params in cur.calls)

    def test_batch_count_tracks_the_batch_size_not_the_org(self):
        # Ten times the leads must not mean a ten-times-longer statement; it
        # means ten times as many statements of the same bounded cost.
        small = _BatchCursor(remaining=5_000)
        big = _BatchCursor(remaining=50_000)
        _delete_account_leads(small, 42, 5_000)
        _delete_account_leads(big, 42, 5_000)
        assert len(small.calls) == 2      # one full batch + the empty one
        assert len(big.calls) == 11

    def test_stops_on_the_first_empty_batch(self):
        cur = _BatchCursor(remaining=0)
        assert _delete_account_leads(cur, 42, 5_000) == 0
        assert len(cur.calls) == 1

    def test_scopes_the_delete_to_the_account(self):
        cur = _BatchCursor(remaining=10)
        _delete_account_leads(cur, 42, 5_000)
        sql = cur.calls[0][0]
        assert "DELETE FROM properties WHERE id IN" in sql
        assert "WHERE account_id = %s LIMIT %s" in sql

    def test_a_zero_batch_cannot_spin_forever(self):
        # A misconfigured ACCOUNT_DELETE_BATCH must still make progress rather
        # than delete nothing and loop on a rowcount that is always zero.
        cur = _BatchCursor(remaining=3)
        assert _delete_account_leads(cur, 42, 0) == 3
        assert all(params[1] >= 1 for _, params in cur.calls)


class TestAdminDeleteAccount:
    def test_deletes_the_org_and_reports_counts(self):
        conn = _Conn(_script(leads=1_200), leads=1_200)
        out = admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                                   admin=ADMIN, db=conn)
        assert out == {"deleted": True, "account_id": 42, "name": "Doomed Roofing",
                       "counts": {"leads": 1_200, "tasks": 2, "invoices": 1,
                                  "quotes": 0, "expenses": 0, "calls": 4,
                                  "messages": 7, "pipeline_runs": 3,
                                  "workflow_rules": 1, "scoring_reveals_month": 0,
                                  "users": 3, "auth_events": 9}}
        assert conn.commits == 1 and conn.rollbacks == 0

    def test_raises_the_statement_timeout_for_this_transaction_only(self):
        # SET LOCAL, not SET: the connection is pooled, so a raised cap that
        # outlived the transaction would silently apply to the next request.
        conn = _Conn(_script())
        admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                             admin=ADMIN, db=conn)
        timeouts = [s for s in _statements(conn) if "statement_timeout" in s]
        assert timeouts == [f"SET LOCAL statement_timeout = {ACCOUNT_DELETE_TIMEOUT_MS}"]

    def test_timeout_is_raised_before_anything_is_deleted(self):
        conn = _Conn(_script(leads=10), leads=10)
        admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                             admin=ADMIN, db=conn)
        stmts = _statements(conn)
        set_at = next(i for i, s in enumerate(stmts) if "statement_timeout" in s)
        first_delete = next(i for i, s in enumerate(stmts) if s.startswith("DELETE"))
        assert set_at < first_delete

    def test_leads_are_batched_away_before_the_cascade_runs(self):
        conn = _Conn(_script(leads=10), leads=10)
        admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                             admin=ADMIN, db=conn)
        stmts = _statements(conn)
        leads = next(i for i, s in enumerate(stmts)
                     if s.startswith("DELETE FROM properties"))
        cascade = next(i for i, s in enumerate(stmts)
                       if s.startswith("DELETE FROM accounts"))
        assert leads < cascade

    def test_the_cascade_is_still_what_deletes_the_org(self):
        # The batching is a bound on one statement's cost, not a replacement
        # for the cascade — every other table still goes through this.
        conn = _Conn(_script())
        admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                             admin=ADMIN, db=conn)
        assert ("DELETE FROM accounts WHERE id = %s", (42,)) in conn.executed

    def test_auth_events_are_still_purged_by_hand(self):
        conn = _Conn(_script())
        out = admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                                   admin=ADMIN, db=conn)
        assert ("DELETE FROM auth_events WHERE account_id = %s", (42,)) in conn.executed
        assert out["counts"]["auth_events"] == 9

    def test_audit_row_is_written_before_the_commit(self):
        conn = _Conn(_script())
        admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                             admin=ADMIN, db=conn)
        stmts = _statements(conn)
        audit = next(i for i, s in enumerate(stmts)
                     if s.startswith("INSERT INTO admin_audit_log"))
        assert audit < stmts.index("COMMIT")

    def test_a_surviving_row_rolls_the_purge_back(self):
        script = [("WHERE EXISTS", (None, [("tasks",)]))] + _script()
        conn = _Conn(script)
        with pytest.raises(HTTPException) as exc:
            admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                                 admin=ADMIN, db=conn)
        assert exc.value.status_code == 500
        assert conn.commits == 0 and conn.rollbacks == 1

    def test_a_mistyped_name_never_reaches_the_database(self):
        conn = _Conn(_script())
        with pytest.raises(HTTPException) as exc:
            admin_delete_account(account_id=42, confirm_name="Doomed Roofin",
                                 admin=ADMIN, db=conn)
        assert exc.value.status_code == 409
        assert not any(s.startswith("DELETE") for s in _statements(conn))

    def test_batch_size_comes_from_config(self):
        conn = _Conn(_script(leads=10), leads=10)
        admin_delete_account(account_id=42, confirm_name="Doomed Roofing",
                             admin=ADMIN, db=conn)
        batches = [params for sql, params in conn.executed
                   if sql.startswith("DELETE FROM properties")]
        assert batches and all(p == (42, ACCOUNT_DELETE_BATCH) for p in batches)
