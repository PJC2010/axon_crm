"""Tests for pipeline/reconcile.py — pure RentCast comparison (no DB, no network)."""
from datetime import date

import pytest

from pipeline import reconcile
from pipeline.reconcile import (
    FILL, MATCH, MISMATCH, NO_REMOTE, DETAIL_FIELDS, RECONCILED_FIELDS,
    REPORTED_FIELDS, map_detail, map_record, years_owned,
)


def _record(**overrides) -> dict:
    """A realistic RentCast /properties record, shaped like the live response."""
    record = {
        "addressLine1": "123 Main St",
        "city": "Houston",
        "state": "TX",
        "zipCode": "77396",
        "latitude": 29.9,
        "longitude": -95.2,
        "propertyType": "Single Family",
        "yearBuilt": 1998,
        "squareFootage": 2100,
        "lotSize": 7200,
        "subdivision": "Summerwood",
        "price": 340_000,
        "lastSalePrice": 250_000,
        "lastSaleDate": "2015-06-01",
        "ownerOccupied": True,
        "owner": {"names": ["JANE DOE"]},
        "features": {"garageSpaces": 2, "garageType": "Attached"},
    }
    record.update(overrides)
    return record


# ── map_record ────────────────────────────────────────────────────────────────

def test_map_record_reads_nested_features_and_owner():
    mapped = map_record(_record())
    assert mapped["garage_spaces"] == 2
    assert mapped["garage_type"] == "Attached"
    assert mapped["owner_name"] == "JANE DOE"


def test_map_record_falls_back_to_flat_owner_name():
    mapped = map_record(_record(owner={}, ownerName="JOHN ROE"))
    assert mapped["owner_name"] == "JOHN ROE"


def test_map_record_nulls_placeholder_owner():
    # A vendor echoing the county's "CURRENT OWNER" placeholder must map to
    # None — it may neither fill a NULL nor mismatch against a real name.
    mapped = map_record(_record(owner={"names": ["CURRENT OWNER"]}))
    assert mapped["owner_name"] is None


def test_map_record_covers_every_reconciled_field():
    mapped = map_record(_record())
    assert set(mapped) == set(RECONCILED_FIELDS)


def test_map_record_returns_none_for_absent_data():
    mapped = map_record({})
    assert all(v is None for v in mapped.values())


def test_map_record_derives_equity_from_sale():
    mapped = map_record(_record())
    # Amortized against the 2015 sale — strictly between "no equity" and the
    # full value, which is what makes it more useful than the flat proxy.
    assert 0 < mapped["estimated_equity"] < mapped["estimated_value"]


def test_map_detail_excludes_coordinates_and_city_state():
    """The per-ZIP step overwrites what it writes, so it must not carry
    coordinates — that would move a pin the geocode step placed."""
    detail = map_detail(_record())
    assert set(detail) == set(DETAIL_FIELDS)
    for field in ("latitude", "longitude", "city", "state"):
        assert field not in detail
    assert detail["lot_size"] == 7200
    assert detail["property_type"] == "Single Family"


def test_years_owned_handles_junk():
    assert years_owned("2015-06-01") == date.today().year - 2015
    assert years_owned(None) is None
    assert years_owned("not-a-date") is None
    assert years_owned(f"{date.today().year + 5}-01-01") is None  # future sale


# ── Verdicts ──────────────────────────────────────────────────────────────────

def test_null_stored_is_a_fill():
    result = reconcile.reconcile({"year_built": None}, _record(), fields=["year_built"])
    assert result["verdicts"]["year_built"] == FILL
    assert result["updates"]["year_built"] == 1998


def test_empty_string_counts_as_missing():
    result = reconcile.reconcile({"garage_type": ""}, _record(), fields=["garage_type"])
    assert result["verdicts"]["garage_type"] == FILL


def test_agreeing_values_are_a_match_and_write_nothing():
    result = reconcile.reconcile({"year_built": 1998}, _record(), fields=["year_built"])
    assert result["verdicts"]["year_built"] == MATCH
    assert result["updates"] == {}
    assert result["findings"] == []


