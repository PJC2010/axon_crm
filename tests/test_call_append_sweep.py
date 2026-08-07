"""Tests for api/call_append_sweep.py — the missed-call reverse-append backfill.

DB-free: a fake connection hands back canned candidate rows and records every
statement, so the sweep's real decisions — who gets queried, who gets flagged,
and whether the writes stay account-scoped — are checked without Postgres.
"""
import pytest

from api import call_append_sweep
from api.call_append_sweep import run_sweep


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._conn.statements.append((sql, params))

    def fetchall(self):
        return self._conn.candidates


class _FakeConn:
    """Answers the candidate query with canned rows; records everything else."""
    def __init__(self, candidates=()):
        self.candidates = list(candidates)
        self.statements = []
        self.commits = 0

    def cursor(self, *a, **k):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def updates(self):
        return [(sql, params) for sql, params in self.statements
                if sql.startswith("UPDATE properties")]


def _candidate(account_id=1, digits="7135550142", property_id=10, **overrides):
    """One candidate row in the column order _CANDIDATES_SQL selects."""
    row = {"address": None, "city": None, "state": None, "zip": None,
           "contact_name": None, "contact_email": None, "enrichment_flags": None}
    row.update(overrides)
    return (account_id, digits, property_id, row["address"], row["city"],
            row["state"], row["zip"], row["contact_name"], row["contact_email"],
            row["enrichment_flags"])


MATCH = {"contact_name": "Greta Fisher", "address": "123 Main St",
         "city": "Humble", "state": "TX", "zip": "77396",
         "phone_type": "Mobile", "phone_reachable": True}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(call_append_sweep, "PHONE_APPEND_PROVIDER", "batchdata")
    monkeypatch.setattr(call_append_sweep, "PHONE_APPEND_API_KEY", "test-key")
    monkeypatch.setattr(call_append_sweep, "PHONE_APPEND_SWEEP_MAX", 200)
    monkeypatch.setattr(call_append_sweep, "PHONE_APPEND_SWEEP_DAYS", 30)


def _results(monkeypatch, mapping):
    monkeypatch.setattr("pipeline.contact.phone_append_batch",
                        lambda digits: dict(mapping))


# ── The off switch ───────────────────────────────────────────────────────────

class TestDisabled:
    def test_zero_max_never_queries(self, monkeypatch, configured):
        # The default. Deploying the sweep must not start spending on its own.
        monkeypatch.setattr(call_append_sweep, "PHONE_APPEND_SWEEP_MAX", 0)
        conn = _FakeConn([_candidate()])
        assert run_sweep(conn)["skipped_no_provider"] is True
        assert conn.statements == []

    def test_no_provider_configured(self, monkeypatch, configured):
        monkeypatch.setattr(call_append_sweep, "PHONE_APPEND_PROVIDER", "")
        assert run_sweep(_FakeConn([_candidate()]))["skipped_no_provider"] is True

    def test_unknown_provider_name(self, monkeypatch, configured):
        monkeypatch.setattr(call_append_sweep, "PHONE_APPEND_PROVIDER", "nope")
        conn = _FakeConn([_candidate()])
        assert run_sweep(conn)["skipped_no_provider"] is True
        assert conn.statements == []


# ── Applying results ─────────────────────────────────────────────────────────

