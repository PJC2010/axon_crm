"""Tests for the scoring feedback loop's snapshot capture (pipeline/score_snapshots.py)
and its hook in pipeline/scorer.py score_zip: active-model lookup, per-score snapshot
writes, PII exclusion, and non-fatal degradation. Fake-conn style, no live DB."""
from datetime import date
from decimal import Decimal

import config
import pipeline.scorer as scorer
from pipeline.score_snapshots import (
    get_active_model_version, snapshot_features, write_score_snapshots,
)
from pipeline.scoring import _compute_score


# ── Fakes ─────────────────────────────────────────────────────────────────────
# Responses are keyed by SQL substring (not call order) so the score_zip hook can
# be tested even though other non-fatal writers (pipeline/ml snapshot) share the
# connection and interleave their own statements.

class _FakeCursor:
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
        self._rows = []
        for fragment, rows in self._conn.responses.items():
            if fragment in sql:
                self._rows = rows
                break

    def executemany(self, sql, params_list):
        self._conn.executed.append((sql, list(params_list)))
        self._rows = []

    @property
    def description(self):
        if self._rows and isinstance(self._rows[0], dict):
            return [(k,) for k in self._rows[0].keys()]
        return []

    def fetchall(self):
        if self._rows and isinstance(self._rows[0], dict):
            return [tuple(r.values()) for r in self._rows]
        return list(self._rows)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _FakeConn:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


_MODEL_ROW = {
    "id": 7,
    "version_tag": "v0-heuristic",
    "algorithm": "heuristic_weights",
    "coefficients": dict(config.DEFAULT_WEIGHTS),
    "grade_bands": {"A": 75, "B": 55, "C": 35},
}

_ACTIVE_MODEL_SQL = "FROM scoring_model_versions"


def _lead_row(**over):
    row = {
        "id": 101,
        "address": "123 Main St",           # PII-adjacent — must never be snapshotted
        "zip": "77002",
        "owner_name": "Jane Doe",           # PII — must never be snapshotted
        "contact_phone": "713-555-0101",    # PII — must never be snapshotted
        "contact_email": "jane@example.com",  # PII — must never be snapshotted
        "mailing_address": "PO Box 1",      # PII — must never be snapshotted
        "year_built": 2003,
        "garage_spaces": 2,
        "estimated_value": 400_000,
        "estimated_equity": 120_000,
        "estimated_job_value": 5_000,
        "last_sale_date": date(2025, 3, 1),
        "zip_median_income": 80_000,
        "permit_count_24mo": 2,
        "hail_size_in": Decimal("1.75"),
        "vertical": None,
        "lead_source": "pipeline",
    }
    row.update(over)
    return row


# ── get_active_model_version ──────────────────────────────────────────────────

class TestGetActiveModelVersion:
    def test_returns_active_row_as_dict(self):
        conn = _FakeConn({_ACTIVE_MODEL_SQL: [_MODEL_ROW]})
        model = get_active_model_version(conn)
        assert model["id"] == 7
        assert model["version_tag"] == "v0-heuristic"
        sql, _ = conn.executed[0]
        assert "status = 'active'" in sql

    def test_returns_none_when_registry_empty(self):
        assert get_active_model_version(_FakeConn()) is None


# ── snapshot_features ─────────────────────────────────────────────────────────

class TestSnapshotFeatures:
    def test_never_contains_pii(self):
        features = snapshot_features(_lead_row())
        assert not {
            "owner_name", "contact_name", "contact_phone", "contact_email",
            "address", "mailing_address",
        } & set(features)

    def test_captures_factor_fields(self):
        features = snapshot_features(_lead_row())
        assert features["year_built"] == 2003
        assert features["estimated_equity"] == 120_000
        assert features["garage_spaces"] == 2
        assert features["vertical"] is None
        assert features["lead_source"] == "pipeline"

    def test_values_are_json_serializable(self):
        features = snapshot_features(_lead_row())
        assert features["last_sale_date"] == "2025-03-01"     # date → ISO string
        assert features["hail_size_in"] == 1.75               # Decimal → float
        assert isinstance(features["hail_size_in"], float)


