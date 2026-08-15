"""Unit tests for the contact/lead import logic (pure, no DB)."""
import pytest

from api.import_logic import (
    clean_value, detect_mapping, normalize_row, normalize_status, normalize_zip,
    parse_amount, row_is_usable,
)


# ── detect_mapping ──────────────────────────────────────────────────────────────

def test_detect_generic_headers():
    headers = ["Name", "Phone", "Email", "Address", "City", "State", "Zip"]
    m = detect_mapping(headers)
    assert m["Name"] == "contact_name"
    assert m["Phone"] == "contact_phone"
    assert m["Email"] == "contact_email"
    assert m["Address"] == "address"
    assert m["City"] == "city"
    assert m["State"] == "state"
    assert m["Zip"] == "zip"


def test_detect_google_contacts_headers():
    headers = [
        "First Name", "Last Name", "E-mail 1 - Value", "Phone 1 - Value",
        "Address 1 - Street", "Address 1 - City", "Address 1 - Region",
        "Address 1 - Postal Code", "Group Membership",
    ]
    m = detect_mapping(headers)
    assert m["E-mail 1 - Value"] == "contact_email"
    assert m["Phone 1 - Value"] == "contact_phone"
    assert m["Address 1 - Street"] == "address"
    assert m["Address 1 - City"] == "city"
    assert m["Address 1 - Region"] == "state"
    assert m["Address 1 - Postal Code"] == "zip"
    # Unknown columns are left unmapped.
    assert "Group Membership" not in m


def test_detect_is_punctuation_and_case_insensitive():
    m = detect_mapping(["ZIP CODE", "Phone Number", "e-mail address"])
    assert m["ZIP CODE"] == "zip"
    assert m["Phone Number"] == "contact_phone"
    assert m["e-mail address"] == "contact_email"


# ── normalize_row ────────────────────────────────────────────────────────────────

def test_normalize_combines_first_and_last_name():
    headers = ["First Name", "Last Name", "E-mail 1 - Value"]
    mapping = detect_mapping(headers)
    row = normalize_row(
        {"First Name": "Jane", "Last Name": "Doe", "E-mail 1 - Value": "JANE@EXAMPLE.COM"},
        mapping,
    )
    assert row["contact_name"] == "Jane Doe"
    assert row["contact_email"] == "jane@example.com"  # lowercased
    assert "address" not in row


def test_normalize_full_name_takes_precedence_over_parts():
    mapping = detect_mapping(["Name", "First Name", "Last Name"])
    row = normalize_row({"Name": "Acme Corp", "First Name": "A", "Last Name": "B"}, mapping)
    assert row["contact_name"] == "Acme Corp"


def test_normalize_drops_empty_values():
    mapping = detect_mapping(["Name", "Phone", "Email"])
    row = normalize_row({"Name": "Jane", "Phone": "  ", "Email": ""}, mapping)
    assert row == {"contact_name": "Jane"}


def test_normalize_parses_estimated_value():
    mapping = detect_mapping(["Name", "Estimated Value"])
    row = normalize_row({"Name": "Jane", "Estimated Value": "$15,000"}, mapping)
    assert row["estimated_value"] == 15000


def test_normalize_drops_unparseable_value():
    mapping = detect_mapping(["Name", "Value"])
    row = normalize_row({"Name": "Jane", "Value": "n/a"}, mapping)
    assert "estimated_value" not in row


def test_normalize_falls_back_to_formatted_address():
    mapping = detect_mapping(["Name", "Address 1 - Formatted"])
    row = normalize_row(
        {"Name": "Jane", "Address 1 - Formatted": "123 Main St, Houston, TX 77002"},
        mapping,
    )
    assert row["address"] == "123 Main St, Houston, TX 77002"


# ── row_is_usable ────────────────────────────────────────────────────────────────

def test_row_is_usable():
    assert row_is_usable({"address": "123 Main St"})
    assert row_is_usable({"contact_email": "a@b.com"})
    assert row_is_usable({"contact_phone": "555"})
    assert row_is_usable({"contact_name": "Jane"})
    assert not row_is_usable({})
    assert not row_is_usable({"city": "Houston", "state": "TX"})


# ── parse_amount ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("$15,000", 15000),
    ("15000", 15000),
    ("15,000.00", 15000),
    # The regression this replaced: dropping every non-digit read this as
    # 150050 — a 100x overstatement that then fed scoring.
    ("1,500.50", 1500),
    ("1500.50", 1500),
    ("1500,50", 1500),          # comma as the decimal separator
    ("1.500.000", 1500000),     # European thousands grouping
    ("1.234,56", 1235),         # European decimal, rounded to whole units
    ("$ 2,750 ", 2750),
    ("15k", 15000),
    ("1.2M", 1200000),
    ("USD 900", 900),
    ("0", 0),
])
def test_parse_amount_parses_real_spreadsheet_shapes(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "  ", "n/a", "TBD", "call for price", "-", "$", "12-34-56",
    "-200", "(200)",            # negatives are bad data for a property value
])
def test_parse_amount_rejects_junk(raw):
    assert parse_amount(raw) is None


# ── normalize_status ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("new", "new"),
    ("Won ", "won"),
    ("Quote Sent", "quote_sent"),
    ("quote-sent", "quote_sent"),
    ("NOT INTERESTED", "not_interested"),
    ("", ""),
    ("   ", ""),
    ("!!!", ""),
])
def test_normalize_status(raw, expected):
    assert normalize_status(raw) == expected


def test_normalize_row_folds_status_and_drops_empty_ones():
    mapping = detect_mapping(["Name", "Status"])
    assert normalize_row({"Name": "J", "Status": "Quote Sent"}, mapping)["status"] == "quote_sent"
    # A status of pure punctuation normalizes to nothing and must not be stored
    # as an empty string — the route fills in the import default instead.
    assert "status" not in normalize_row({"Name": "J", "Status": "--"}, mapping)


# ── normalize_zip ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("77002", "77002"),
    ("77002-1234", "77002"),    # ZIP+4 would fork the (address, zip) key
    ("77002 1234", "77002"),
    ("770021234", "77002"),
    (" 77002 ", "77002"),
    ("01234", "01234"),         # leading zero preserved
    ("K1A 0B1", "K1A 0B1"),     # non-US: left alone
    ("", ""),
])
def test_normalize_zip(raw, expected):
    assert normalize_zip(raw) == expected


# ── control characters ───────────────────────────────────────────────────────────

def test_clean_value_strips_control_chars_but_keeps_text():
    # Postgres text columns cannot hold a NUL at all, so a single stray byte
    # would fail the whole row rather than the one cell.
    assert clean_value("Ja\x00ne") == "Jane"
    assert clean_value("  spaced\x07  ") == "spaced"
    assert clean_value("José Núñez") == "José Núñez"


def test_normalize_row_strips_control_chars():
    mapping = detect_mapping(["Name", "Email"])
    row = normalize_row({"Name": "Ja\x00ne", "Email": "A\x00@B.com"}, mapping)
    assert row == {"contact_name": "Jane", "contact_email": "a@b.com"}