class TestSweep:
    def test_fills_a_matched_lead(self, monkeypatch, configured):
        _results(monkeypatch, {"7135550142": MATCH})
        conn = _FakeConn([_candidate()])
        assert run_sweep(conn) == {"candidates": 1, "queried": 1, "matched": 1,
                                   "updated": 1, "skipped_no_provider": False}
        sql, params = conn.updates()[0]
        assert "address = %s" in sql and "enrichment_flags = %s" in sql
        assert "123 Main St" in params
        assert conn.commits == 1

    def test_no_match_still_flags_so_it_is_never_re_queried(self, monkeypatch, configured):
        # The provider billed for the miss; without the flag the next run pays
        # again for the same nothing.
        _results(monkeypatch, {"7135550142": None})
        conn = _FakeConn([_candidate()])
        summary = run_sweep(conn)
        assert (summary["queried"], summary["matched"], summary["updated"]) == (1, 0, 0)
        sql, params = conn.updates()[0]
        assert sql.startswith("UPDATE properties SET enrichment_flags = %s")
        assert params[0].adapted == {"phone_append": "batchdata"}

    def test_transport_failure_writes_nothing(self, monkeypatch, configured):
        # An absent key means the lookup never completed — leaving the row
        # unflagged is what lets the next run retry it.
        _results(monkeypatch, {})
        conn = _FakeConn([_candidate()])
        summary = run_sweep(conn)
        assert (summary["candidates"], summary["queried"]) == (1, 0)
        assert conn.updates() == []

    def test_never_overwrites_what_the_lead_already_has(self, monkeypatch, configured):
        _results(monkeypatch, {"7135550142": MATCH})
        conn = _FakeConn([_candidate(city="Katy", contact_name="G. Fisher")])
        run_sweep(conn)
        sql, params = conn.updates()[0]
        assert "city = %s" not in sql
        assert "contact_name = %s" not in sql
        assert "Katy" not in params

    def test_line_type_rides_in_enrichment_flags(self, monkeypatch, configured):
        _results(monkeypatch, {"7135550142": MATCH})
        conn = _FakeConn([_candidate()])
        run_sweep(conn)
        flags = next(p for p in conn.updates()[0][1] if hasattr(p, "adapted"))
        assert flags.adapted["phone_append_meta"] == {
            "phone_type": "Mobile", "phone_reachable": True}

    def test_empty_backlog_makes_no_provider_call(self, monkeypatch, configured):
        def boom(digits):
            raise AssertionError("should not query with no candidates")
        monkeypatch.setattr("pipeline.contact.phone_append_batch", boom)
        assert run_sweep(_FakeConn([]))["candidates"] == 0


# ── Multi-tenancy ────────────────────────────────────────────────────────────

class TestTenantScoping:
    def test_every_update_is_account_scoped(self, monkeypatch, configured):
        _results(monkeypatch, {"7135550142": MATCH, "7135550143": MATCH})
        conn = _FakeConn([_candidate(account_id=1, digits="7135550142", property_id=10),
                          _candidate(account_id=2, digits="7135550143", property_id=20)])
        run_sweep(conn)
        for sql, params in conn.updates():
            assert sql.rstrip().endswith("WHERE id = %s AND account_id = %s")
        assert [params[-2:] for _, params in conn.updates()] == [(10, 1), (20, 2)]

    def test_shared_caller_updates_both_tenants_from_one_lookup(self, monkeypatch, configured):
        # One person calling two businesses is two independent leads. Each is
        # written separately; the lookup behind them is only bought once.
        seen = []
        monkeypatch.setattr("pipeline.contact.phone_append_batch",
                            lambda digits: seen.append(list(digits))
                            or {"7135550142": MATCH})
        conn = _FakeConn([_candidate(account_id=1, property_id=10),
                          _candidate(account_id=2, property_id=20)])
        summary = run_sweep(conn)
        assert seen == [["7135550142", "7135550142"]]  # dedupe is the batcher's job
        assert summary["updated"] == 2
        assert [params[-2:] for _, params in conn.updates()] == [(10, 1), (20, 2)]


# ── Batching ─────────────────────────────────────────────────────────────────

def test_chunks_commit_as_they_land(monkeypatch, configured):
    # 100 per request (BatchData's cap); each chunk commits so a crash keeps
    # the lookups it already paid for.
    _results(monkeypatch, {})
    calls = []
    monkeypatch.setattr("pipeline.contact.phone_append_batch",
                        lambda digits: calls.append(len(digits)) or {})
    conn = _FakeConn([_candidate(digits=f"71355{i:05d}", property_id=i)
                      for i in range(150)])
    run_sweep(conn)
    assert calls == [100, 50]
    assert conn.commits == 2
