"""
Tests for pipeline/seed.py _normalize_rentcast — the records→row mapper.

Pure/offline: just exercises the dict transform. Locks in that garage data is
pulled from the nested `features` object (previously dropped on seed).
"""
import pipeline.seed as seed
from pipeline.seed import _normalize_rentcast, _normalize_hcad, _wanted_type


def test_normalize_extracts_garage_from_features():
    record = {
        "addressLine1": "123 Main St",
        "city": "Houston",
        "state": "TX",
        "zipCode": "77002",
        "yearBuilt": 2005,
        "features": {"garage": True, "garageSpaces": 3, "garageType": "Detached"},
    }
    row = _normalize_rentcast(record)
    assert row["garage_spaces"] == 3
    assert row["garage_type"] == "Detached"
    assert row["year_built"] == 2005


def test_normalize_missing_features_block():
    row = _normalize_rentcast({"addressLine1": "1 A St", "zipCode": "77002"})
    assert row["garage_spaces"] is None
    assert row["garage_type"] is None
    assert row["owner_name"] is None


def test_normalize_extracts_owner_name_from_nested_list():
    # Real RentCast shape: owner.names is a list; first entry is the owner.
    record = {"addressLine1": "5 B St", "zipCode": "77002",
              "owner": {"names": ["ACME HOLDINGS LLC"], "type": "Organization"}}
    row = _normalize_rentcast(record)
    assert row["owner_name"] == "ACME HOLDINGS LLC"


def test_normalize_owner_flat_fallback():
    # No nested owner object → fall back to a flat ownerName if present.
    row = _normalize_rentcast({"addressLine1": "6 C St", "zipCode": "77002",
                               "ownerName": "FLAT OWNER"})
    assert row["owner_name"] == "FLAT OWNER"


def test_normalize_nulls_placeholder_owner():
    # Assessor placeholders must land as NULL so the row stays eligible for the
    # paid owner fill — a stored "CURRENT OWNER" blocks it (pipeline/owner.py).
    row = _normalize_rentcast({"addressLine1": "7 D St", "zipCode": "77002",
                               "owner": {"names": ["CURRENT OWNER"]}})
    assert row["owner_name"] is None


def test_normalize_records_origin_zip_in_flags():
    row = _normalize_rentcast({"zipCode": "77003"}, origin_zip="77002")
    assert row["enrichment_flags"]["seed_origin_zip"] == "77002"


def test_normalize_maps_parcel_and_ride_along_features():
    """Seeding reads the same paid response the detail step does — the parcel
    number and migration-068 features must land at seed time, for free."""
    row = _normalize_rentcast({
        "addressLine1": "8 E St", "zipCode": "77002",
        "assessorID": "066-064-013-0020",
        "owner": {"names": ["JANE DOE"], "type": "Organization"},
        "features": {"roofType": "Asphalt", "pool": True},
    })
    assert row["parcel_apn"] == "0660640130020"
    assert row["owner_type"] == "Organization"
    assert row["roof_type"] == "Asphalt"
    assert row["has_pool"] is True


def test_normalize_estimated_value_from_tax_assessments():
    # /properties records carry no flat price; the assessed value is the live
    # source (see reconcile._latest_assessment).
    row = _normalize_rentcast({
        "addressLine1": "9 F St", "zipCode": "77002",
        "taxAssessments": {"2024": {"year": 2024, "value": 216_513}},
    })
    assert row["estimated_value"] == 216_513


def test_normalize_geocode_provenance_only_with_coordinates():
    located = _normalize_rentcast({"addressLine1": "10 G St", "zipCode": "77002",
                                   "latitude": 29.7, "longitude": -95.3})
    assert located["geocode_source"] == "rentcast"
    unlocated = _normalize_rentcast({"addressLine1": "11 H St", "zipCode": "77002"})
    assert unlocated.get("geocode_source") is None


# ── _normalize_hcad (free DuckDB seed mapper) ─────────────────────────────────

def _hcad_parcel(**over):
    base = {
        "site_address": "7003 PINETEX DR", "site_city": "HUMBLE",
        "site_zip": "77396",
        "year_built": 1960, "square_footage": 1849,
        "lot_size": 7480, "estimated_value": 234193,
        "last_sale_date": "2014-10-02", "owner_name": "CAPUCHINA LIZETTE",
        "owner_occupied": True, "mailing_address": "7003 PINETEX DR, HUMBLE TX 77396",
        "neighborhood_code": "8901.44", "neighborhood_name": "PINE TRAILS",
        "parcel_apn": "1163040000015",
    }
    base.update(over)
    return base


