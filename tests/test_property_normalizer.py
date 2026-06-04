"""
Tests for pipeline/property.py response normalizers.

Network is mocked by monkeypatching get_json, so these stay pure/offline. They
lock in that Attom now yields the FULL field set (value/sale/owner/year), not
just garage — the core fix for missing columns.
"""
import pipeline.property as prop


def test_attom_extracts_full_field_set(monkeypatch):
    fixture = {
        "property": [{
            "summary": {"yearbuilt": 1998},
            "building": {
                "size": {"livingsize": 2400},
                "parking": {"garageType": "Attached", "prkgSize": 600},
            },
            "lot": {"lotsize2": 8000},
            "assessment": {
                "assessed": {"assdttlvalue": 320000},
                "market": {"mktttlvalue": 410000},
                "sale": {"amount": {"saleamt": 250000}, "salesearchdate": "2015-04-01"},
                "owner": {"owner1": {"fullname": "JANE DOE"}, "absenteeownerstatus": "O"},
                "mortgage": {"lender": {"balance": 120000}},
            },
        }]
    }
    monkeypatch.setattr(prop, "get_json", lambda *a, **k: fixture)

    out = prop._attom_detail("123 Main St", "77002")
    assert out["year_built"] == 1998
    assert out["square_footage"] == 2400
    assert out["lot_size"] == 8000
    assert out["estimated_value"] == 320000
    assert out["last_sale_price"] == 250000
    assert out["last_sale_date"] == "2015-04-01"
    assert out["owner_name"] == "JANE DOE"
    assert out["owner_occupied"] is True
    assert out["garage_spaces"] == 3        # >=550 sqft
    assert out["garage_type"] == "Attached"
    # equity uses the known mortgage balance: 320000 - 120000
    assert out["estimated_equity"] == 200000


def test_attom_handles_empty_response(monkeypatch):
    monkeypatch.setattr(prop, "get_json", lambda *a, **k: None)
    assert prop._attom_detail("x", "y") is None


def test_attom_missing_blocks_dont_crash(monkeypatch):
    monkeypatch.setattr(prop, "get_json", lambda *a, **k: {"property": [{}]})
    out = prop._attom_detail("x", "y")
    assert out["year_built"] is None
    assert out["garage_spaces"] is None


def test_rentcast_detail_maps_fields(monkeypatch):
    fixture = [{
        "yearBuilt": 2005,
        "squareFootage": 1800,
        "price": 300000,
        "lastSaleDate": "2018-09-01",
        "lastSalePrice": 240000,
        "ownerName": "JOHN SMITH",
        "ownerOccupied": True,
    }]
    monkeypatch.setattr(prop, "get_json", lambda *a, **k: fixture)
    out = prop._rentcast_detail("123 Main St", "77002")
    assert out["year_built"] == 2005
    assert out["owner_name"] == "JOHN SMITH"
    assert out["estimated_value"] == 300000
    assert isinstance(out["estimated_equity"], int)
    assert out["ownership_years"] >= 0
