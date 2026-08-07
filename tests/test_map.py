"""Tests for the property-map endpoints (api/routes/map.py) and the bbox filter
branch they rely on in api/routes/leads.py.

The repo has no live-DB test harness — every other suite is pure-logic — so these
tests drive the route functions directly with a fake DB connection that records
the SQL/params and returns canned rows. That verifies the Python contract
(account scoping, param ordering, bbox conditions, response-model mapping)
without needing Postgres. The SQL's aggregation semantics are exercised manually
(see the plan's verification steps), not here.
"""
import pytest

from api.routes.leads import _build_filters
from api.routes.map import map_cells, map_properties, map_zips
from api.models import MapPoint, MapZip


# ── fake DB ─────────────────────────────────────────────────────────────────────

class _FakeCursor:
    """Stands in for a psycopg2 cursor: captures execute() and replays canned
    rows in the dict_fetchall shape (description + tuple rows)."""
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, list(params) if params is not None else None))

    @property
    def description(self):
        return [(k,) for k in self._rows[0].keys()] if self._rows else []

    def fetchall(self):
        return [tuple(r.values()) for r in self._rows]


class _FakeConn:
    def __init__(self, rows):
        self.cur = _FakeCursor(rows)

    def cursor(self):
        return self.cur


# ── _build_filters bbox branch ──────────────────────────────────────────────────

class TestBuildFiltersBbox:
    def test_always_scopes_and_excludes_archived(self):
        conds, params = _build_filters(7)
        assert conds == ["account_id = %s", "archived_at IS NULL"]
        assert params == [7]

    def test_bbox_adds_lat_lng_bounds(self):
        conds, params = _build_filters(
            7, min_lat=29.0, max_lat=30.0, min_lng=-96.0, max_lng=-95.0,
        )
        for frag in ("latitude >= %s", "latitude <= %s",
                     "longitude >= %s", "longitude <= %s"):
            assert frag in conds
        assert params[0] == 7                      # account scope is always first
        for val in (29.0, 30.0, -96.0, -95.0):
            assert val in params

    def test_vertical_and_status_included_when_set(self):
        conds, params = _build_filters(1, vertical="roofing", status="new")
        assert "vertical = %s" in conds and "status = %s" in conds
        assert "roofing" in params and "new" in params


# ── /map/cells ───────────────────────────────────────────────────────────────────

_CELL_ROW = {
    "cell": "9vk03m", "name": "West End", "leads": 10, "avg_score": 72.5,
    "grade_a": 3, "grade_b": 4, "grade_c": 2, "grade_d": 1,
    "signal_count": 5, "lat": 29.7, "lng": -95.4,
}


class TestMapCells:
    def test_maps_rows_to_model(self):
        conn = _FakeConn([_CELL_ROW])
        result = map_cells(vertical=None, status=None, signal_days=30,
                           db=conn, user={"account_id": 42})
        assert len(result) == 1
        mc = result[0]
        assert mc.cell == "9vk03m"
        assert mc.signal_count == 5
        assert mc.grade_a == 3 and mc.grade_d == 1
        assert mc.avg_score == 72.5

    def test_signal_window_params_lead_and_account_scoped(self):
        conn = _FakeConn([_CELL_ROW])
        map_cells(vertical=None, status=None, signal_days=30,
                  db=conn, user={"account_id": 42})
        sql, params = conn.cur.executed[0]
        # Signal subquery binds (account_id, signal_days) before the WHERE filters.
        assert params[0] == 42
        assert params[1] == 30
        assert "geohash IS NOT NULL" in sql
        # Account scoping appears again in the WHERE clause (filter params).
        assert params[2:].count(42) >= 1

    def test_filters_threaded_through(self):
        conn = _FakeConn([_CELL_ROW])
        map_cells(vertical="roofing", status="new", signal_days=90,
                  db=conn, user={"account_id": 1})
        sql, params = conn.cur.executed[0]
        assert "vertical = %s" in sql and "status = %s" in sql
        assert "roofing" in params and "new" in params

    def test_empty_result(self):
        conn = _FakeConn([])
        assert map_cells(vertical=None, status=None, signal_days=90,
                         db=conn, user={"account_id": 1}) == []


# ── /map/properties ──────────────────────────────────────────────────────────────

_POINT_ROW = {
    "id": 1, "address": "1 A St", "latitude": 29.7, "longitude": -95.4,
    "lead_score": 80.0, "score_grade": "A", "status": "new",
    "signals": ["just_sold", "new_permit"],
}


