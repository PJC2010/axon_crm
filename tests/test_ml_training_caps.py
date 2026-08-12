"""Resource caps on the nightly retrain (pipeline/ml).

The retrain runs in-process on the API instance, so an unbounded load is an OOM of
the web service rather than of a detached worker. These tests pin the three things
that keep it bounded — a projected column list instead of `SELECT p.*`, a
server-side cursor instead of a client-side buffer, and a cap on how many rows are
retained and fitted — because all three fail silently: the job still "works", it
just takes the instance down once the table is big enough.

Fake-conn style, no live DB.
"""
from datetime import datetime, timedelta

import pytest

import config
from pipeline.ml import dataset, features, snapshot
from pipeline.ml.train import _subsample


# ── Fakes ─────────────────────────────────────────────────────────────────────
# Rows are keyed by SQL substring so a test only has to describe the query it
# cares about. Named cursors are recorded separately: whether one was used *is*
# the behavior under test, not an implementation detail.

class _Cursor:
    rowcount = 1

    def __init__(self, conn):
        self._conn = conn
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        self._rows = self._conn.rows_for(sql)

    def executemany(self, sql, params_list):
        self._conn.executed.append((sql, list(params_list)))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _NamedCursor(_Cursor):
    """Stand-in for a psycopg2 server-side cursor: iterated, never fetchall()'d."""

    def __init__(self, conn, name):
        super().__init__(conn)
        self.name = name
        self.itersize = None
        self.closed = False

    def __iter__(self):
        return iter(self._rows)

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.executed = []
        self.named_cursors = []
        self.commits = 0

    def rows_for(self, sql):
        for fragment, rows in self.responses.items():
            if fragment in sql:
                return list(rows)
        return []

    def cursor(self, *a, name=None, **k):
        if name is not None:
            cur = _NamedCursor(self, name)
            self.named_cursors.append(cur)
            return cur
        return _Cursor(self)

    def commit(self):
        self.commits += 1


def _prop(i, decided_at, status="won"):
    """A properties row as the bootstrap query returns it."""
    return {"id": i, "account_id": 1, "status": status,
            "created_at": datetime(2024, 1, 1), "stage_moved_at": decided_at,
            "updated_at": decided_at, "estimated_job_value": None,
            "year_built": 1998, "estimated_value": 320_000,
            "has_paid_invoice": False, "has_accepted_quote": False}


# ── The projection: p.* is what made a row cost KBs instead of bytes ──────────

def test_bootstrap_query_projects_columns_instead_of_star():
    conn = _FakeConn({"FROM properties p": []})
    dataset.backfill_examples(conn, account_id=1, max_rows=10)
    sql = conn.executed[0][0]

    assert "SELECT p.*" not in sql
    # The two JSONB columns and the wide free-text ones are the expensive half of
    # a properties row and no feature or label reads them.
    for excluded in ("p.enrichment_flags", "p.custom_fields", "p.owner_name",
                     "p.mailing_address", "p.address"):
        assert excluded not in sql
    # …while everything the label rules and the feature vector do read is present.
    for needed in ("p.status", "p.created_at", "p.stage_moved_at", "p.updated_at",
                   "p.year_built", "p.estimated_value", "p.vertical"):
        assert needed in sql


def test_projection_covers_every_snapshot_field():
    cols = set(dataset._backfill_columns())
    assert set(features.SNAPSHOT_FIELDS) <= cols
    # derive_label / derive_outcome_at / derive_job_value inputs.
    assert {"status", "created_at", "stage_moved_at", "updated_at",
            "estimated_job_value", "account_id", "id"} <= cols


def test_projection_guard_rejects_an_unsafe_identifier(monkeypatch):
    # The column list is interpolated into SQL, so a bad name must fail loudly
    # here rather than build a surprising statement.
    monkeypatch.setattr(features, "SNAPSHOT_FIELDS",
                        ["year_built", "x FROM properties; DROP TABLE properties;--"])
    with pytest.raises(ValueError):
        dataset._backfill_columns()


# ── Streaming: psycopg2 buffers everything unless the cursor is named ─────────

def test_bootstrap_scan_streams_through_a_server_side_cursor():
    conn = _FakeConn({"FROM properties p": [_prop(1, datetime(2024, 6, 1))]})
    dataset.backfill_examples(conn, account_id=1, max_rows=10)

    assert conn.named_cursors, "bootstrap scan must not buffer the table client-side"
    cur = conn.named_cursors[0]
    assert cur.itersize == config.ML_STREAM_BATCH
    assert cur.closed, "server-side cursor must be closed even on an early break"


