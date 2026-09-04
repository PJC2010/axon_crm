"""
Tests for pipeline/db.upsert_properties — the batched multi-row upsert.

Offline: psycopg2.extras.execute_values is monkeypatched to capture the SQL and
argument lists, so these lock in the batching contract (one statement per
column signature, correct Json wrapping, exact affected-row count) without a DB.
"""
import psycopg2.extras

import pipeline.db as db


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self):
        self.committed = 0

    def cursor(self):
        return _FakeCursor()

    def commit(self):
        self.committed += 1


def _capture(monkeypatch):
    """Patch execute_values to record every call; each returns one row per arg."""
    calls = []

    def fake_execute_values(cur, sql, argslist, page_size=100, fetch=False):
        calls.append({"sql": sql, "argslist": argslist, "page_size": page_size})
        return [(1,) for _ in argslist] if fetch else None

    monkeypatch.setattr(psycopg2.extras, "execute_values", fake_execute_values)
    return calls


def test_empty_rows_short_circuits(monkeypatch):
    calls = _capture(monkeypatch)
    conn = _FakeConn()
    assert db.upsert_properties(conn, [], account_id=7) == 0
    assert calls == []
    assert conn.committed == 0


def test_same_signature_batched_into_one_statement(monkeypatch):
    calls = _capture(monkeypatch)
    conn = _FakeConn()
    rows = [
        {"address": "1 A St", "zip": "77002", "year_built": 2001},
        {"address": "2 B St", "zip": "77002", "year_built": 1999},
        {"address": "3 C St", "zip": "77002", "year_built": 2010},
    ]
    n = db.upsert_properties(conn, rows, account_id=42)

    # One column signature → one batched execute_values call, three arg rows.
    assert len(calls) == 1
    assert len(calls[0]["argslist"]) == 3
    assert n == 3
    assert conn.committed == 1
    # account_id is written first on every row.
    assert all(args[0] == 42 for args in calls[0]["argslist"])


def test_different_signatures_split_into_separate_statements(monkeypatch):
    calls = _capture(monkeypatch)
    conn = _FakeConn()
    rows = [
        {"address": "1 A St", "zip": "77002", "year_built": 2001},
        {"address": "2 B St", "zip": "77002", "owner_name": "SMITH"},
        {"address": "3 C St", "zip": "77002", "year_built": 2010},
    ]
    n = db.upsert_properties(conn, rows, account_id=1)

    # Two distinct signatures → two statements; the year_built group has 2 rows.
    assert len(calls) == 2
    sizes = sorted(len(c["argslist"]) for c in calls)
    assert sizes == [1, 2]
    assert n == 3


def test_rows_with_no_writable_columns_are_skipped(monkeypatch):
    calls = _capture(monkeypatch)
    conn = _FakeConn()
    rows = [
        {"unknown_field": "x"},          # nothing in ALL_COLS → skipped
        {"address": "1 A St", "zip": "77002", "year_built": 2001},
    ]
    n = db.upsert_properties(conn, rows, account_id=1)
    assert len(calls) == 1
    assert len(calls[0]["argslist"]) == 1
    assert n == 1


def test_enrichment_flags_dict_is_json_wrapped_and_merged(monkeypatch):
    calls = _capture(monkeypatch)
    conn = _FakeConn()
    rows = [{"address": "1 A St", "zip": "77002",
             "enrichment_flags": {"seed": "rentcast"}}]
    db.upsert_properties(conn, rows, account_id=1)

    sql = calls[0]["sql"]
    assert "enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags" in sql
    # The dict value is wrapped in psycopg2's Json adapter, not passed raw.
    flag_val = calls[0]["argslist"][0][-1]
    assert isinstance(flag_val, psycopg2.extras.Json)


def test_fill_only_writes_into_nulls_not_over_values(monkeypatch):
    """The seed paths re-run on every scheduled pipeline; fill_only keeps a
    re-seed from replacing HCAD facts, refreshed values, or the row's
    HCAD-sourced parcel identity with the seed source's copy."""
    calls = _capture(monkeypatch)
    db.upsert_properties(_FakeConn(), [{
        "address": "1 A St", "zip": "77002", "year_built": 1998,
        "parcel_apn": "0660640130020", "enrichment_flags": {"seed": "rentcast"},
    }], account_id=1, fill_only=True)
    sql = calls[0]["sql"]
    assert "year_built = COALESCE(properties.year_built, EXCLUDED.year_built)" in sql
    assert "parcel_apn = COALESCE(properties.parcel_apn, EXCLUDED.parcel_apn)" in sql
    assert "year_built = EXCLUDED.year_built" not in sql
    # Flags still merge, and under fill_only the EXISTING keys win: a re-seed
    # that keeps the row's columns keeps their provenance too (e.g. the
    # enrichment_flags.equity_source stamp, pipeline/equity.py).
    assert "enrichment_flags = EXCLUDED.enrichment_flags || properties.enrichment_flags" in sql


def test_default_mode_still_overwrites(monkeypatch):
    calls = _capture(monkeypatch)
    db.upsert_properties(_FakeConn(), [{"address": "1 A St", "zip": "77002",
                                        "lead_score": 88}], account_id=1)
    assert "lead_score = EXCLUDED.lead_score" in calls[0]["sql"]
    assert "COALESCE" not in calls[0]["sql"]


def test_conflict_set_omits_key_columns(monkeypatch):
    calls = _capture(monkeypatch)
    conn = _FakeConn()
    rows = [{"address": "1 A St", "zip": "77002", "year_built": 2001}]
    db.upsert_properties(conn, rows, account_id=1)

    sql = calls[0]["sql"]
    assert "year_built = EXCLUDED.year_built" in sql
    # address / zip are the conflict key — never in the UPDATE SET clause.
    assert "address = EXCLUDED.address" not in sql
    assert "zip = EXCLUDED.zip" not in sql


def test_only_key_columns_uses_do_nothing(monkeypatch):
    calls = _capture(monkeypatch)
    conn = _FakeConn()
    # A row whose only writable columns are the conflict key: no SET clause is
    # valid, so the statement must fall back to DO NOTHING.
    rows = [{"address": "1 A St", "zip": "77002"}]
    db.upsert_properties(conn, rows, account_id=1)

    sql = calls[0]["sql"]
    assert "DO NOTHING" in sql
    assert "DO UPDATE SET" not in sql
