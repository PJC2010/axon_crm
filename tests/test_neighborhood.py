"""Tests for pipeline/neighborhood.py — the ZIP-scoped value benchmark.

The scoped path exists to make a per-ZIP pipeline run cost O(ZIP) instead of
O(account). It is only safe if the *numbers* don't move, and the numbers live in
SQL, so what these tests pin is the SQL's shape: the row set is bounded by CELL
and never by ZIP (a cell straddling a ZIP line must still be measured over every
member), and the reset covers exactly the rows the recompute rewrites.

Fake-conn style — no live DB. `scripts/verify_neighborhood_scoping.py` is the
companion check that runs both paths against a real database and diffs the
values row by row.
"""
import pytest

from pipeline import neighborhood as nb


class _ScriptedCursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []
        self.rowcount = self._conn.rowcounts.pop(0) if self._conn.rowcounts else 0

    def fetchall(self):
        return list(self._current)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _ScriptedConn:
    def __init__(self, responses=(), rowcounts=()):
        self.responses = list(responses)
        self.rowcounts = list(rowcounts)
        self.executed = []
        self.commits = 0

    def cursor(self):
        return _ScriptedCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


@pytest.fixture
def _no_geohash_backfill(monkeypatch):
    """Neuter the self-healing geohash backfill — exercised separately below."""
    monkeypatch.setattr(nb, "backfill_geohashes", lambda *a, **k: 0)


def _sql_of(conn, needle):
    return [sql for sql, _ in conn.executed if needle in sql]


# ── Account-wide path (unchanged behaviour) ──────────────────────────────────

@pytest.mark.usefixtures("_no_geohash_backfill")
class TestAccountWide:
    def test_no_cell_predicate_anywhere(self):
        conn = _ScriptedConn(rowcounts=[0, 7])
        assert nb.recompute_neighborhood_values(conn, 5) == 7
        # Two statements: the reset and the windowed recompute. Neither may carry
        # a cell scope — this is the sweep that must still cover the whole org.
        assert len(conn.executed) == 2
        for sql, params in conn.executed:
            assert "= ANY(%(cells)s)" not in sql
            assert params["acct"] == 5
        assert conn.commits == 1

    def test_empty_zip_list_is_account_wide(self):
        # A caller that lost its ZIP must not silently under-compute.
        conn = _ScriptedConn(rowcounts=[0, 3])
        assert nb.recompute_neighborhood_values(conn, 5, zips=[]) == 3
        assert not _sql_of(conn, "= ANY(%(cells)s)")
        conn = _ScriptedConn(rowcounts=[0, 3])
        assert nb.recompute_neighborhood_values(conn, 5, zips=[None, ""]) == 3
        assert not _sql_of(conn, "= ANY(%(cells)s)")


# ── Scoped path ──────────────────────────────────────────────────────────────

