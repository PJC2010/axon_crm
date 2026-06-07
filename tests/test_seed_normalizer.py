"""
Tests for pipeline/seed.py _normalize_rentcast — the records→row mapper.

Pure/offline: just exercises the dict transform. Locks in that garage data is
pulled from the nested `features` object (previously dropped on seed).
"""
import pipeline.seed as seed
from pipeline.seed import _normalize_rentcast, _wanted_type


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
