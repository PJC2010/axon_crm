"""
Tests for pipeline/property.py response normalizers.

Network is mocked by monkeypatching get_json_result, so these stay pure/offline.
_rentcast_detail returns (data, answered); `answered` is False only when the
lookup never got a response, which is what stops a vendor outage from stamping
rows as checked. See pipeline/http.py::get_json_result.
"""
import pipeline.property as prop


def _stub(monkeypatch, payload, answered=True):
    monkeypatch.setattr(prop, "get_json_result", lambda *a, **k: (payload, answered))


def test_rentcast_detail_maps_fields(monkeypatch):
    fixture = [{
        "yearBuilt": 2005,
        "squareFootage": 1800,
        "price": 300000,
        "lastSaleDate": "2018-09-01",
        "lastSalePrice": 240000,
        "owner": {"names": ["JOHN SMITH"], "type": "Individual"},
        "ownerOccupied": True,
        "features": {"garage": True, "garageSpaces": 2, "garageType": "Garage"},
    }]
    _stub(monkeypatch, fixture)
    out, answered = prop._rentcast_detail("123 Main St", "77002")
    assert answered is True
    assert out["year_built"] == 2005
    # Owner name comes from the nested owner.names list, not flat ownerName.
    assert out["owner_name"] == "JOHN SMITH"
    assert out["estimated_value"] == 300000
    assert isinstance(out["estimated_equity"], int)
    assert out["ownership_years"] >= 0
    # Garage now pulled from the nested features object (was previously dropped).
    assert out["garage_spaces"] == 2
    assert out["garage_type"] == "Garage"


def test_rentcast_detail_missing_features_block(monkeypatch):
    # No features/owner objects → those fields are None, not a crash.
    _stub(monkeypatch, [{"price": 100000}])
    out, _ = prop._rentcast_detail("x", "y")
    assert out["garage_spaces"] is None
    assert out["garage_type"] is None
    assert out["owner_name"] is None


def test_rentcast_detail_owner_flat_fallback(monkeypatch):
    # Older/flat shape with no nested owner object still resolves owner_name.
    _stub(monkeypatch, [{"price": 100000, "ownerName": "FLAT OWNER"}])
    out, _ = prop._rentcast_detail("x", "y")
    assert out["owner_name"] == "FLAT OWNER"


def test_rentcast_detail_fills_lot_size_and_property_type(monkeypatch):
    """Both are tracked coverage columns and lot_size feeds job-value estimation,
    but neither used to be read off a record we were already paying for."""
    _stub(monkeypatch, [{"lotSize": 7200, "propertyType": "Single Family",
                         "subdivision": "Summerwood"}])
    out, _ = prop._rentcast_detail("x", "y")
    assert out["lot_size"] == 7200
    assert out["property_type"] == "Single Family"
    assert out["subdivision"] == "Summerwood"


def test_rentcast_detail_never_returns_coordinates(monkeypatch):
    """This step overwrites every column it returns, so carrying coordinates
    would move a pin the geocode step placed and contradict geocode_source."""
    _stub(monkeypatch, [{"latitude": 29.9, "longitude": -95.2, "city": "Houston"}])
    out, _ = prop._rentcast_detail("x", "y")
    for field in ("latitude", "longitude", "city", "state"):
        assert field not in out


def test_no_record_is_an_answer(monkeypatch):
    """An address the vendor has no record of: nothing to map, but it answered —
    so the caller stamps the row and stops re-billing it."""
    _stub(monkeypatch, None, answered=True)
    assert prop._rentcast_detail("x", "y") == (None, True)


def test_unreachable_vendor_is_not_an_answer(monkeypatch):
    """A timeout must be distinguishable, or one outage disqualifies a whole
    batch from being retried for PROPERTY_RECHECK_DAYS."""
    _stub(monkeypatch, None, answered=False)
    assert prop._rentcast_detail("x", "y") == (None, False)
