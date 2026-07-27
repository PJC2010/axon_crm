"""Tests for pipeline/hcad_store.hcad_available() — the startup-guard helper."""
import pytest

import pipeline.hcad_store as hcad_store
from pipeline.hcad_store import garage_spaces_from_sqft


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _FakeCursor(self._row)

    def close(self):
        pass


def test_available_true_when_duckdb_present(monkeypatch):
    # DuckDB file present → available without touching Postgres.
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: True)
    assert hcad_store.hcad_available() is True


def test_available_true_when_postgres_has_rows(monkeypatch):
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: False)
    import pipeline.db as db
    monkeypatch.setattr(db, "get_conn", lambda: _FakeConn(row=(1,)))
    assert hcad_store.hcad_available() is True


def test_unavailable_when_no_duckdb_and_empty_mirror(monkeypatch):
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: False)
    import pipeline.db as db
    monkeypatch.setattr(db, "get_conn", lambda: _FakeConn(row=None))
    assert hcad_store.hcad_available() is False


def test_unavailable_when_db_unreachable(monkeypatch):
    # No DuckDB and Postgres connection fails → False (non-fatal for the guard).
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: False)
    import pipeline.db as db

    def _boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(db, "get_conn", _boom)
    assert hcad_store.hcad_available() is False


# ── garage_spaces_from_sqft ──────────────────────────────────────────────────
# HCAD extra-features store garage size as square footage (`uts`), not a space
# count. Regression tests for the "462 garage spaces" bug.

def test_garage_sqft_converts_to_spaces():
    assert garage_spaces_from_sqft(462) == 2    # the reported bug case
    assert garage_spaces_from_sqft(240) == 1
    assert garage_spaces_from_sqft(720) == 3


def test_garage_sqft_zero_and_none_mean_no_garage():
    assert garage_spaces_from_sqft(0) == 0
    assert garage_spaces_from_sqft(None) == 0


def test_garage_sqft_floors_at_one_space():
    # Any recorded garage area implies at least a 1-car garage.
    assert garage_spaces_from_sqft(80) == 1


def test_garage_sqft_caps_at_max():
    import config
    assert garage_spaces_from_sqft(999_999) == config.MAX_GARAGE_SPACES


def test_query_extra_features_returns_spaces_not_sqft(tmp_path):
    """End-to-end through the DuckDB query: 462 sqft of garage → 2 spaces."""
    duckdb = pytest.importorskip("duckdb")
    db_file = tmp_path / "hcad.duckdb"
    con = duckdb.connect(str(db_file))
    con.execute("CREATE TABLE property_summary (acct VARCHAR, site_address VARCHAR, site_zip VARCHAR)")
    con.execute("CREATE TABLE extra_features (acct VARCHAR, bld_num VARCHAR, cd VARCHAR, s_dscr VARCHAR, l_dscr VARCHAR, uts VARCHAR)")
    con.execute("INSERT INTO property_summary VALUES ('1', '9414 SLATE STONE CT', '77064')")
    con.execute("INSERT INTO extra_features VALUES ('1', '1', 'GAR', '', 'GARAGE - ATTACHED', '462')")
    con.close()

    out = hcad_store.query_extra_features("77064", db_path=str(db_file))
    assert out["9414 slate stone ct"]["garage_spaces"] == 2
