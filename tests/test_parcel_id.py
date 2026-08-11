"""Tests for pipeline/parcel_id.py — the one rule for assessor parcel numbers."""
from pipeline.parcel_id import normalize_apn, same_parcel


# ── normalize_apn (storage form) ──────────────────────────────────────────────

def test_normalize_strips_punctuation_and_uppercases():
    assert normalize_apn("066-064-013-0020") == "0660640130020"
    assert normalize_apn(" 05076 103 0500 ") == "050761030500"
    assert normalize_apn("12ab34c") == "12AB34C"


def test_normalize_keeps_leading_zeros():
    # HCAD accounts are conventionally 13-digit zero-padded; operators recognize
    # them that way, so the stored form keeps the padding.
    assert normalize_apn("0660640130020") == "0660640130020"


def test_normalize_rejects_junk():
    assert normalize_apn(None) is None
    assert normalize_apn("") is None
    assert normalize_apn("---") is None


def test_normalize_rejects_all_zero_placeholders():
    """Two different properties both carrying a zero-filled APN must never be
    treated as the same parcel."""
    assert normalize_apn("0000000000000") is None
    assert normalize_apn("000-000-0000") is None


def test_normalize_accepts_non_string_input():
    assert normalize_apn(660640130020) == "660640130020"


# ── same_parcel (comparison) ──────────────────────────────────────────────────

def test_same_parcel_ignores_padding_dashes_and_case():
    assert same_parcel("0660640130020", "66-064-013-0020")
    assert same_parcel("05076-103-0500", "050761030500")
    assert same_parcel("12ab34", "12AB34")


def test_different_parcels_do_not_match():
    assert not same_parcel("0660640130020", "0660640130021")


def test_missing_or_junk_is_never_a_match():
    # Mirrors same_address's empty-input rule: absence of an identifier is not
    # evidence of a match.
    assert not same_parcel(None, "0660640130020")
    assert not same_parcel("0660640130020", "")
    assert not same_parcel(None, None)
    assert not same_parcel("0000000000000", "0000000000000")
