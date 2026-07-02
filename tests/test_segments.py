"""Tests for saved segments (api/routes/segments.py): filter-key whitelist,
account scoping, and delete permissions — fake-conn style, no live DB."""
import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from api.routes.segments import (
    ALLOWED_FILTER_KEYS, _clean_filters, create_segment, delete_segment, list_segments,
)
from api.models import SegmentCreate


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    @property
    def description(self):
        rows = self._current
        if rows and isinstance(rows[0], dict):
            return [(k,) for k in rows[0].keys()]
        return []

    def fetchall(self):
        rows = self._current
        if rows and isinstance(rows[0], dict):
            return [tuple(r.values()) for r in rows]
        return list(rows)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _FakeConn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass


USER = {"id": 9, "account_id": 3, "role": "rep"}
OWNER = {"id": 1, "account_id": 3, "role": "owner"}


def _segment_row(**over):
    row = {"id": 11, "account_id": 3, "name": "Hot A leads",
           "filters": json.dumps({"grade": "A"}), "created_by": 9,
           "created_at": datetime(2026, 7, 1), "updated_at": datetime(2026, 7, 1)}
    row.update(over)
    return row


class TestCleanFilters:
    def test_allows_lead_filter_keys(self):
        filters = {"zip": "77002", "grade": "A", "sort": "score"}
        assert _clean_filters(filters) == filters

    def test_strips_pagination_and_empty_values(self):
        assert _clean_filters({"grade": "A", "page": 3, "page_size": 50, "status": ""}) == {"grade": "A"}

    def test_rejects_unknown_keys(self):
        with pytest.raises(HTTPException) as exc:
            _clean_filters({"grade": "A", "evil": "1=1"})
        assert exc.value.status_code == 400
        assert "evil" in exc.value.detail

    def test_whitelist_matches_lead_filters_contract(self):
        # Keep in lockstep with _build_filters in api/routes/leads.py.
        assert ALLOWED_FILTER_KEYS == {
            "zip", "grade", "vertical", "status", "min_value", "max_value",
            "neighborhood", "min_neighborhood_pctile", "sort",
        }


class TestRoutes:
    def test_list_scopes_by_account(self):
        conn = _FakeConn([[_segment_row()]])
        result = list_segments(db=conn, user=USER)
        sql, params = conn.executed[0]
        assert "account_id = %s" in sql
        assert params == [3]
        assert result[0]["filters"] == {"grade": "A"}   # JSON string parsed

    def test_create_inserts_scoped_row(self):
        conn = _FakeConn([[_segment_row()]])
        body = SegmentCreate(name="  Hot A leads  ", filters={"grade": "A", "page": 2})
        result = create_segment(body, db=conn, user=USER)
        sql, params = conn.executed[0]
        assert "INSERT INTO segments" in sql
        assert params[0] == 3 and params[1] == "Hot A leads"
        assert json.loads(params[2]) == {"grade": "A"}   # page stripped
        assert params[3] == 9
        assert result["name"] == "Hot A leads"

    def test_create_rejects_blank_name(self):
        with pytest.raises(HTTPException) as exc:
            create_segment(SegmentCreate(name="   "), db=_FakeConn([]), user=USER)
        assert exc.value.status_code == 400

    def test_delete_by_non_creator_rep_forbidden(self):
        conn = _FakeConn([[(1,)]])                       # created_by = someone else
        with pytest.raises(HTTPException) as exc:
            delete_segment(11, db=conn, user=USER)
        assert exc.value.status_code == 403

    def test_delete_by_owner_allowed(self):
        conn = _FakeConn([[(9,)], []])                   # created_by 9, owner deletes
        delete_segment(11, db=conn, user=OWNER)
        sql, params = conn.executed[1]
        assert "DELETE FROM segments" in sql
        assert params == [11, 3]

    def test_delete_missing_404(self):
        conn = _FakeConn([[]])
        with pytest.raises(HTTPException) as exc:
            delete_segment(11, db=conn, user=USER)
        assert exc.value.status_code == 404