def test_remote_silence_is_not_a_mismatch():
    result = reconcile.reconcile({"year_built": 1998}, _record(yearBuilt=None),
                                 fields=["year_built"])
    assert result["verdicts"]["year_built"] == NO_REMOTE
    assert result["updates"] == {}


def test_text_comparison_ignores_case_and_spacing():
    stored = {"property_type": "SINGLE  family"}
    result = reconcile.reconcile(stored, _record(), fields=["property_type"])
    assert result["verdicts"]["property_type"] == MATCH


def test_date_comparison_accepts_date_objects_and_timestamps():
    stored = {"last_sale_date": date(2015, 6, 1)}
    assert reconcile.reconcile(stored, _record(), fields=["last_sale_date"]) \
        ["verdicts"]["last_sale_date"] == MATCH

    stored = {"last_sale_date": "2015-06-01T00:00:00Z"}
    assert reconcile.reconcile(stored, _record(), fields=["last_sale_date"]) \
        ["verdicts"]["last_sale_date"] == MATCH


def test_bool_comparison_normalizes_representations():
    result = reconcile.reconcile({"owner_occupied": "true"}, _record(),
                                 fields=["owner_occupied"])
    assert result["verdicts"]["owner_occupied"] == MATCH


# ── Numeric tolerance ─────────────────────────────────────────────────────────

def test_small_value_difference_is_rounding_not_a_discrepancy():
    # 5% default tolerance — $341k vs $340k is the same house.
    result = reconcile.reconcile({"estimated_value": 341_000}, _record(),
                                 fields=["estimated_value"])
    assert result["verdicts"]["estimated_value"] == MATCH


def test_large_value_difference_is_a_real_discrepancy():
    result = reconcile.reconcile({"estimated_value": 200_000}, _record(),
                                 fields=["estimated_value"])
    assert result["verdicts"]["estimated_value"] == MISMATCH


def test_tolerance_scales_with_magnitude():
    """One fraction has to work for a cheap lot and an expensive house."""
    rule = {"kind": "number", "tol": 0.05}
    assert reconcile._equal(10_000, 10_400, rule)        # 4% of a small number
    assert not reconcile._equal(10_000, 11_000, rule)    # 10% of the same
    assert reconcile._equal(1_000_000, 1_040_000, rule)  # 4% of a large one


def test_counts_have_no_tolerance():
    result = reconcile.reconcile({"garage_spaces": 3}, _record(),
                                 fields=["garage_spaces"])
    assert result["verdicts"]["garage_spaces"] == MISMATCH


def test_unparseable_number_is_never_reported_as_a_difference():
    result = reconcile.reconcile({"square_footage": "n/a"}, _record(),
                                 fields=["square_footage"])
    assert result["verdicts"]["square_footage"] == MATCH


# ── Write policy ──────────────────────────────────────────────────────────────

def test_fill_mode_never_overwrites_even_a_refreshable_field():
    result = reconcile.reconcile({"estimated_value": 200_000}, _record(), mode="fill",
                                 fields=["estimated_value"])
    assert result["updates"] == {}
    assert result["findings"][0]["resolution"] == "kept"


def test_refresh_mode_overwrites_values_that_move():
    result = reconcile.reconcile({"estimated_value": 200_000}, _record(), mode="refresh",
                                 fields=["estimated_value"])
    assert result["updates"] == {"estimated_value": 340_000}
    assert result["findings"][0]["resolution"] == "refreshed"


def test_refresh_mode_still_defers_to_the_county_on_structural_facts():
    """year_built is fill_only — HCAD is the record, an AVM does not overrule it."""
    result = reconcile.reconcile({"year_built": 1975}, _record(), mode="refresh",
                                 fields=["year_built"])
    assert result["updates"] == {}
    assert result["findings"][0]["resolution"] == "kept"


def test_coordinates_are_fill_only_in_every_mode():
    result = reconcile.reconcile({"latitude": 30.1}, _record(), mode="refresh",
                                 fields=["latitude"])
    assert result["updates"] == {}


