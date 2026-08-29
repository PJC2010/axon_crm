"""The audit reads a stored verdict instead of re-deriving the rule.

Migration 0083 is the `properties` half of what 0077 did for `parcels`. The
audit endpoint interpolated 11,678 bytes of predicate across 9 reasons and
evaluated all of it per row, three passes deep, on a page load — and returned
QueryCanceled (a 500) to the data-quality page on 2026-08-29.

What has to stay true afterwards:

  * the audit's statements no longer carry the battery at all (a partial
    conversion that leaves one pass heavy fixes nothing);
  * `archive` DOES still carry it, deliberately — it stamps each row with what
    is true now, not with a verdict that may predate the row's last edit;
  * NULL (never classified) is never silently reported as clean;
  * account scoping survives the rewrite on every new statement.
"""
import psycopg2
import pytest

from pipeline import property_audit
from pipeline.property_audit import (
    ALL_REASONS, EXCLUDE_REASONS, audit, classify, rule_hash, sweep,
)


class _FakeCursor:
    def __init__(self, owner, results=None):
        self.owner = owner
        self._results = results
        self._current = []
        self.rowcount = owner.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.owner.statements.append((str(sql), params))
        self._current = self.owner.next_result()

    def fetchone(self):
        return self._current[0] if self._current else None

    def fetchall(self):
        return list(self._current)

    def fetchmany(self, n):
        return list(self._current)[:n]


class _FakeConn:
    def __init__(self, results=None, rowcount=0):
        self.statements = []
        self._results = list(results or [])
        self.rowcount = rowcount
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self)

    def next_result(self):
        return self._results.pop(0) if self._results else []

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _audit_results():
    """Scripted result sets in the order audit() consumes them."""
    totals = {"properties": 10, "unclassified": 2, "flagged": 3,
              "excludable": 2, "billable": 1, "protected": 0}
    totals.update({f"n_{r}": 0 for r in ALL_REASONS})
    return [
        [{"rule_hash": rule_hash()}],   # stamped_rule_hash
        [totals],                        # totals scan
        [],                              # samples
        [{"n": 0}],                      # already_archived
    ]


# ── The battery is gone from the read path ───────────────────────────────────

def _battery_bytes():
    from pipeline.residential import sql_reason
    return sum(len(sql_reason(r, owner_norm="__owner_norm")) for r in ALL_REASONS)


def test_no_audit_statement_still_interpolates_the_reason_battery():
    conn = _FakeConn(results=_audit_results())
    audit(conn, account_id=7)
    for sql, _ in conn.statements:
        # A signature fragment of the rule that only the generated predicate
        # contains — cheap and specific, unlike matching on length alone.
        assert "REGEXP_REPLACE" not in sql.upper(), \
            f"audit still normalizes owner_name per row:\n{sql[:400]}"
        assert "__owner_norm" not in sql, \
            f"audit still projects the normalization column:\n{sql[:400]}"


def _reason_eval_bytes():
    """SQL the audit now spends on deciding which reasons a row carries."""
    from pipeline.property_audit import FLAGGED_SQL, _has, _has_any
    return (sum(len(_has(r)) for r in ALL_REASONS)
            + len(_has_any(EXCLUDE_REASONS))
            + len(FLAGGED_SQL)
            + sum(len(_has(r)) for r in EXCLUDE_REASONS))   # the sample ranking


def test_reason_evaluation_shrank_by_more_than_an_order_of_magnitude():
    """The measurement that matters: what the database evaluates PER ROW to
    decide a row's reasons. Total statement length is the wrong yardstick — most
    of what remains is _gap_clause and UNWORKED_ONLY_SQL, which this change
    never touched.
    """
    now, before = _reason_eval_bytes(), _battery_bytes()
    assert now * 10 < before, (
        f"reason evaluation is {now} bytes against the {before}-byte battery "
        f"({before / now:.1f}x) — expected better than 10x")


def test_the_whole_audit_statement_shrank_too():
    """Weaker but independent: the same totals query, built the old way, against
    what the module issues now. Constructed here rather than remembered, so it
    cannot go stale."""
    conn = _FakeConn(results=_audit_results())
    audit(conn, account_id=7)
    biggest = max(len(sql) for sql, _ in conn.statements)
    would_have_been = biggest + _battery_bytes()   # the battery it no longer carries
    assert biggest * 3 < would_have_been, (
        f"{biggest} bytes now vs ~{would_have_been} before — expected 3x+")


