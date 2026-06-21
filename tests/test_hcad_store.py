"""Tests for pipeline/hcad_store.hcad_available() — the startup-guard helper."""
import pipeline.hcad_store as hcad_store


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
