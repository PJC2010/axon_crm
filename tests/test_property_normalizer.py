"""
Tests for pipeline/property.py response normalizers.

Network is mocked by monkeypatching get_json, so these stay pure/offline.
"""
import pipeline.property as prop


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
    monkeypatch.setattr(prop, "get_json", lambda *a, **k: fixture)
    out = prop._rentcast_detail("123 Main St", "77002")
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
    monkeypatch.setattr(prop, "get_json", lambda *a, **k: [{"price": 100000}])
    out = prop._rentcast_detail("x", "y")
    assert out["garage_spaces"] is None
    assert out["garage_type"] is None
    assert out["owner_name"] is None


def test_rentcast_detail_owner_flat_fallback(monkeypatch):
    # Older/flat shape with no nested owner object still resolves owner_name.
    monkeypatch.setattr(prop, "get_json",
                        lambda *a, **k: [{"price": 100000, "ownerName": "FLAT OWNER"}])
    out = prop._rentcast_detail("x", "y")
    assert out["owner_name"] == "FLAT OWNER"
