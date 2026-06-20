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


def test_normalize_records_origin_zip_in_flags():
    row = _normalize_rentcast({"zipCode": "77003"}, origin_zip="77002")
    assert row["enrichment_flags"]["seed_origin_zip"] == "77002"


# ── _normalize_hcad (free DuckDB seed mapper) ─────────────────────────────────

def _hcad_parcel(**over):
    base = {
        "site_address": "7003 PINETEX DR", "site_zip": "77396",
        "mail_city": "HUMBLE", "year_built": 1960, "square_footage": 1849,
        "lot_size": 7480, "estimated_value": 234193,
        "last_sale_date": "2014-10-02", "owner_name": "CAPUCHINA LIZETTE",
        "owner_occupied": True, "mailing_address": "7003 PINETEX DR, HUMBLE TX 77396",
        "neighborhood_code": "8901.44", "neighborhood_name": "PINE TRAILS",
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


def test_normalize_hcad_city_falls_back_to_mail_city():
    # HCAD has no site-city; city mirrors the owner's mailing city (harmless —
    # rows key on address+zip and geocode doesn't need city).
    row = _normalize_hcad(_hcad_parcel(mail_city="ATASCOCITA"), region_id="r")
    assert row["city"] == "ATASCOCITA"


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