def test_normalize_hcad_maps_core_fields():
    row = _normalize_hcad(_hcad_parcel(), region_id="8901.44")
    assert row["address"] == "7003 PINETEX DR"
    assert row["zip"] == "77396"
    assert row["state"] == "TX"
    assert row["year_built"] == 1960
    assert row["estimated_value"] == 234193
    assert row["hcad_neighborhood_code"] == "8901.44"
    assert row["hcad_neighborhood_name"] == "PINE TRAILS"


def test_normalize_hcad_carries_the_parcel_number():
    # The acct is the identity the RentCast step later verifies assessorID
    # against — dropping it here would make every seeded row unverifiable.
    row = _normalize_hcad(_hcad_parcel())
    assert row["parcel_apn"] == "1163040000015"
    row = _normalize_hcad(_hcad_parcel(parcel_apn=None))
    assert row["parcel_apn"] is None


def test_normalize_hcad_no_latlng_geocode_fills_later():
    row = _normalize_hcad(_hcad_parcel(), region_id="8901.44")
    assert row["latitude"] is None
    assert row["longitude"] is None


def test_normalize_hcad_flags_record_source_and_region():
    row = _normalize_hcad(_hcad_parcel(), region_id="8901.44")
    assert row["enrichment_flags"]["seed"] == "hcad"
    assert row["enrichment_flags"]["hcad_region"] == "8901.44"


def test_normalize_hcad_zip_seed_omits_region_flag():
    # ZIP-level free seed (seed_from_hcad_zip) passes no region_id: the source is
    # still flagged "hcad" but no hcad_region key is written.
    row = _normalize_hcad(_hcad_parcel())
    assert row["enrichment_flags"]["seed"] == "hcad"
    assert "hcad_region" not in row["enrichment_flags"]


def test_normalize_hcad_city_is_situs_never_mail_city():
    # city is the parcel's OWN city (site_addr_2). The owner's mailing city is
    # a fact about the owner, not the parcel: an absentee owner who gets mail
    # in Lake Dallas once labeled a Houston lead (ZIP 77073) "LAKE DALLAS, TX"
    # on the card and in every geocode query built from the row.
    row = _normalize_hcad(
        _hcad_parcel(site_city="HOUSTON", mail_city="LAKE DALLAS"),
        region_id="r")
    assert row["city"] == "HOUSTON"


def test_normalize_hcad_missing_site_city_stays_null():
    # A source predating site_city (old DuckDB / mirror row) must yield NULL —
    # the UI drops empty address parts ("ADDRESS, TX") and enrichment or a
    # RentCast lookup fills the real city later. Never substitute mail_city.
    p = _hcad_parcel(mail_city="LAKE DALLAS")
    p.pop("site_city")
    row = _normalize_hcad(p)
    assert row["city"] is None


# ── _wanted_type (property-type filter) ───────────────────────────────────────

def test_wanted_type_keeps_target_types(monkeypatch):
    monkeypatch.setattr(seed, "SEED_PROPERTY_TYPES",
                        ["Single Family", "Condo", "Townhouse", "Manufactured"])
    assert _wanted_type("Single Family") is True
    assert _wanted_type("Condo") is True
    assert _wanted_type("Manufactured") is True


def test_wanted_type_drops_apartment_and_multifamily(monkeypatch):
    monkeypatch.setattr(seed, "SEED_PROPERTY_TYPES",
                        ["Single Family", "Condo", "Townhouse", "Manufactured"])
    assert _wanted_type("Apartment") is False
    assert _wanted_type("Multi-Family") is False
    assert _wanted_type("Land") is False


def test_wanted_type_keeps_missing_type(monkeypatch):
    # No propertyType on the record → kept (no grounds to drop).
    monkeypatch.setattr(seed, "SEED_PROPERTY_TYPES", ["Single Family"])
    assert _wanted_type(None) is True
    assert _wanted_type("") is True


def test_wanted_type_wildcard_disables_filter(monkeypatch):
    monkeypatch.setattr(seed, "SEED_PROPERTY_TYPES", ["*"])
    assert _wanted_type("Apartment") is True
    # Empty allowlist also disables the filter.
    monkeypatch.setattr(seed, "SEED_PROPERTY_TYPES", [])
    assert _wanted_type("Apartment") is True