def test_audit_reads_the_stored_column():
    conn = _FakeConn(results=_audit_results())
    audit(conn, account_id=7)
    joined = "\n".join(sql for sql, _ in conn.statements)
    assert "non_residential_reasons" in joined


def test_archive_still_evaluates_the_live_rule():
    """The asymmetry is deliberate and load-bearing — see migration 0083.

    A destructive bulk action must not run on a verdict that predates the row's
    last edit, so archive keeps paying for the battery.
    """
    conn = _FakeConn(results=[[(1,)]], rowcount=1)
    property_audit.archive(conn, account_id=7, reasons=["county_class"])
    joined = "\n".join(sql for sql, _ in conn.statements)
    assert "__owner_norm" in joined, \
        "archive stopped deriving the rule — it would archive on a stale verdict"


# ── NULL is not 'clean' ──────────────────────────────────────────────────────

def test_unclassified_rows_are_reported_separately():
    conn = _FakeConn(results=_audit_results())
    report = audit(conn, account_id=7)
    assert report["unclassified"] == 2
    # …and are not counted as flagged.
    assert report["flagged"] == 3


def test_flagged_predicate_excludes_null_and_empty_arrays():
    sql = property_audit.FLAGGED_SQL
    assert "array_length" in sql and "COALESCE" in sql, \
        "array_length is NULL for both an empty and a NULL array"
    assert property_audit.UNCLASSIFIED_SQL == "(non_residential_reasons IS NULL)"


def test_has_any_is_array_overlap_and_handles_the_empty_case():
    assert property_audit._has_any([]) == "(FALSE)"
    sql = property_audit._has_any(EXCLUDE_REASONS)
    assert "&&" in sql and "::text[]" in sql


def test_rule_staleness_is_surfaced():
    results = _audit_results()
    results[0] = [{"rule_hash": "definitely-not-the-current-hash"}]
    conn = _FakeConn(results=results)
    assert audit(conn, account_id=7)["rule_stale"] is True

    conn = _FakeConn(results=_audit_results())
    assert audit(conn, account_id=7)["rule_stale"] is False


def test_never_stamped_account_reads_as_stale():
    results = _audit_results()
    results[0] = []          # no stamp row at all
    conn = _FakeConn(results=results)
    assert audit(conn, account_id=7)["rule_stale"] is True


# ── Account scoping ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("call", [
    lambda conn: audit(conn, account_id=7),
    lambda conn: classify(conn, account_id=7),
    lambda conn: classify(conn, account_id=7, after_id=0, through_id=100,
                          only_unclassified=True),
])
def test_every_statement_is_account_scoped(call):
    """CLAUDE.md: 'the single most important correctness rule in the codebase'."""
    conn = _FakeConn(results=_audit_results())
    call(conn)
    reads = [(s, p) for s, p in conn.statements if "properties" in s]
    assert reads, "no statement touched properties"
    for sql, params in reads:
        assert "account_id = %s" in sql, f"unscoped statement:\n{sql[:300]}"
        assert params and params[0] == 7


def test_stamp_is_keyed_by_account():
    conn = _FakeConn()
    with conn.cursor() as cur:
        property_audit.stamp_rule(cur, 7, "abc123")
    sql, params = conn.statements[-1]
    assert "property_rule_stamps" in sql
    assert "ON CONFLICT (account_id)" in sql
    assert params == (7, "abc123")


# ── classify() ───────────────────────────────────────────────────────────────

def test_classify_writes_an_array_and_guards_against_no_op_writes():
    conn = _FakeConn(rowcount=5)
    assert classify(conn, account_id=7) == 5
    sql, _ = conn.statements[-1]
    assert "SET non_residential_reasons = v.reasons" in sql
    assert "ARRAY_REMOVE(" in sql, "a clean row must store {} rather than NULLs"
    assert "IS DISTINCT FROM" in sql, \
        "without the change guard a nightly sweep rewrites every row"
    # The two optimizer fences the cost of this UPDATE depends on.
    assert sql.count("OFFSET 0") == 2
    assert conn.commits == 1


