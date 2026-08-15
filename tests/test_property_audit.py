"""Tests for pipeline/property_audit.py — the non-residential audit and cleanup.

The DB is stubbed, so these exercise what the module decides: what it queries,
what it refuses to do, and what it writes. Three properties matter most and are
each pinned below.

  Account scoping. CLAUDE.md calls this "the single most important correctness
  rule in the codebase" — a missing account_id leaks one tenant's leads into
  another's audit, or archives them.

  The EXCLUDE/REVIEW split. REVIEW reasons exist precisely because a legitimate
  home can look like that, so no path may archive on one.

  Sample/count agreement. The counts come from SQL and each sample's reasons are
  re-derived in Python; if the projection omits a column the rule reads, the two
  disagree silently.
"""
import pytest

from pipeline import property_audit
from pipeline.property_audit import _CLASSIFIER_INPUTS, _SAMPLE_COLS, archive, audit
from pipeline.residential import EXCLUDE_REASONS, REVIEW_REASONS


class _FakeCursor:
    """Captures statements; replays scripted result sets in order."""

    def __init__(self, results=None, rowcount=0):
        self.statements: list[tuple] = []
        self._results = list(results or [])
        self._current: list = []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        self._current = list(self._results.pop(0)) if self._results else []

    def fetchone(self):
        return self._current[0] if self._current else None

    def fetchall(self):
        return list(self._current)

    def fetchmany(self, n):
        return list(self._current)[:n]

    def all_sql(self) -> str:
        return "\n".join(s for s, _ in self.statements)


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        self.commits += 1


def _audit_results(totals=None, samples=(), by_zip=(), billable=0, archived=0):
    """The five result sets audit() consumes, in order."""
    base = {"properties": 100, "flagged": 7, "excludable": 5}
    base.update({f"n_{r}": 0 for r in
                 list(EXCLUDE_REASONS) + list(REVIEW_REASONS)})
    base.update(totals or {})
    return [[base], list(samples), list(by_zip),
            [{"billable": billable}], [{"n": archived}]]


# ── Scoping ──────────────────────────────────────────────────────────────────

def test_every_statement_is_account_scoped():
    cur = _FakeCursor(_audit_results())
    audit(_FakeConn(cur), 42)
    assert cur.statements, "no statements issued"
    for sql, params in cur.statements:
        assert "account_id = %s" in sql, sql
        # Bound, never interpolated.
        assert 42 in (params or []), (sql, params)


def test_account_id_is_never_interpolated():
    cur = _FakeCursor(_audit_results())
    audit(_FakeConn(cur), 42)
    assert "account_id = 42" not in cur.all_sql()


def test_live_leads_only_by_default():
    cur = _FakeCursor(_audit_results())
    audit(_FakeConn(cur), 1)
    # The first three statements report on work still to do.
    for sql, _ in cur.statements[:3]:
        assert "archived_at IS NULL" in sql


def test_zip_scope_is_bound_not_interpolated():
    cur = _FakeCursor(_audit_results())
    audit(_FakeConn(cur), 1, zip_code="77024")
    for sql, params in cur.statements:
        assert "zip = %s" in sql
        assert "77024" in (params or [])
    assert "77024" not in cur.all_sql()


def test_audit_writes_nothing():
    cur = _FakeCursor(_audit_results())
    conn = _FakeConn(cur)
    audit(conn, 1)
    sql = cur.all_sql().upper()
    for verb in ("UPDATE ", "INSERT ", "DELETE ", "ARCHIVED_AT = "):
        assert verb not in sql, verb
    assert conn.commits == 0


# ── Return shape ─────────────────────────────────────────────────────────────

def test_audit_return_shape():
    cur = _FakeCursor(_audit_results(
        totals={"properties": 12_403, "flagged": 900, "excludable": 812,
                "n_commercial_owner": 300},
        by_zip=[{"zip": "77024", "properties": 12_403, "excludable": 812}],
        billable=640, archived=3,
    ))
    out = audit(_FakeConn(cur), 1)
    assert out["properties"] == 12_403
    assert out["flagged"] == 900
    assert out["excludable"] == 812
    assert out["by_reason"]["commercial_owner"]["count"] == 300
    assert out["by_reason"]["commercial_owner"]["tier"] == "exclude"
    assert out["by_reason"]["no_structure"]["tier"] == "review"
    assert out["by_zip"][0]["zip"] == "77024"
    assert out["spend_at_risk"]["billable_rows"] == 640
    assert out["already_archived"] == 3
    assert out["scope"] == {"zip": None}


def test_every_reason_is_reported_even_at_zero():
    """A reason missing from the report reads as "not checked", not "none found"."""
    cur = _FakeCursor(_audit_results())
    out = audit(_FakeConn(cur), 1)
    from pipeline.residential import ALL_REASONS
    assert set(out["by_reason"]) == set(ALL_REASONS)


