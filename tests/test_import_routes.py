"""Tests for the file-handling and dedup half of api/routes/imports.py.

The parsing tests are pure. The upsert tests drive `_upsert_row` with a fake
cursor (same style as tests/test_dialer_routes.py) and assert on the SQL it
issues, so the dedup decisions are pinned without needing a database.
"""
import pytest
from fastapi import HTTPException

from api.routes.imports import _decode, _read_csv, _sniff_delimiter, _upsert_row


def _csv(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


# ── Decoding ─────────────────────────────────────────────────────────────────────

def test_decode_utf8_and_bom():
    assert _decode(b"name,city\nJane,Houston\n").startswith("name")
    assert _decode(b"\xef\xbb\xbfname,city\n") == "name,city\n"


def test_decode_keeps_accents_from_a_windows_export():
    # Excel on Windows writes cp1252. Decoding it as UTF-8 with errors="replace"
    # stored "Jos�" — and the mojibake, not the name, is what persisted.
    text = _decode(_csv("name\nJosé Núñez\n", "cp1252"))
    assert "José Núñez" in text
    assert "�" not in text


def test_decode_handles_utf16():
    assert "Houston" in _decode(_csv("name,city\nJane,Houston\n", "utf-16"))


# ── Delimiters ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("header, expected", [
    ("name,phone,email", ","),
    ("name;phone;email", ";"),
    ("name\tphone\temail", "\t"),
    ("name|phone|email", "|"),
    ("email", ","),                       # single column: fall back to comma
])
def test_sniff_delimiter(header, expected):
    assert _sniff_delimiter(header + "\nA,B,C\n") == expected


def test_semicolon_file_parses_into_real_columns():
    headers, rows = _read_csv(_csv("name;phone;email\nJane;555;j@x.com\n"))
    assert headers == ["name", "phone", "email"]
    assert rows[0]["email"] == "j@x.com"


def test_quoted_delimiter_inside_a_field_survives():
    headers, rows = _read_csv(_csv('name;address\n"Jane";"123 Main St, Apt 4"\n'))
    assert rows[0]["address"] == "123 Main St, Apt 4"


@pytest.mark.parametrize("payload", [
    "name,city\r\nJane,Houston\r\n",       # Windows
    "name,city\rJane,Houston\r",           # classic Mac
    "name,city\nJane,Houston\n",           # Unix
])
def test_line_endings(payload):
    headers, rows = _read_csv(_csv(payload))
    assert headers == ["name", "city"]
    assert rows[0]["city"] == "Houston"


# ── Files that aren't CSVs ───────────────────────────────────────────────────────