def test_outcome_backfill_streams_and_flushes_in_batches(monkeypatch):
    monkeypatch.setattr(snapshot, "ML_STREAM_BATCH", 10)
    rows = [{"snap_id": i, "status": "won", "created_at": datetime(2024, 1, 1),
             "stage_moved_at": datetime(2024, 6, 1), "updated_at": datetime(2024, 6, 1),
             "estimated_job_value": 500, "invoice_total": None, "quote_total": None,
             "has_paid_invoice": False, "has_accepted_quote": False}
            for i in range(50)]
    conn = _FakeConn({"FROM lead_feature_snapshots s": rows})

    assert snapshot.backfill_outcomes(conn) == 50
    assert conn.named_cursors and conn.named_cursors[0].closed

    writes = [c for c in conn.executed if c[0].startswith("UPDATE lead_feature_snapshots")]
    assert len(writes) == 5, "updates must flush per batch, not accumulate"
    assert all(len(params) <= 10 for _, params in writes)
    # One commit at the end: committing mid-scan would close the cursor's portal.
    assert conn.commits == 1


def test_outcome_backfill_is_not_capped():
    # Skipping rows here would leave them unlabeled forever, so only the in-memory
    # batch is bounded — never the number of rows considered.
    rows = [{"snap_id": i, "status": "lost", "created_at": datetime(2024, 1, 1),
             "stage_moved_at": None, "updated_at": datetime(2024, 5, 1),
             "estimated_job_value": None, "invoice_total": None, "quote_total": None,
             "has_paid_invoice": False, "has_accepted_quote": False}
            for i in range(config.ML_STREAM_BATCH * 3 + 7)]
    conn = _FakeConn({"FROM lead_feature_snapshots s": rows})
    assert snapshot.backfill_outcomes(conn) == len(rows)


# ── The cap itself ────────────────────────────────────────────────────────────

def test_bootstrap_keeps_the_most_recently_decided_rows():
    base = datetime(2024, 1, 1)
    rows = [_prop(i, base + timedelta(days=i)) for i in range(50)]
    conn = _FakeConn({"FROM properties p": rows})

    out = dataset.backfill_examples(conn, account_id=1, max_rows=10)

    assert len(out) == 10
    # Recent signal survives the trim; stale history is what gets dropped.
    assert sorted(e["outcome_at"] for e in out) == \
        [base + timedelta(days=i) for i in range(40, 50)]


def test_bootstrap_without_a_cap_returns_every_labeled_row():
    base = datetime(2024, 1, 1)
    rows = [_prop(i, base + timedelta(days=i)) for i in range(30)]
    conn = _FakeConn({"FROM properties p": rows})
    assert len(dataset.backfill_examples(conn, account_id=1)) == 30


def test_bootstrap_still_drops_censored_rows():
    # An open lead that has not aged out has no label and must not be trained on,
    # cap or no cap.
    conn = _FakeConn({"FROM properties p": [
        _prop(1, datetime(2024, 6, 1), status="won"),
        _prop(2, datetime(2024, 6, 1), status="quote_sent"),
    ]})
    out = dataset.backfill_examples(conn, account_id=1, max_rows=10)
    assert [e["features"]["id"] for e in out] == [1]


def test_labeled_snapshots_orders_and_limits():
    conn = _FakeConn({"FROM lead_feature_snapshots": []})
    dataset.labeled_snapshots(conn, account_id=3, max_rows=25)
    sql, params = conn.executed[0]

    assert "ORDER BY outcome_at DESC NULLS LAST" in sql
    assert "LIMIT %s" in sql
    # psycopg2 binds %s in the order the placeholders appear in the statement, so
    # the account filter must stay ahead of the limit.
    assert params == [3, 25]


def test_labeled_snapshots_without_a_cap_has_no_limit():
    conn = _FakeConn({"FROM lead_feature_snapshots": []})
    dataset.labeled_snapshots(conn, account_id=None)
    sql, params = conn.executed[0]
    assert "LIMIT" not in sql
    assert params == []


# ── Fit-set subsampling (the CPU half) ───────────────────────────────────────

def test_subsample_bounds_the_fit_set_and_preserves_order():
    rows = [{"i": i} for i in range(1000)]
    out = _subsample(rows, 100)

    assert len(out) == 100
    order = [r["i"] for r in out]
    assert order == sorted(order)
    assert len(set(order)) == len(order), "no row sampled twice"


def test_subsample_barely_over_the_cap_loses_almost_nothing():
    rows = [{"i": i} for i in range(101)]
    assert len(_subsample(rows, 100)) == 100


def test_subsample_is_a_no_op_under_the_cap_or_when_disabled():
    rows = [{"i": i} for i in range(50)]
    assert _subsample(rows, 100) is rows
    assert _subsample(rows, 0) is rows


def test_subsample_is_deterministic():
    rows = [{"i": i} for i in range(997)]
    assert _subsample(rows, 123) == _subsample(rows, 123)
