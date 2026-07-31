"""
Tests for pipeline/geocode_batch.py — Census batch geocoder payload + parsing.

Pure CSV in / CSV out; no HTTP, no database.
"""
import pytest

from pipeline.geocode_batch import (
    MAX_BATCH,
    build_payload,
    chunk,
    parse_response,
    _clean,
    _parse_coords,
)


# ── build_payload ─────────────────────────────────────────────────────────────

def test_payload_has_five_columns_per_record():
    out = build_payload([
        {"id": "1", "address": "123 Main St", "city": "Katy", "state": "TX", "zip": "77449"},
    ])
    assert out == "1,123 Main St,Katy,TX,77449\n"


def test_payload_writes_one_line_per_record():
    out = build_payload([
        {"id": "1", "address": "1 A St", "city": "Katy", "state": "TX", "zip": "77449"},
        {"id": "2", "address": "2 B St", "city": "Katy", "state": "TX", "zip": "77449"},
    ])
    assert out.count("\n") == 2


def test_payload_quotes_addresses_containing_commas():
    """A comma in the street must not shift the column layout."""
    out = build_payload([
        {"id": "7", "address": "123 MAIN ST, APT 4", "city": "Katy", "state": "TX", "zip": "77449"},
    ])
    assert out == '7,"123 MAIN ST, APT 4",Katy,TX,77449\n'
    # And it round-trips back to five fields.
    import csv, io
    assert len(next(csv.reader(io.StringIO(out)))) == 5


def test_payload_keeps_blank_fields_as_empty_columns():
    """HCAD rows often have no city; all five columns must still be present."""
    out = build_payload([{"id": "3", "address": "9 C St", "city": None, "state": "TX", "zip": "77449"}])
    assert out == "3,9 C St,,TX,77449\n"


def test_payload_strips_newlines_that_would_corrupt_row_alignment():
    out = build_payload([
        {"id": "4", "address": "10 D St\nSuite 2", "city": "Katy", "state": "TX", "zip": "77449"},
    ])
    assert out.count("\n") == 1
    assert "10 D St Suite 2" in out


def test_payload_collapses_whitespace():
    out = build_payload([
        {"id": "5", "address": "  11   E   St  ", "city": "Katy", "state": "TX", "zip": "77449"},
    ])
    assert out == "5,11 E St,Katy,TX,77449\n"


def test_empty_records_produce_empty_payload():
    assert build_payload([]) == ""


# ── parse_response ────────────────────────────────────────────────────────────

MATCH_ROW = (
    '"1","123 MAIN ST, KATY, TX, 77449","Match","Exact",'
    '"123 MAIN ST, KATY, TX, 77449","-95.8,29.78","123456","L"'
)
NO_MATCH_ROW = '"2","999 NOWHERE ST, KATY, TX, 77449","No_Match"'
TIE_ROW = '"3","5 TIE ST, KATY, TX, 77449","Tie"'


def test_parses_a_match_row_into_lat_lng_confidence():
    out = parse_response(MATCH_ROW)
    assert out == {"1": (29.78, -95.8, 0.9)}


def test_coordinates_are_swapped_from_census_lon_lat_order():
    """Census emits "lon,lat"; everything else in this codebase is (lat, lng)."""
    lat, lng, _ = parse_response(MATCH_ROW)["1"]
    assert lat == 29.78 and lng == -95.8
    assert -90 <= lat <= 90          # a latitude, not a Texas longitude
    assert lng < 0                   # western hemisphere


def test_non_exact_match_gets_lower_confidence():
    row = ('"9","X","Match","Non_Exact","X","-95.8,29.78","1","L"')
    assert parse_response(row)["9"][2] == 0.6


def test_no_match_and_tie_rows_are_dropped():
    out = parse_response("\n".join([MATCH_ROW, NO_MATCH_ROW, TIE_ROW]))
    assert set(out) == {"1"}


def test_short_or_malformed_rows_are_skipped_not_raised():
    """One bad line must not lose the rest of a 10,000-record batch."""
    out = parse_response("\n".join([NO_MATCH_ROW, "garbage", MATCH_ROW, '"x","y"']))
    assert set(out) == {"1"}


def test_unparseable_coordinates_are_skipped():
    row = '"1","X","Match","Exact","X","not-a-coord","1","L"'
    assert parse_response(row) == {}


def test_empty_response_returns_empty_mapping():
    assert parse_response("") == {}
    assert parse_response(None) == {}


def test_response_order_need_not_match_request_order():
    """Census does not guarantee ordering — ids are what tie results back."""
    second = '"2","B","Match","Exact","B","-95.7,29.70","2","L"'
    out = parse_response("\n".join([second, MATCH_ROW]))
    assert set(out) == {"1", "2"}
    assert out["2"] == (29.70, -95.7, 0.9)


def test_ids_are_stripped_of_surrounding_whitespace():
    row = ' 42 ,"X","Match","Exact","X","-95.8,29.78","1","L"'
    assert "42" in parse_response(row)


# ── chunk ─────────────────────────────────────────────────────────────────────

def test_chunk_splits_at_the_batch_ceiling():
    records = list(range(25_000))
    batches = chunk(records)
    assert [len(b) for b in batches] == [MAX_BATCH, MAX_BATCH, 5_000]


def test_chunk_of_a_zip_sized_workload():
    """ZIP 77449 is 41,334 parcels — 5 requests instead of 41,334."""
    assert len(chunk(list(range(41_334)))) == 5


def test_chunk_handles_empty_and_undersized_inputs():
    assert chunk([]) == []
    assert chunk([1, 2, 3]) == [[1, 2, 3]]


def test_chunk_rejects_a_non_positive_size():
    with pytest.raises(ValueError):
        chunk([1, 2, 3], size=0)


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("-95.8,29.78", (-95.8, 29.78)),
    ("  -95.8 , 29.78 ", (-95.8, 29.78)),
])
def test_parse_coords_accepts_valid_pairs(raw, expected):
    assert _parse_coords(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "1", "1,2,3", "a,b"])
def test_parse_coords_rejects_invalid(raw):
    assert _parse_coords(raw) is None


def test_clean_handles_none_and_numbers():
    assert _clean(None) == ""
    assert _clean(77449) == "77449"
