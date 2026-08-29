"""The cooling-leads prefilter: correct first, fast second.

/api/pipeline/alerts computes `last_activity_at` with two correlated MAX()
subqueries per row and only then applies the idle-days test. On 2026-08-29 that
scan hit statement_timeout and returned a 500. COOLING_PREFILTER moves the same
test inside the scan, onto the two columns the row already carries, so the
subqueries never run for a lead that is plainly still warm.

That is only a legitimate optimisation if it removes exactly the rows the outer
filter would have removed. These tests are the proof, not a spot check: the
losslessness case matrix is exhaustive over every NULL/relative-ordering
combination of the four inputs.

The prefilter is deliberately NOT the same expression as the outer filter — it
reads two columns where the outer reads four — so "they look alike" is not an
argument. The argument is the inequality
    last_activity_at >= GREATEST(stage_moved_at, created_at)
and the NULL case where that inequality has nothing to say.
"""
import itertools

import pytest

from api.routes import pipeline as pipeline_routes
from api.routes.pipeline import COOLING_PREFILTER


# ── The two predicates, modelled ─────────────────────────────────────────────
# `None` is SQL NULL. GREATEST ignores NULLs and is NULL only when every
# argument is; a comparison involving NULL is NULL, which WHERE treats as false.

def _greatest(*vals):
    present = [v for v in vals if v is not None]
    return max(present) if present else None


def _outer_last_activity(stage_moved_at, created_at, notes_max, history_max):
    """The production expression, transcribed."""
    return _greatest(
        stage_moved_at,
        created_at,
        notes_max if notes_max is not None else created_at,
        history_max if history_max is not None else created_at,
    )


def _outer_admits(row, cutoff):
    last = _outer_last_activity(*row)
    return last is not None and last < cutoff


def _prefilter_admits(row, cutoff):
    """COALESCE(GREATEST(stage_moved_at, created_at) < cutoff, TRUE)."""
    stage_moved_at, created_at, _notes, _history = row
    g = _greatest(stage_moved_at, created_at)
    if g is None:          # comparison is NULL → COALESCE hands back TRUE
        return True
    return g < cutoff


# Values around the cutoff: clearly stale, exactly at it, clearly fresh, absent.
CUTOFF = 100
_VALUES = (None, 50, 100, 150)


def _rows():
    return itertools.product(_VALUES, repeat=4)


def test_prefilter_never_drops_a_row_the_outer_filter_would_keep():
    """The losslessness property, exhaustively: prefilter ⊇ outer.

    This is the only direction that can lose data. A row admitted by the outer
    filter but rejected by the prefilter is a cooling lead that silently stops
    being reported.
    """
    lost = [row for row in _rows()
            if _outer_admits(row, CUTOFF) and not _prefilter_admits(row, CUTOFF)]
    assert lost == [], f"prefilter drops rows the outer filter keeps: {lost}"


def test_prefilter_actually_prunes_something():
    """A positive control. `WHERE TRUE` would pass the test above and be
    worthless, so pin that the prefilter rejects a real, common shape: a lead
    touched today, which is most of an active account."""
    pruned = [row for row in _rows() if not _prefilter_admits(row, CUTOFF)]
    assert pruned, "prefilter admits everything — it is not pruning at all"
    # Every pruned row must genuinely be non-cooling.
    assert not any(_outer_admits(row, CUTOFF) for row in pruned)
    # The concrete case: stage moved after the cutoff, nothing else known.
    assert not _prefilter_admits((150, None, None, None), CUTOFF)


def test_the_null_case_is_why_coalesce_is_there():
    """properties.created_at is nullable (`TIMESTAMP DEFAULT NOW()`), so both
    columns can be NULL on a row that still has notes. A bare
    `GREATEST(...) < cutoff` would drop it; the outer filter keeps it."""
    row = (None, None, 50, None)          # no dates, one old note
    assert _outer_admits(row, CUTOFF)
    assert _prefilter_admits(row, CUTOFF)
    # …and the bare form — the tempting simplification — would not.
    bare = _greatest(row[0], row[1])
    assert bare is None, "precondition: GREATEST over two NULLs is NULL"


