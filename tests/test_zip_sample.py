"""Tests for the public ZIP-sample teaser helpers (api/zip_sample_logic.py):
masking must never leak a full house number, and value labels stay deliberately
imprecise."""
import re

from api.zip_sample_logic import mask_address, value_label


def test_mask_keeps_street_hides_house_number():
    assert mask_address("1842 Westheimer Rd") == "18XX Westheimer Rd"
    assert mask_address("504 River Oaks Blvd") == "5XX River Oaks Blvd"
    assert mask_address("77 Tanglewood Ln") == "7X Tanglewood Ln"


def test_mask_always_hides_at_least_one_digit():
    # Whatever the house-number length, the exact parcel must not be recoverable.
    for n in ("7", "42", "319", "12345", "180765"):
        masked = mask_address(f"{n} Main St")
        leading = masked.split()[0]
        assert "X" in leading, masked
        assert leading != n


def test_mask_handles_odd_shapes():
    assert mask_address("") == ""
    assert mask_address(None) == ""
    # No leading house number: every digit run is masked instead.
    assert mask_address("Corner of Elm & 5th") == "Corner of Elm & Xth"
    # Digit-free descriptions pass through (nothing identifying to hide).
    assert mask_address("Oak Meadow Estate") == "Oak Meadow Estate"


def test_value_label_rounds_and_degrades():
    assert value_label(483_250) == "~$485K"
    assert value_label(1_240_000) == "~$1.2M"
    assert value_label(2_000_000) == "~$2M"
    assert value_label(None) == ""
    assert value_label("not-a-number") == ""
    assert value_label(0) == ""
    # Never emits enough precision to identify the parcel's exact county value.
    assert not re.search(r"\d{6}", value_label(487_631))
