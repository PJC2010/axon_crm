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
        "addressLine1": "123 Main St",
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
    _stub(monkeypatch, [{"addressLine1": "x", "price": 100000}])
    out, _ = prop._rentcast_detail("x", "y")
    assert out["garage_spaces"] is None
    assert out["garage_type"] is None
    assert out["owner_name"] is None


def test_rentcast_detail_owner_flat_fallback(monkeypatch):
    # Older/flat shape with no nested owner object still resolves owner_name.
    _stub(monkeypatch, [{"addressLine1": "x", "price": 100000, "ownerName": "FLAT OWNER"}])
    out, _ = prop._rentcast_detail("x", "y")
    assert out["owner_name"] == "FLAT OWNER"


def test_rentcast_detail_fills_lot_size_and_property_type(monkeypatch):
    """Both are tracked coverage columns and lot_size feeds job-value estimation,
    but neither used to be read off a record we were already paying for."""
    _stub(monkeypatch, [{"addressLine1": "x", "lotSize": 7200,
                         "propertyType": "Single Family",
                         "subdivision": "Summerwood"}])
    out, _ = prop._rentcast_detail("x", "y")
    assert out["lot_size"] == 7200
    assert out["property_type"] == "Single Family"
    assert out["subdivision"] == "Summerwood"


def test_rentcast_detail_rides_along_parcel_and_features(monkeypatch):
    """The migration-068 set: parcel identity plus county-record features, read
    off the same paid call rather than triggering new ones."""
    _stub(monkeypatch, [{"addressLine1": "x",
                         "assessorID": "066-064-013-0020",
                         "taxAssessments": {"2024": {"year": 2024, "value": 216_513}},
                         "owner": {"names": ["JANE DOE"], "type": "Individual"},
                         "features": {"roofType": "Asphalt",
                                      "foundationType": "Slab", "pool": True}}])
    out, _ = prop._rentcast_detail("x", "y")
    assert out["parcel_apn"] == "0660640130020"
    assert out["roof_type"] == "Asphalt"
    assert out["foundation_type"] == "Slab"
    assert out["has_pool"] is True
    assert out["owner_type"] == "Individual"
    # No flat price on current responses — assessed value carries the estimate.
    assert out["estimated_value"] == 216_513


def test_rentcast_detail_never_returns_coordinates(monkeypatch):
    """This step overwrites every column it returns, so carrying coordinates
    would move a pin the geocode step placed and contradict geocode_source."""
    _stub(monkeypatch, [{"addressLine1": "x", "latitude": 29.9,
                         "longitude": -95.2, "city": "Houston"}])
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


# ── Verification ──────────────────────────────────────────────────────────────
# The lookup is by address string and RentCast's own parser decides what that
# resolves to, with limit=1 hiding any ambiguity. Without a check, a neighbouring
# parcel's data lands on the row and the row is stamped as enriched.

def test_a_wrong_property_is_rejected(monkeypatch):
    _stub(monkeypatch, [{"addressLine1": "125 Main St", "yearBuilt": 1998}])
    data, answered = prop._rentcast_detail("123 Main St", "77396")
    assert data is None
    # Still an answer — RentCast responded, so the caller stamps the row rather
    # than re-billing this address on every future run.
    assert answered is True


def test_a_differently_formatted_same_address_is_accepted(monkeypatch):
    """Rejecting on formatting would discard data already paid for."""
    _stub(monkeypatch, [{"addressLine1": "123 MAIN STREET", "yearBuilt": 1998}])
    data, _ = prop._rentcast_detail("123 Main St", "77396")
    assert data["year_built"] == 1998


def test_formatted_address_is_enough_to_verify(monkeypatch):
    _stub(monkeypatch, [{"formattedAddress": "123 Main St, Houston, TX 77396",
                         "yearBuilt": 1998}])
    data, _ = prop._rentcast_detail("123 Main St", "77396")
    assert data["year_built"] == 1998


def test_an_unverifiable_record_is_rejected(monkeypatch):
    """Deliberate: a record carrying no address at all cannot be checked, and
    accepting it would restore the silent-wrong-parcel hole. If RentCast ever
    stops returning an address this fails loudly and uniformly (every row counts
    as an address mismatch) rather than quietly writing unverifiable data."""
    _stub(monkeypatch, [{"yearBuilt": 1998}])
    assert prop._rentcast_detail("123 Main St", "77396") == (None, True)