@pytest.mark.parametrize("content, hint", [
    (b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x01\x02\x03" * 40, "workbook"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x01\x02" * 40, "workbook"),
    (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj", "PDF"),
])
def test_binary_uploads_are_rejected_with_a_400(content, hint):
    # These used to escape as a 500 (csv.Error) or parse into a screenful of
    # garbage columns, either of which reads as "the importer is broken".
    with pytest.raises(HTTPException) as exc:
        _read_csv(content)
    assert exc.value.status_code == 400
    assert hint in exc.value.detail


def test_a_stray_nul_does_not_reject_the_whole_file():
    # The binary check is a NUL *density* test on purpose — one stray control
    # byte in a real export must not cost the user their import.
    headers, rows = _read_csv(b"name,phone\nJa\x00ne,555\n")
    assert headers == ["name", "phone"]
    assert len(rows) == 1


def test_oversized_field_is_a_400_not_a_500():
    with pytest.raises(HTTPException) as exc:
        _read_csv(_csv("name,notes\nJane," + "x" * 200_000 + "\n"))
    assert exc.value.status_code == 400


def test_row_cap_is_enforced(monkeypatch):
    monkeypatch.setattr("api.routes.imports.IMPORT_MAX_ROWS", 10)
    with pytest.raises(HTTPException) as exc:
        _read_csv(_csv("name\n" + "".join(f"P{i}\n" for i in range(50))))
    assert exc.value.status_code == 400
    assert "rows" in exc.value.detail


# ── Dedup ────────────────────────────────────────────────────────────────────────

class FakeCursor:
    """Records every statement; returns whatever the test queued for the lookup."""

    def __init__(self, existing=None, new_id=42):
        self.existing = existing        # (id, zip) tuple or None
        self.new_id = new_id
        self.statements: list[tuple[str, list]] = []
        self._next = None

    def __init_phone__(self, phone_match):
        self.phone_match = phone_match
        return self

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.statements.append((sql, list(params) if params is not None else None))
        if sql.startswith("SELECT id FROM properties WHERE account_id = %s AND address IS NULL"):
            self._next = getattr(self, "phone_match", None)
        elif sql.startswith("SELECT id, zip FROM properties"):
            self._next = self.existing
        elif "RETURNING id, (xmax = 0)" in sql:
            self._next = (self.new_id, True)
        elif "RETURNING id" in sql:
            self._next = (self.new_id,)
        else:
            self._next = None

    def fetchone(self):
        return self._next

    @property
    def sql(self) -> list[str]:
        return [s for s, _ in self.statements]


BASE = {"enrichment_flags": {"source": "csv_import"}, "lead_source": "csv_import"}


def test_address_row_looks_up_through_the_normalizer():
    cur = FakeCursor(existing=None)
    _upsert_row(cur, 7, {**BASE, "address": "12 Ash St", "zip": "77002"})
    lookup = cur.sql[0]
    assert "axon_normalize_address(address) = axon_normalize_address(%s)" in lookup
    assert "account_id = %s" in lookup            # never match another tenant
    assert cur.statements[0][1][0] == 7


def test_existing_address_row_is_updated_not_duplicated():
    cur = FakeCursor(existing=(5, "77002"))
    inserted, lead_id = _upsert_row(cur, 7, {**BASE, "address": "12 ASH ST.", "zip": "77002",
                                             "contact_name": "Jane"})
    assert (inserted, lead_id) == (False, 5)
    update = [s for s in cur.sql if s.startswith("UPDATE properties")]
    assert len(update) == 1
    assert "contact_name = %s" in update[0]
    # The address we matched on is never rewritten, and the update is scoped.
    assert "address = %s" not in update[0]
    assert "WHERE id = %s AND account_id = %s" in update[0]
    assert cur.statements[-1][1][-2:] == [5, 7]


def test_zip_is_filled_in_when_the_existing_row_has_none():
    cur = FakeCursor(existing=(5, None))
    _upsert_row(cur, 7, {**BASE, "address": "12 Ash St", "zip": "77002"})
    update = [s for s in cur.sql if s.startswith("UPDATE properties")][0]
    assert "zip = %s" in update


def test_zip_is_not_overwritten_when_the_existing_row_has_one():
    cur = FakeCursor(existing=(5, "77002"))
    _upsert_row(cur, 7, {**BASE, "address": "12 Ash St", "zip": "77002"})
    update = [s for s in cur.sql if s.startswith("UPDATE properties")][0]
    assert "zip = %s" not in update


def test_address_without_a_zip_still_dedups():
    # ON CONFLICT (account_id, address, zip) can never match a NULL zip, so
    # before the lookup every re-import inserted these rows again.
    cur = FakeCursor(existing=(5, None))
    inserted, lead_id = _upsert_row(cur, 7, {**BASE, "address": "900 Oak Ave"})
    assert (inserted, lead_id) == (False, 5)
    assert cur.statements[0][1] == [7, "900 Oak Ave", None, None]


def test_new_address_row_inserts_with_the_unique_key_as_a_race_guard():
    cur = FakeCursor(existing=None)
    inserted, lead_id = _upsert_row(cur, 7, {**BASE, "address": "1 New St", "zip": "77002"})
    assert (inserted, lead_id) == (True, 42)
    insert = [s for s in cur.sql if s.startswith("INSERT INTO properties")][0]
    assert "ON CONFLICT (account_id, address, zip)" in insert
    assert "enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags" in insert


def test_email_only_row_uses_the_partial_index():
    cur = FakeCursor()
    _upsert_row(cur, 7, {**BASE, "contact_email": "a@b.com", "contact_name": "A"})
    insert = [s for s in cur.sql if s.startswith("INSERT INTO properties")][0]
    assert "ON CONFLICT (account_id, lower(contact_email))" in insert
    assert "WHERE address IS NULL AND contact_email IS NOT NULL" in insert
    # No address means no address lookup.
    assert not any(s.startswith("SELECT id, zip") for s in cur.sql)


def test_name_only_row_is_a_plain_insert():
    # A bare name is not an identity — two "John Smith"s are two people — so
    # this row genuinely has nothing to dedup on.
    cur = FakeCursor()
    inserted, lead_id = _upsert_row(cur, 7, {**BASE, "contact_name": "Frank"})
    assert (inserted, lead_id) == (True, 42)
    assert "ON CONFLICT" not in cur.sql[0]
    assert not any("address IS NULL" in s for s in cur.sql)


def test_phone_only_row_dedups_on_phone_and_name():
    cur = FakeCursor().__init_phone__((5,))
    inserted, lead_id = _upsert_row(
        cur, 7, {**BASE, "contact_phone": "+1 (713) 555-0142", "contact_name": " Jane Doe "})
    assert (inserted, lead_id) == (False, 5)
    lookup, params = cur.statements[0]
    assert "address IS NULL" in lookup
    # Last 10 digits, matching api/routes/twilio_inbound.py::normalize_phone.
    assert params == [7, "7135550142", "jane doe"]


def test_phone_only_row_inserts_when_nothing_matches():
    cur = FakeCursor().__init_phone__(None)
    inserted, lead_id = _upsert_row(cur, 7, {**BASE, "contact_phone": "713-555-0142"})
    assert (inserted, lead_id) == (True, 42)
    assert cur.sql[-1].startswith("INSERT INTO properties")


def test_unusably_short_phone_skips_the_lookup():
    # An empty key would otherwise match every row with a blank phone.
    cur = FakeCursor().__init_phone__((5,))
    inserted, _ = _upsert_row(cur, 7, {**BASE, "contact_phone": "555", "contact_name": "A"})
    assert inserted is True
    assert not any("address IS NULL" in s for s in cur.sql)


def test_email_row_prefers_the_email_key_over_the_phone_one():
    cur = FakeCursor().__init_phone__((5,))
    _upsert_row(cur, 7, {**BASE, "contact_email": "a@b.com", "contact_phone": "713-555-0142"})
    assert not any("address IS NULL AND" in s for s in cur.sql if s.startswith("SELECT"))
    assert "ON CONFLICT (account_id, lower(contact_email))" in cur.sql[-1]


def test_only_writable_columns_reach_the_sql():
    # A caller-supplied mapping is normalized against TARGET_FIELDS before it
    # gets here; this pins that _upsert_row itself never interpolates a column
    # name that isn't on the allowlist.
    cur = FakeCursor()
    _upsert_row(cur, 7, {**BASE, "contact_name": "Frank", "lead_score": 99, "id": 1})
    sql, params = cur.statements[0]
    assert "lead_score" not in sql and " id," not in sql
    # account_id, contact_name, enrichment_flags, lead_source — and nothing else.
    assert len(params) == 4
    assert params[0] == 7 and params[1] == "Frank"
