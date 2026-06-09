"""Unit tests for the contact/lead import logic (pure, no DB)."""
from api.import_logic import detect_mapping, normalize_row, row_is_usable


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