def test_classify_normalizes_owner_name_once_per_row():
    conn = _FakeConn(rowcount=0)
    classify(conn, account_id=7)
    sql, _ = conn.statements[-1]
    assert "AS __owner_norm" in sql
    assert sql.count("AS __owner_norm") == 1


def test_classify_range_params_follow_statement_order():
    """psycopg2 binds positionally by statement text, and both range bounds sit
    in the inner WHERE after the scope predicates."""
    conn = _FakeConn(rowcount=0)
    classify(conn, account_id=7, zip_code="77396", after_id=100, through_id=600)
    sql, params = conn.statements[-1]
    assert params == [7, "77396", 100, 600]
    assert sql.index("account_id = %s") < sql.index("id > %s") < sql.index("id <= %s")


def test_batches_are_disjoint_so_a_stale_sweep_makes_progress():
    """The bug this replaced: `LIMIT n` with no ORDER BY re-reads the same rows
    every call. With classify's IS DISTINCT FROM guard, batch 2 would find
    nothing left to change, report 0, and the sweep would conclude it had
    finished — then stamp the new rule hash over an account it had barely
    started, so nothing ever revisited the remainder.
    """
    import inspect
    src = inspect.getsource(property_audit.sweep)
    assert "next_batch_bound" in src
    assert "after_id = through_id" in src, "the walk does not advance"
    bound_src = inspect.getsource(property_audit.next_batch_bound)
    assert "ORDER BY id" in bound_src, "an unordered batch is not disjoint"
    assert "id > %s" in bound_src


def test_sweep_only_stamps_a_completed_walk():
    """A partial sweep that stamps tells the next tick the rule change was
    applied, stranding every row it did not reach."""
    calls = {"n": 0}

    class _Conn2(_FakeConn):
        def cursor(self, cursor_factory=None):
            calls["n"] += 1
            return _FakeCursor(self)

    # next_batch_bound keeps returning a bound → the walk never ends.
    conn = _Conn2(results=[[{"rule_hash": "stale"}]] + [[(999,)]] * 200,
                  rowcount=0)
    out = sweep(conn, account_id=7, batch_size=10, max_batches=3)
    assert out["complete"] is False
    assert out["resume_after_id"] == 999
    # The stamp is READ at the start of every sweep; what must not happen is
    # the write.
    assert not any("INSERT INTO property_rule_stamps" in sql
                   for sql, _ in conn.statements), "a partial sweep must not stamp"


def test_sweep_stamps_when_the_walk_reaches_the_end():
    conn = _FakeConn(results=[[{"rule_hash": "stale"}], [(None,)]], rowcount=0)
    out = sweep(conn, account_id=7)
    assert out["complete"] is True
    assert any("INSERT INTO property_rule_stamps" in sql
               for sql, _ in conn.statements)


def test_only_unclassified_restricts_to_the_backlog():
    conn = _FakeConn(rowcount=0)
    classify(conn, account_id=7, only_unclassified=True)
    sql, _ = conn.statements[-1]
    assert "non_residential_reasons IS NULL" in sql


def test_flag_array_covers_every_reason_in_order():
    sql = property_audit._flag_array()
    for r in ALL_REASONS:
        assert f"THEN '{r}' END" in sql, f"{r} missing from the stored verdict"


def test_rule_hash_changes_when_the_rule_changes(monkeypatch):
    """Otherwise a rule edit never reaches already-classified rows: the change
    guard makes the re-run write nothing, so nothing would ever notice."""
    before = rule_hash()
    import pipeline.residential as residential
    real = residential.sql_reason
    monkeypatch.setattr(residential, "sql_reason",
                        lambda r, prefix="", **kw: real(r, prefix, **kw) + " AND TRUE")
    assert rule_hash() != before


def test_rule_hash_is_stable_across_calls():
    assert rule_hash() == rule_hash()


def test_a_healthy_report_says_degraded_false_rather_than_omitting_it():
    from pipeline.property_audit import empty_report
    conn = _FakeConn(results=_audit_results())
    healthy = audit(conn, account_id=7)
    assert healthy["degraded"] is False
    assert empty_report(7)["degraded"] is True
    # Same keys either way, so a client never has to branch on shape.
    assert set(healthy) == set(empty_report(7))
