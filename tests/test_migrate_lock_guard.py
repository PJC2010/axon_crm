"""The migration runner bounds every migration's lock wait itself.

Why this test exists
────────────────────
Render runs `python db/migrate.py` as preDeployCommand, with the previous
instances still serving traffic. DDL on a hot table takes ACCESS EXCLUSIVE, and
Postgres' lock queue is FIFO: once that ALTER is waiting, every later SELECT on
the table queues behind it. With DB_STATEMENT_TIMEOUT_MS at 30s (api/deps.py)
the readers do not merely slow down — they are cancelled, and the dashboard
returns 500s while the deploy finishes.

0077, 0078 and 0080 each opened with their own `SET LOCAL lock_timeout`. 0081
did not, and shipped two `ALTER TABLE properties` with an unbounded wait. A
convention that has to be remembered per file is one that will be forgotten
again, so the guard belongs in the runner. These tests pin that it is applied
BEFORE the file's SQL and INSIDE the same transaction — either alone would be
useless.
"""
import importlib.util
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_migrate(monkeypatch, **env):
    """Import db/migrate.py fresh. It is a script, not a package module, and it
    reads DATABASE_URL at import time."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused_by_these_tests")
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location(
        "_migrate_under_test", REPO / "db" / "migrate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeCursor:
    def __init__(self):
        self.statements: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.statements.append((" ".join(str(sql).split()), params))


class _FakeConn:
    """One cursor for the whole run, so statement order across `with` blocks is
    observable — that ordering is the thing under test."""

    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1
        self.cursor_obj.statements.append(("COMMIT", None))

    def close(self):
        pass


def test_lock_timeout_is_set_before_the_migration_sql(monkeypatch, tmp_path):
    mod = _load_migrate(monkeypatch, MIGRATION_LOCK_TIMEOUT=None)  # use the default
    cur = _FakeCursor()
    assert mod.apply_lock_timeout(cur) is True
    (sql, params), = cur.statements
    assert "set_config" in sql
    assert "lock_timeout" in sql
    # Bound, never interpolated: an env var must not reach SQL as text.
    assert params == ("10s",)
    assert "10s" not in sql
    # is_local => true, i.e. scoped to this transaction, not the session.
    assert "true" in sql.lower()


def test_default_is_ten_seconds_matching_the_hand_written_convention(monkeypatch):
    mod = _load_migrate(monkeypatch, MIGRATION_LOCK_TIMEOUT=None)
    assert mod.MIGRATION_LOCK_TIMEOUT == "10s"


def test_env_override_is_honoured(monkeypatch):
    mod = _load_migrate(monkeypatch, MIGRATION_LOCK_TIMEOUT="3s")
    cur = _FakeCursor()
    mod.apply_lock_timeout(cur)
    assert cur.statements[0][1] == ("3s",)


def test_empty_override_disables_the_bound(monkeypatch):
    """Escape hatch for a maintenance window where waiting is the point."""
    mod = _load_migrate(monkeypatch, MIGRATION_LOCK_TIMEOUT="")
    cur = _FakeCursor()
    assert mod.apply_lock_timeout(cur) is False
    assert cur.statements == []


def test_run_applies_the_guard_inside_each_migrations_transaction(monkeypatch, tmp_path):
    """The ordering that matters: guard → migration SQL → bookkeeping → COMMIT.

    A guard applied after the SQL bounds nothing, and one applied in a different
    transaction is discarded before the DDL runs.
    """
    mod = _load_migrate(monkeypatch, MIGRATION_LOCK_TIMEOUT=None)

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_first.sql").write_text("ALTER TABLE properties ADD COLUMN a INT;")
    (mig_dir / "0002_second.sql").write_text("ALTER TABLE properties ADD COLUMN b INT;")
    monkeypatch.setattr(mod, "MIGRATIONS_DIR", mig_dir)

    conn = _FakeConn()
    monkeypatch.setattr(mod, "get_conn", lambda: conn)
    monkeypatch.setattr(mod, "ensure_migrations_table", lambda c: None)
    monkeypatch.setattr(mod, "reconcile_legacy_names", lambda c: None)
    monkeypatch.setattr(mod, "applied_migrations", lambda c: [])

    mod.run(argparse_ns())

    kinds = [_kind(sql) for sql, _ in conn.cursor_obj.statements]
    assert kinds == [
        "guard", "ddl", "bookkeeping", "commit",
        "guard", "ddl", "bookkeeping", "commit",
    ], kinds


def test_every_migration_file_gets_the_guard_even_when_it_sets_none_itself(monkeypatch, tmp_path):
    """The 0081 regression, pinned: a file with no lock_timeout of its own still
    runs behind one."""
    mod = _load_migrate(monkeypatch, MIGRATION_LOCK_TIMEOUT=None)
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "0081_freeze_events.sql").write_text(
        "ALTER TABLE properties ADD COLUMN IF NOT EXISTS last_freeze_date DATE;")
    monkeypatch.setattr(mod, "MIGRATIONS_DIR", mig_dir)
    conn = _FakeConn()
    monkeypatch.setattr(mod, "get_conn", lambda: conn)
    monkeypatch.setattr(mod, "ensure_migrations_table", lambda c: None)
    monkeypatch.setattr(mod, "reconcile_legacy_names", lambda c: None)
    monkeypatch.setattr(mod, "applied_migrations", lambda c: [])

    mod.run(argparse_ns())

    guard_idx = next(i for i, (s, _) in enumerate(conn.cursor_obj.statements)
                     if "set_config" in s)
    ddl_idx = next(i for i, (s, _) in enumerate(conn.cursor_obj.statements)
                   if "ALTER TABLE" in s)
    assert guard_idx < ddl_idx
    # …and no COMMIT separates them, or the bound would already have lapsed.
    between = conn.cursor_obj.statements[guard_idx:ddl_idx]
    assert not any(s == "COMMIT" for s, _ in between)


# ── helpers ───────────────────────────────────────────────────────────────────

def _kind(sql: str) -> str:
    if "set_config" in sql:
        return "guard"
    if sql == "COMMIT":
        return "commit"
    if "schema_migrations" in sql:
        return "bookkeeping"
    return "ddl"


def argparse_ns():
    import argparse
    return argparse.Namespace()
