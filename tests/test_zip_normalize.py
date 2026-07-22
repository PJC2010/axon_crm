"""
Tests for pipeline.addr.normalize_zip — the canonical-5-digit ZIP reducer that
keeps HCAD ZIP+4 site ZIPs from hiding a covered Harris County ZIP.

Pure/offline: no DB or network.
"""
from pipeline.addr import normalize_zip


def test_clean_five_digit_passes_through():
    assert normalize_zip("77008") == "77008"


def test_zip_plus_four_hyphenated_collapses_to_five():
    assert normalize_zip("77008-2317") == "77008"


def test_zip_plus_four_unhyphenated_collapses_to_five():
    assert normalize_zip("770082317") == "77008"


def test_surrounding_whitespace_is_ignored():
    assert normalize_zip("  77008 ") == "77008"


def test_non_digit_noise_is_stripped():
    assert normalize_zip("77008 TX") == "77008"


def test_empty_and_none_yield_empty_string():
    assert normalize_zip("") == ""
    assert normalize_zip(None) == ""
    assert normalize_zip("   ") == ""


def test_numeric_input_accepted():
    # DuckDB/CSV can hand back an int for an all-digit ZIP.
    assert normalize_zip(77008) == "77008"
