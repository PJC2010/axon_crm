"""
Tests for pipeline/parcel_centroids.py — ArcGIS request building and response
parsing for the county parcel layer. Pure: no HTTP, no database (same split as
tests/test_geocode_batch.py).
"""
import pytest

from pipeline.parcel_centroids import (
    ARCGIS_PAGE_SIZE, ArcGISError, count_params, parse_count, parse_page,
    query_params,
)


def _feature(oid, acct="0221090010009", lon=-95.25, lat=29.97, centroid=True):
    feature = {"attributes": {"OBJECTID": oid, "acct_num": acct}}
    if centroid:
        feature["centroid"] = {"x": lon, "y": lat}
    return feature


# ── Request building ──────────────────────────────────────────────────────────

def test_query_params_keyset_shape():
    params = query_params(41)
    assert params["where"] == "OBJECTID > 41"
    assert params["orderByFields"] == "OBJECTID"
    # OBJECTID must be in outFields or the parser cannot advance the cursor.
    assert params["outFields"] == "OBJECTID,acct_num"
    assert params["returnGeometry"] == "false"
    assert params["returnCentroid"] == "true"
    # The layer's native SR is Texas State Plane FEET — outSR=4326 is what
    # makes centroids come back as WGS84 lon/lat.
    assert params["outSR"] == 4326
    assert params["resultRecordCount"] == ARCGIS_PAGE_SIZE
    assert params["f"] == "json"


def test_query_params_coerces_the_cursor_to_int():
    """The cursor is interpolated into the where clause; int() is the guard."""
    assert query_params("41")["where"] == "OBJECTID > 41"
    with pytest.raises((TypeError, ValueError)):
        query_params("41; DROP TABLE parcels")
    with pytest.raises((TypeError, ValueError)):
        query_params(None)


def test_count_params_shape():
    params = count_params()
    assert params["returnCountOnly"] == "true"
    assert params["f"] == "json"


# ── parse_count ───────────────────────────────────────────────────────────────

def test_parse_count_happy_path():
    assert parse_count({"count": 1535525}) == 1535525


@pytest.mark.parametrize("payload", [
    None,                                       # transport gave nothing usable
    {"error": {"code": 400, "message": "Invalid query parameters."}},
    {"features": []},                           # a page, not a count
    [],                                         # not even a dict
])
def test_parse_count_rejects_non_counts(payload):
    with pytest.raises(ArcGISError):
        parse_count(payload)


# ── parse_page ────────────────────────────────────────────────────────────────

def test_parse_page_happy_path():
    rows, meta = parse_page({"features": [
        _feature(1, acct="0221090010009", lon=-95.25, lat=29.97),
        _feature(2, acct="0441720000105", lon=-95.23, lat=29.99),
    ]})
    assert rows == [(1, "0221090010009", -95.25, 29.97),
                    (2, "0441720000105", -95.23, 29.99)]
    assert meta == {"features": 2, "no_acct": 0, "no_centroid": 0,
                    "last_objectid": 2}


def test_parse_page_keeps_leading_zeros_as_text():
    rows, _ = parse_page({"features": [_feature(1, acct="0000123400056")]})
    assert rows[0][1] == "0000123400056"


def test_parse_page_skips_and_counts_features_without_an_account():
    """~0.8% of real layer features carry no acct_num — that is the feature's
    defect, not the run's."""
    rows, meta = parse_page({"features": [
        _feature(1, acct=None),
        _feature(2, acct="   "),
        _feature(3),
    ]})
    assert [r[0] for r in rows] == [3]
    assert meta["no_acct"] == 2


def test_parse_page_skips_and_counts_features_without_a_centroid():
    rows, meta = parse_page({"features": [
        _feature(1, centroid=False),
        _feature(2),
    ]})
    assert [r[0] for r in rows] == [2]
    assert meta["no_centroid"] == 1


def test_cursor_advances_even_when_every_feature_is_skipped():
    """A page of acct-less features must still move last_objectid, or the
    download loops on the same page forever."""
    rows, meta = parse_page({"features": [_feature(7, acct=None),
                                          _feature(9, acct=None)]})
    assert rows == []
    assert meta["last_objectid"] == 9


def test_parse_page_accepts_exceeded_transfer_limit_pages():
    """exceededTransferLimit marks a capped page — normal, NOT the end of the
    data. Termination is an EMPTY page, which reports last_objectid None."""
    rows, meta = parse_page({"features": [_feature(1)],
                             "exceededTransferLimit": True})
    assert len(rows) == 1

    rows, meta = parse_page({"features": []})
    assert rows == []
    assert meta == {"features": 0, "no_acct": 0, "no_centroid": 0,
                    "last_objectid": None}


def test_parse_page_raises_on_error_payloads():
    """ArcGIS delivers errors as HTTP 200 with an {"error": ...} body, so the
    parser is the only place they can be caught."""
    with pytest.raises(ArcGISError):
        parse_page({"error": {"code": 400, "message": "Invalid query."}})
    with pytest.raises(ArcGISError):
        parse_page(None)
    with pytest.raises(ArcGISError):
        parse_page({"fields": []})   # no features array


def test_parse_page_raises_on_state_plane_sized_coordinates():
    """A coordinate in the millions means outSR=4326 was dropped and EVERY
    subsequent feature is equally poisoned — run-fatal, never a skip."""
    with pytest.raises(ArcGISError):
        parse_page({"features": [_feature(1, lon=3081234.0, lat=13876543.0)]})


def test_parse_page_raises_on_swapped_lat_lon():
    with pytest.raises(ArcGISError):
        parse_page({"features": [_feature(1, lon=29.97, lat=-95.25)]})


def test_parse_page_raises_when_objectid_is_missing():
    """Without OBJECTID (an outFields mistake) keyset paging cannot advance."""
    with pytest.raises(ArcGISError):
        parse_page({"features": [{"attributes": {"acct_num": "0221090010009"},
                                  "centroid": {"x": -95.25, "y": 29.97}}]})
