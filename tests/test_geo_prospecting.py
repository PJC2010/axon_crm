"""
Tests for pipeline/prospecting.py — the DB-free / network-free pieces of the
cluster-seeded prospecting flow: client-side refinement, record mapping, and
dedupe matching. The orchestration (resolve_seed, cost control, ingest, score)
is thin SQL over these and the provider.
"""
import pytest

from pipeline.prospecting import (
    _parse_range,
    _in_range,
    refine,
    map_record,
    is_duplicate,
    dedupe,
)


def _rec(**over):
    """A RentCast-shaped record with sensible defaults."""
    base = {
        "addressLine1": "123 Oak St",
        "city": "Houston",
        "state": "TX",
        "zipCode": "77002",
        "latitude": 29.76,
        "longitude": -95.37,
        "propertyType": "Single Family",
        "yearBuilt": 2005,
        "lotSize": 9000,
        "ownerOccupied": True,
        "price": 350000,
        "lastSalePrice": 300000,
        "lastSaleDate": "2018-05-01",
        "subdivision": "Oakwood",
        "features": {"garageSpaces": 2, "pool": False},
        "owner": {"names": ["JANE DOE"]},
    }
    base.update(over)
    if "features" in over:
        base["features"] = {**{"garageSpaces": 2, "pool": False}, **over["features"]}
    return base


# ── range parsing ─────────────────────────────────────────────────────────────

class TestRange:
    def test_parse_both_sides(self):
        assert _parse_range("7000:15000") == (7000.0, 15000.0)

    def test_parse_open_upper(self):
        assert _parse_range("7000:") == (7000.0, None)

    def test_parse_open_lower(self):
        assert _parse_range(":15000") == (None, 15000.0)

    def test_parse_list_form(self):
        assert _parse_range([7000, 15000]) == (7000.0, 15000.0)

    def test_none(self):
        assert _parse_range(None) == (None, None)

    def test_in_range_inclusive(self):
        assert _in_range(7000, "7000:15000") is True
        assert _in_range(15000, "7000:15000") is True

    def test_in_range_outside(self):
        assert _in_range(6999, "7000:15000") is False
        assert _in_range(15001, "7000:15000") is False

    def test_in_range_none_value(self):
        assert _in_range(None, "7000:15000") is False


# ── refine ────────────────────────────────────────────────────────────────────

class TestRefine:
    def test_no_preset_keeps_all(self):
        recs = [_rec(), _rec(propertyType="Condo")]
        assert refine(recs, None) == recs
        assert refine(recs, {}) == recs

    def test_property_type_filter(self):
        recs = [_rec(), _rec(propertyType="Condo")]
        out = refine(recs, {"propertyType": "Single Family"})
        assert len(out) == 1 and out[0]["propertyType"] == "Single Family"

    def test_lot_size_range(self):
        recs = [_rec(lotSize=8000), _rec(lotSize=20000), _rec(lotSize=5000)]
        out = refine(recs, {"lotSize": "7000:15000"})
        assert [r["lotSize"] for r in out] == [8000]

    def test_year_built_range(self):
        recs = [_rec(yearBuilt=1995), _rec(yearBuilt=2010)]
        out = refine(recs, {"yearBuilt": "2000:"})
        assert [r["yearBuilt"] for r in out] == [2010]

    def test_absentee_targeting(self):
        recs = [_rec(ownerOccupied=True), _rec(ownerOccupied=False)]
        out = refine(recs, {"ownerOccupied": False})
        assert len(out) == 1 and out[0]["ownerOccupied"] is False

    def test_pool_filter(self):
        recs = [_rec(features={"pool": True}), _rec(features={"pool": False})]
        out = refine(recs, {"pool": True})
        assert len(out) == 1 and out[0]["features"]["pool"] is True

    def test_hoa_presence(self):
        recs = [_rec(hoa={"fee": 250}), _rec()]  # second has no hoa
        out = refine(recs, {"hoa": True})
        assert len(out) == 1 and out[0]["hoa"]["fee"] == 250

    def test_combined_preset(self):
        recs = [
            _rec(propertyType="Single Family", lotSize=9000, ownerOccupied=False),  # keep
            _rec(propertyType="Single Family", lotSize=9000, ownerOccupied=True),   # drop (occupied)
            _rec(propertyType="Condo", lotSize=9000, ownerOccupied=False),          # drop (type)
        ]
        out = refine(recs, {"propertyType": "Single Family", "lotSize": "7000:15000", "ownerOccupied": False})
        assert len(out) == 1


# ── map_record ────────────────────────────────────────────────────────────────

class TestMapRecord:
    def test_core_field_mapping(self):
        row = map_record(_rec(), vertical="lawn_care")
        assert row["address"] == "123 Oak St"
        assert row["zip"] == "77002"
        assert row["latitude"] == 29.76 and row["longitude"] == -95.37
        assert row["geocode_source"] == "rentcast"
        assert row["owner_name"] == "JANE DOE"
        assert row["subdivision"] == "Oakwood"
        assert row["vertical"] == "lawn_care"
        assert row["lead_source"] == "prospecting"
        assert row["garage_spaces"] == 2

    def test_equity_is_populated_proxy(self):
        row = map_record(_rec(), vertical=None)
        # estimate_equity derives a proxy from value/sale price/date.
        assert "estimated_equity" in row

    def test_missing_coords_no_geocode_source(self):
        # No coordinates → no provenance claimed. The delegated mapping omits
        # the key rather than emitting an explicit None; upsert treats both
        # identically (None values are never written).
        row = map_record(_rec(latitude=None, longitude=None), vertical=None)
        assert row.get("geocode_source") is None

    def test_formatted_address_fallback(self):
        r = _rec()
        del r["addressLine1"]
        r["formattedAddress"] = "999 Elm St, Houston, TX"
        row = map_record(r, vertical=None)
        assert row["address"] == "999 Elm St, Houston, TX"

    def test_flat_owner_name_fallback(self):
        r = _rec(owner={})
        r["ownerName"] = "BOB SMITH"
        assert map_record(r, vertical=None)["owner_name"] == "BOB SMITH"


# ── dedupe ────────────────────────────────────────────────────────────────────

class TestDedupe:
    def test_address_match_is_duplicate(self):
        row = map_record(_rec(), vertical=None)
        assert is_duplicate(row, {"123 oak st"}, []) is True

    def test_geometry_within_threshold_is_duplicate(self):
        row = map_record(_rec(addressLine1="Somewhere Else"), vertical=None)
        # ~10 m from an existing property → duplicate under the 25 m default.
        assert is_duplicate(row, set(), [(29.76009, -95.37)]) is True

    def test_far_and_new_address_is_not_duplicate(self):
        row = map_record(_rec(addressLine1="New Place", latitude=30.0, longitude=-96.0), vertical=None)
        assert is_duplicate(row, {"123 oak st"}, [(29.76, -95.37)]) is False

    def test_dedupe_collapses_within_pull(self):
        rows = [
            map_record(_rec(addressLine1="1 A St", latitude=29.70, longitude=-95.40), vertical=None),
            map_record(_rec(addressLine1="1 A St", latitude=29.70, longitude=-95.40), vertical=None),  # dup addr
            map_record(_rec(addressLine1="2 B St", latitude=29.80, longitude=-95.50), vertical=None),
        ]
        kept = dedupe(rows, set(), [])
        addrs = sorted(r["address"] for r in kept)
        assert addrs == ["1 A St", "2 B St"]

    def test_dedupe_against_existing(self):
        rows = [map_record(_rec(addressLine1="123 Oak St"), vertical=None)]
        assert dedupe(rows, {"123 oak st"}, []) == []