def test_gap_is_filled_in_both_modes():
    for mode in ("fill", "refresh"):
        result = reconcile.reconcile({"estimated_value": None}, _record(), mode=mode,
                                     fields=["estimated_value"])
        assert result["updates"] == {"estimated_value": 340_000}


def test_unknown_field_is_ignored_rather_than_crashing():
    result = reconcile.reconcile({}, _record(), fields=["lead_score", "year_built"])
    assert "lead_score" not in result["verdicts"]
    assert result["verdicts"]["year_built"] == FILL


def test_bad_mode_is_rejected():
    with pytest.raises(ValueError):
        reconcile.reconcile({}, _record(), mode="overwrite")


# ── Findings and summary ──────────────────────────────────────────────────────

def test_findings_carry_both_sides_as_text():
    result = reconcile.reconcile({"year_built": 1975}, _record(), fields=["year_built"])
    finding = result["findings"][0]
    assert finding == {"field": "year_built", "stored": "1975", "remote": "1998",
                       "verdict": MISMATCH, "resolution": "kept"}


def test_matches_produce_no_findings():
    result = reconcile.reconcile(map_record(_record()), _record())
    assert result["findings"] == []
    assert result["updates"] == {}


def test_verdicts_cover_every_requested_field():
    stored = {"year_built": 1998, "square_footage": None, "garage_spaces": 3}
    result = reconcile.reconcile(
        stored, _record(yearBuilt=1998, squareFootage=None),
        fields=["year_built", "square_footage", "garage_spaces"])
    assert result["verdicts"] == {
        "year_built": MATCH, "square_footage": NO_REMOTE, "garage_spaces": MISMATCH,
    }


def test_derived_fields_are_refreshed_but_never_reported():
    """estimated_equity is an amortization curve and ownership_years counts from
    today, so both drift on their own — reporting them would bury real findings."""
    for field in ("estimated_equity", "ownership_years"):
        assert field not in REPORTED_FIELDS
    result = reconcile.reconcile({"estimated_equity": 1}, _record(), mode="refresh",
                                 fields=["estimated_equity"])
    assert result["updates"]["estimated_equity"] > 1   # still kept consistent


def test_empty_row_against_a_full_record_fills_everything():
    result = reconcile.reconcile({}, _record())
    assert set(result["updates"]) == set(RECONCILED_FIELDS)
    assert all(v == FILL for v in result["verdicts"].values())


# ── verify_record ─────────────────────────────────────────────────────────────
# RentCast resolves the address string itself and limit=1 hides any ambiguity,
# so a lookup can silently answer about a different parcel. verify_record is the
# gate; it returns None to accept, or the address actually answered with.

def test_accepts_the_record_for_the_address_we_asked_about():
    assert reconcile.verify_record(_record(), "123 Main St") is None


def test_accepts_a_differently_formatted_same_address():
    record = _record(addressLine1="123 Main Street")
    assert reconcile.verify_record(record, "123 MAIN ST") is None


def test_rejects_a_neighbouring_parcel():
    """The failure this exists for: a house number away, silently written onto
    our row along with its year built, value and owner."""
    record = _record(addressLine1="125 Main St")
    assert reconcile.verify_record(record, "123 Main St") == "125 Main St"


def test_rejects_a_different_street():
    record = _record(addressLine1="123 Oak St")
    assert reconcile.verify_record(record, "123 Main St") == "123 Oak St"


def test_falls_back_to_the_formatted_address():
    """Some records carry only formattedAddress; its first segment is the
    street line."""
    record = _record(addressLine1=None,
                     formattedAddress="123 Main St, Houston, TX 77396")
    assert reconcile.verify_record(record, "123 Main St") is None
    assert reconcile.record_address(record) == "123 Main St"


def test_a_record_with_no_address_is_unverifiable_not_accepted():
    record = _record(addressLine1=None, formattedAddress=None)
    assert reconcile.verify_record(record, "123 Main St") is not None


def test_record_address_prefers_the_street_line():
    record = _record(addressLine1="123 Main St",
                     formattedAddress="999 Wrong Ave, Houston, TX 77396")
    assert reconcile.record_address(record) == "123 Main St"