# ── write_score_snapshots ─────────────────────────────────────────────────────

class TestWriteScoreSnapshots:
    def test_writes_one_row_per_lead(self):
        conn = _FakeConn({_ACTIVE_MODEL_SQL: [_MODEL_ROW]})
        n = write_score_snapshots(
            conn, 3,
            [(_lead_row(id=101), 72.34567, "B"), (_lead_row(id=102), 91.0, "A")],
        )
        assert n == 2
        sql, params_list = conn.executed[-1]
        assert "INSERT INTO lead_score_snapshots" in sql
        assert len(params_list) == 2
        pid, account_id, model_id, features, raw_score, grade = params_list[0]
        assert (pid, account_id, model_id) == (101, 3, 7)
        assert features.adapted["year_built"] == 2003     # psycopg2 Json wrapper
        assert raw_score == 72.3457                       # NUMERIC(8,4) precision
        assert grade == "B"
        assert params_list[1][0] == 102
        assert conn.commits == 1

    def test_reuses_prefetched_model_row(self):
        conn = _FakeConn()
        n = write_score_snapshots(conn, 3, [(_lead_row(), 50.0, "C")], model=_MODEL_ROW)
        assert n == 1
        assert all(_ACTIVE_MODEL_SQL not in sql for sql, _ in conn.executed)

    def test_skips_gracefully_when_no_active_model(self):
        conn = _FakeConn()   # SELECT finds no active model (pre-migration DB)
        assert write_score_snapshots(conn, 3, [(_lead_row(), 50.0, "C")]) == 0
        assert all("INSERT" not in sql for sql, _ in conn.executed)

    def test_skips_rows_without_id(self):
        conn = _FakeConn({_ACTIVE_MODEL_SQL: [_MODEL_ROW]})
        assert write_score_snapshots(conn, 3, [(_lead_row(id=None), 50.0, "C")]) == 0


# ── score_zip hook ────────────────────────────────────────────────────────────

class TestScoreZipSnapshots:
    def _run(self, monkeypatch, conn, rows):
        monkeypatch.setattr(scorer, "get_conn", lambda: conn)
        monkeypatch.setattr(scorer, "fetch_by_zip", lambda c, z, a: rows)
        monkeypatch.setattr(scorer, "upsert_properties", lambda c, u, a: len(u))
        return scorer.score_zip("77002", account_id=3)

    def test_every_scoring_call_writes_snapshots(self, monkeypatch):
        conn = _FakeConn({_ACTIVE_MODEL_SQL: [_MODEL_ROW]})
        rows = [_lead_row(id=101), _lead_row(id=102, address="456 Oak St")]
        assert self._run(monkeypatch, conn, rows) == 2

        inserts = [(sql, p) for sql, p in conn.executed
                   if "INSERT INTO lead_score_snapshots" in sql]
        assert len(inserts) == 1
        params_list = inserts[0][1]
        assert [p[0] for p in params_list] == [101, 102]
        assert all(p[2] == 7 for p in params_list)   # active model version id

        # The snapshot records the same score the lead was graded with.
        expected = _compute_score(_lead_row(id=101), config.DEFAULT_WEIGHTS)
        assert params_list[0][4] == round(expected, 4)

    def test_snapshot_failure_never_breaks_scoring(self, monkeypatch):
        conn = _FakeConn({_ACTIVE_MODEL_SQL: [_MODEL_ROW]})

        def boom(*args, **kwargs):
            raise RuntimeError("snapshot table missing")

        monkeypatch.setattr(scorer, "write_score_snapshots", boom)
        assert self._run(monkeypatch, conn, [_lead_row()]) == 1
        assert conn.rollbacks == 1   # aborted txn cleared for later writers