def test_samples_carry_their_reasons():
    sample = {"id": 9, "account_number": "C-27334",
              "address": "0 BARRYKNOLL LN 656", "zip": "77024",
              "owner_name": "MEMORIAL CITY MALL LP", "property_type": None,
              "state_class": None, "square_footage": 147089, "year_built": 2001,
              "estimated_value": 13_465_295, "lead_score": 62.0,
              "score_grade": "B", "status": "new", "reason_count": 3}
    cur = _FakeCursor(_audit_results(samples=[sample]))
    out = audit(_FakeConn(cur), 1)
    got = out["samples"][0]
    assert set(got["reasons"]) == {"commercial_owner", "oversized_structure",
                                   "no_situs"}
    assert "reason_count" not in got, "internal ordering column leaked"


def test_sample_projection_covers_every_classifier_input():
    """The guard that prevents the counts and the examples disagreeing.

    Drop `state_class` from the projection and the audit would report N rows
    flagged for `county_class` while showing examples that never mention it.
    """
    assert set(_CLASSIFIER_INPUTS) <= set(_SAMPLE_COLS)
    with pytest.raises(ValueError, match="classifier inputs"):
        original = property_audit._SAMPLE_COLS
        try:
            property_audit._SAMPLE_COLS = tuple(
                c for c in original if c != "state_class")
            property_audit._guard_sample_cols()
        finally:
            property_audit._SAMPLE_COLS = original


# ── archive ──────────────────────────────────────────────────────────────────

def test_archive_soft_deletes_and_records_the_reason():
    cur = _FakeCursor([[(1,), (2,)]], rowcount=2)
    conn = _FakeConn(cur)
    out = archive(conn, 7)
    sql = cur.all_sql()
    assert "UPDATE properties" in sql
    assert "archived_at = NOW()" in sql
    assert "exclusion_reason = CASE" in sql
    assert "DELETE" not in sql.upper()
    assert out["archived_count"] == 2
    assert conn.commits == 1


def test_archive_releases_the_paid_budget_slot():
    """A row archived mid-run must stop holding a Top-N enrichment slot."""
    cur = _FakeCursor([[]], rowcount=0)
    archive(_FakeConn(cur), 7)
    assert "enrichment_selected = FALSE" in cur.all_sql()


def test_archive_is_account_scoped():
    cur = _FakeCursor([[]], rowcount=0)
    archive(_FakeConn(cur), 7)
    sql, params = cur.statements[0]
    assert "account_id = %s" in sql
    assert params == [7]


@pytest.mark.parametrize("reason", REVIEW_REASONS)
def test_review_reasons_cannot_be_archived(reason):
    """The whole point of the REVIEW tier: a legitimate home can look like this,
    so it is reported and never acted on automatically."""
    cur = _FakeCursor([[]], rowcount=0)
    with pytest.raises(ValueError, match="review-only"):
        archive(_FakeConn(cur), 7, reasons=[reason])
    assert cur.statements == [], "a rejected request must not touch the DB"


def test_unknown_reason_is_rejected():
    cur = _FakeCursor([[]], rowcount=0)
    with pytest.raises(ValueError, match="unknown reason"):
        archive(_FakeConn(cur), 7, reasons=["made_up"])
    assert cur.statements == []


def test_default_reasons_are_exactly_the_exclude_tier():
    cur = _FakeCursor([[]], rowcount=0)
    out = archive(_FakeConn(cur), 7)
    assert out["reasons"] == list(EXCLUDE_REASONS)


def test_dry_run_counts_without_writing():
    cur = _FakeCursor([[(4,)]])
    conn = _FakeConn(cur)
    out = archive(conn, 7, dry_run=True)
    sql = cur.all_sql()
    assert sql.strip().upper().startswith("SELECT COUNT(*)")
    assert "UPDATE" not in sql.upper()
    assert out == {"archived_count": 0, "would_archive": 4,
                   "reasons": list(EXCLUDE_REASONS), "dry_run": True,
                   "zip": None}
    assert conn.commits == 0


def test_archive_bounds_the_returned_id_list():
    """An account-wide cleanup can touch tens of thousands of rows, and this
    runs in the web process — the response must stay a bounded payload."""
    many = [(i,) for i in range(5_000)]
    cur = _FakeCursor([many], rowcount=5_000)
    out = archive(_FakeConn(cur), 7)
    assert out["archived_count"] == 5_000
    assert len(out["ids"]) == property_audit._MAX_RETURNED_IDS
    assert out["ids_truncated"] is True


def test_archive_generated_sql_has_no_percent_metacharacter():
    """psycopg2 reads a literal '%' as a placeholder once params are bound."""
    cur = _FakeCursor([[]], rowcount=0)
    archive(_FakeConn(cur), 7)
    sql = cur.all_sql()
    assert "%" not in sql.replace("%s", "")