def test_rows_the_outer_filter_rejects_may_still_pass_the_prefilter():
    """The prefilter is a superset, not an equivalence. It is allowed to admit
    rows the outer filter then rejects — that is just work not saved. Pinned so
    a future 'tightening' that makes them equal is understood to be a
    correctness change, not a cleanup."""
    surviving = [row for row in _rows()
                 if _prefilter_admits(row, CUTOFF) and not _outer_admits(row, CUTOFF)]
    assert surviving, "prefilter is exactly equivalent — check the NULL handling"


# ── The statement as actually issued ─────────────────────────────────────────

def test_prefilter_sql_is_null_safe_and_bound():
    sql = COOLING_PREFILTER
    assert "COALESCE(" in sql and ", TRUE)" in sql, \
        "a bare comparison drops rows whose dates are both NULL"
    assert "GREATEST(stage_moved_at, created_at)" in sql
    assert sql.count("%s") == 1, "the idle window must be bound, not interpolated"


def test_cooling_query_binds_the_idle_window_twice_in_statement_order():
    """psycopg2 binds %s positionally by where the placeholder appears in the
    STATEMENT TEXT, not by clause order in the source (CLAUDE.md). The prefilter
    introduces a second occurrence of cooling_days *inside* the scan, ahead of
    the outer one — so the params tuple must repeat it, and the two occurrences
    must be adjacent in the right order. Getting this wrong swaps the idle
    window with the row limit and fails at runtime, or worse, silently doesn't.
    """
    captured = {}

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            if "last_activity_at" in str(sql):
                captured["sql"] = str(sql)
                captured["params"] = params
            self.description = [("id",)]
        def fetchall(self): return []
        def fetchone(self): return None

    cur = _Cur()
    fn = _extract_cooling_fn()
    fn(cur, acct=7, cooling_days=5, limit=50)

    sql, params = captured["sql"], captured["params"]
    # Placeholder order in the text: acct, grades, statuses, prefilter-days,
    # outer-days, limit.
    inner = sql.index("COALESCE(GREATEST")
    outer = sql.index("WHERE last_activity_at <")
    assert inner < outer, "prefilter must precede the outer filter in the text"
    assert params == (7, ("A", "B"), ("new", "contacted"), 5, 5, 50), params


def _extract_cooling_fn():
    """Rebuild the cooling statement exactly as pipeline_alerts issues it.

    Calling the endpoint would drag in auth, entitlements and the quota masker;
    what is under test is the statement and its parameter tuple, so this mirrors
    only that, reading the same module-level constants the endpoint does.
    """
    CARD_COLS = pipeline_routes.CARD_COLS
    PREFILTER = pipeline_routes.COOLING_PREFILTER

    def fn(cur, *, acct, cooling_days, limit):
        cur.execute(
            f"SELECT * FROM ("
            f"  SELECT {CARD_COLS}, GREATEST("
            f"    stage_moved_at, created_at,"
            f"    COALESCE((SELECT MAX(created_at) FROM contact_notes   WHERE property_id = properties.id), created_at),"
            f"    COALESCE((SELECT MAX(created_at) FROM contact_history WHERE property_id = properties.id), created_at)"
            f"  ) AS last_activity_at "
            f"  FROM properties "
            f"  WHERE account_id = %s AND archived_at IS NULL AND score_grade IN %s AND status IN %s"
            f"    AND {PREFILTER}"
            f") s "
            f"WHERE last_activity_at < NOW() - make_interval(days => %s) "
            f"ORDER BY lead_score DESC NULLS LAST LIMIT %s",
            (acct, pipeline_routes.COOLING_GRADES,
             pipeline_routes.COOLING_ACTIVE_STATUSES, cooling_days,
             cooling_days, limit),
        )
    return fn


def test_the_mirror_matches_the_real_endpoint_source():
    """_extract_cooling_fn duplicates the statement, so it can drift from the
    endpoint and keep passing. Pin the shared, load-bearing fragments against
    the real source file."""
    import inspect
    src = inspect.getsource(pipeline_routes.pipeline_alerts)
    assert "AND {COOLING_PREFILTER}" in src, \
        "the endpoint no longer applies the prefilter inside the scan"
    assert "cooling_days,\n             cooling_days" in src, \
        "the endpoint no longer binds cooling_days twice"