@pytest.mark.usefixtures("_no_geohash_backfill")
class TestScoped:
    def _run(self, cells=(("9vk1aa",), ("9vk1ab",)), updated=41):
        conn = _ScriptedConn(responses=[list(cells)], rowcounts=[0, 0, updated])
        rows = nb.recompute_neighborhood_values(conn, 5, zips=["77073"])
        return conn, rows

    def test_resolves_touched_cells_from_the_zip(self):
        conn, _ = self._run()
        sql, params = conn.executed[0]
        assert "SELECT DISTINCT LEFT(geohash, %(prec)s)" in sql
        assert "zip = ANY(%(zips)s)" in sql
        assert "archived_at IS NULL" in sql
        assert params == {"prec": nb.GEOHASH_PRECISION, "acct": 5, "zips": ["77073"]}

    def test_reset_and_recompute_cover_the_same_rows(self):
        # Resetting a wider row set than the recompute rewrites would leave
        # untouched rows permanently NULL — the one asymmetry that silently
        # corrupts the column.
        conn, _ = self._run()
        reset_sql, reset_params = conn.executed[1]
        recompute_sql, recompute_params = conn.executed[2]
        scope = "LEFT(geohash, %(prec)s) = ANY(%(cells)s)"
        assert "neighborhood_value_ratio = NULL" in reset_sql
        assert scope in reset_sql
        assert scope in recompute_sql
        assert reset_params["cells"] == recompute_params["cells"] == ["9vk1aa", "9vk1ab"]
        assert reset_params["acct"] == recompute_params["acct"] == 5

    def test_row_set_is_bounded_by_cell_not_by_zip(self):
        """The load-bearing property: a boundary cell keeps every member.

        If the recompute filtered on `zip` too, a cell straddling a ZIP line
        would be measured over half its members and the median would move.
        """
        conn, _ = self._run()
        recompute_sql, params = conn.executed[2]
        assert "zip = ANY" not in recompute_sql
        assert "zips" not in params
        # ...and every fallback tier is still derived from that same row set.
        for cte in ("cell_stats", "nbhd_stats", "zip_stats", "ranked"):
            assert f"{cte} AS" in recompute_sql
        assert recompute_sql.count("FROM vals") >= 4

    def test_returns_rows_written_and_commits_once(self):
        conn, rows = self._run(updated=41)
        assert rows == 41
        assert conn.commits == 1

    def test_no_geocoded_rows_skips_rather_than_widening(self):
        # Falling back to the account-wide rewrite here would silently reinstate
        # the cost this scoping exists to remove.
        conn = _ScriptedConn(responses=[[]], rowcounts=[0])
        assert nb.recompute_neighborhood_values(conn, 5, zips=["77073"]) == 0
        assert len(conn.executed) == 1        # only the touched-cell lookup
        assert conn.commits == 0

    def test_null_cells_are_dropped(self):
        conn = _ScriptedConn(responses=[[("9vk1aa",), (None,)]], rowcounts=[0, 0, 2])
        nb.recompute_neighborhood_values(conn, 5, zips=["77073"])
        assert conn.executed[2][1]["cells"] == ["9vk1aa"]

    def test_multi_zip_scope(self):
        conn = _ScriptedConn(responses=[[("9vk1aa",)]], rowcounts=[0, 0, 9])
        nb.recompute_neighborhood_values(conn, 5, zips=["77073", "77090"])
        assert conn.executed[0][1]["zips"] == ["77073", "77090"]


class TestTouchedCells:
    def test_deduplicates_and_sorts(self):
        conn = _ScriptedConn(responses=[[("9vk1ab",), ("9vk1aa",), ("9vk1ab",)]])
        assert nb.touched_cells(conn, 5, ["77073"]) == ["9vk1aa", "9vk1ab"]

    def test_uses_the_grouping_precision(self):
        # The scope key must be the same precision the cell grouping uses, not
        # the (longer) stored precision.
        conn = _ScriptedConn(responses=[[]])
        nb.touched_cells(conn, 5, ["77073"])
        assert conn.executed[0][1]["prec"] == nb.GEOHASH_PRECISION
        assert nb.GEOHASH_PRECISION < nb.GEOHASH_STORE_PRECISION


class TestBackfillGeohashes:
    def test_scopes_the_scan_to_the_given_zips(self, monkeypatch):
        monkeypatch.setattr(nb, "_encode", lambda lat, lng: "9vk1aab")
        conn = _ScriptedConn(responses=[[]])
        assert nb.backfill_geohashes(conn, 5, zips=["77073"]) == 0
        sql, params = conn.executed[0]
        assert "zip = ANY(%(zips)s)" in sql
        assert params == {"acct": 5, "zips": ["77073"]}

    def test_account_wide_by_default(self, monkeypatch):
        monkeypatch.setattr(nb, "_encode", lambda lat, lng: "9vk1aab")
        conn = _ScriptedConn(responses=[[]])
        nb.backfill_geohashes(conn, 5)
        sql, params = conn.executed[0]
        assert "zip = ANY" not in sql
        assert params == {"acct": 5}

    def test_no_geohash_library_is_a_clean_noop(self, monkeypatch):
        monkeypatch.setattr(nb, "_encode", lambda lat, lng: None)
        conn = _ScriptedConn()
        assert nb.backfill_geohashes(conn, 5, zips=["77073"]) == 0
        assert conn.executed == []