class TestMapProperties:
    def _call(self, conn, **over):
        kwargs = dict(min_lat=29.0, min_lng=-96.0, max_lat=30.0, max_lng=-95.0,
                      vertical=None, status=None, signal_days=60, limit=500,
                      db=conn, user={"account_id": 9})
        kwargs.update(over)
        return map_properties(**kwargs)

    def test_maps_rows_with_signals(self):
        conn = _FakeConn([_POINT_ROW])
        result = self._call(conn)
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].signals == ["just_sold", "new_permit"]

    def test_bbox_in_query_and_param_order(self):
        conn = _FakeConn([_POINT_ROW])
        self._call(conn)
        sql, params = conn.cur.executed[0]
        # Correlated signal subquery binds first; LIMIT binds last.
        assert params[0] == 9 and params[1] == 60
        assert params[-1] == 500
        for frag in ("latitude >= %s", "latitude <= %s",
                     "longitude >= %s", "longitude <= %s",
                     "latitude IS NOT NULL", "longitude IS NOT NULL"):
            assert frag in sql

    def test_limit_is_honored(self):
        conn = _FakeConn([_POINT_ROW])
        self._call(conn, limit=123)
        _, params = conn.cur.executed[0]
        assert params[-1] == 123

    def test_empty_result(self):
        conn = _FakeConn([])
        assert self._call(conn) == []


class TestMapPointModel:
    def test_coordinates_required(self):
        with pytest.raises(Exception):
            MapPoint(id=1, status="new")  # missing latitude/longitude

    def test_signals_default_empty(self):
        p = MapPoint(id=1, latitude=29.7, longitude=-95.4)
        assert p.signals == []
        assert p.status == "new"


# ── /map/zips ────────────────────────────────────────────────────────────────────

_ZIP_ROW = {
    "zip": "77396", "leads": 42,
    "min_lat": 29.94, "max_lat": 29.99,
    "min_lng": -95.22, "max_lng": -95.16,
}


class TestMapZips:
    def test_maps_rows_to_model(self):
        conn = _FakeConn([_ZIP_ROW])
        result = map_zips(vertical=None, status=None, db=conn, user={"account_id": 3})
        assert len(result) == 1
        z = result[0]
        assert z.zip == "77396" and z.leads == 42
        assert z.min_lat == 29.94 and z.max_lng == -95.16

    def test_account_scoped_and_requires_coordinates(self):
        conn = _FakeConn([_ZIP_ROW])
        map_zips(vertical=None, status=None, db=conn, user={"account_id": 3})
        sql, params = conn.cur.executed[0]
        # No signal subquery here, so account scoping is the very first param.
        assert params[0] == 3
        for frag in ("zip IS NOT NULL", "latitude IS NOT NULL",
                     "longitude IS NOT NULL", "archived_at IS NULL", "GROUP BY zip"):
            assert frag in sql

    def test_filters_threaded_through(self):
        conn = _FakeConn([_ZIP_ROW])
        map_zips(vertical="roofing", status="new", db=conn, user={"account_id": 1})
        sql, params = conn.cur.executed[0]
        assert "vertical = %s" in sql and "status = %s" in sql
        assert "roofing" in params and "new" in params

    def test_extent_is_outlier_resistant(self):
        """The extent must use percentiles, not MIN/MAX: a handful of rows with a
        mis-geocoded lat/lng would otherwise stretch a ZIP's box across states and
        make the jump-to-ZIP fit useless."""
        conn = _FakeConn([_ZIP_ROW])
        map_zips(vertical=None, status=None, db=conn, user={"account_id": 1})
        sql, _ = conn.cur.executed[0]
        assert sql.count("percentile_cont") == 4
        assert "MIN(latitude)" not in sql and "MAX(longitude)" not in sql

    def test_empty_result(self):
        conn = _FakeConn([])
        assert map_zips(vertical=None, status=None, db=conn, user={"account_id": 1}) == []


class TestMapZipModel:
    def test_extent_required(self):
        with pytest.raises(Exception):
            MapZip(zip="77396", leads=1)  # missing the bounding box

    def test_round_trips_extent(self):
        z = MapZip(zip="77346", leads=7, min_lat=29.9, min_lng=-95.3,
                   max_lat=30.0, max_lng=-95.1)
        assert (z.min_lat, z.min_lng, z.max_lat, z.max_lng) == (29.9, -95.3, 30.0, -95.1)
