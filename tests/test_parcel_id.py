"""Tests for pipeline/parcel_id.py — the one rule for assessor parcel numbers."""
import duckdb
import pytest

from pipeline.parcel_id import normalize_apn, same_parcel, sql_normalize_apn


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


# ── sql_normalize_apn (the SQL twin) ──────────────────────────────────────────

# Chosen to break a naive rule: punctuation, inner/outer spaces, mixed case,
# alphanumeric accounts, all-zero placeholders in several stylings, a zero
# bracketed by digits (must NOT be treated as all-zero), over-long values.
# ASCII on purpose — real APNs are, and Python's isalnum() is Unicode-aware
# where the SQL character class is not.
APNS = [
    "0660640130020",
    "066-064-013-0020",
    " 05076 103 0500 ",
    "12ab34c",
    "R123456",
    "0",
    "000-000-0000",
    "0000000000000",
    "",
    "   ",
    "#-",
    "0A0",
    "0660640130020extra",
]


def test_sql_expression_matches_python_exactly():
    """The expression writes BOTH parcels.parcel_apn and
    hcad_parcel_centroids.acct, and fill_coords_from_centroids joins the two on
    plain equality — so a byte divergence between the SQL and Python rules
    makes coordinates silently stop matching. Same harness as tests/test_addr.py:
    run the generated SQL in a real DuckDB, compare key-for-key."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t (acct VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [(a,) for a in APNS])
    rows = con.execute(
        f"SELECT acct, {sql_normalize_apn('acct')} FROM t"
    ).fetchall()
    assert len(rows) == len(APNS)
    for raw, sql_norm in rows:
        assert sql_norm == normalize_apn(raw), (
            f"SQL and Python disagree on {raw!r}: "
            f"{sql_norm!r} != {normalize_apn(raw)!r}")


def test_sql_expression_null_parity():
    con = duckdb.connect()
    (result,) = con.execute(
        f"SELECT {sql_normalize_apn('acct')} "
        f"FROM (SELECT CAST(NULL AS VARCHAR) AS acct) q"
    ).fetchone()
    assert result is None
    assert normalize_apn(None) is None


@pytest.mark.parametrize("bad", [
    "x; DROP TABLE parcels", "a' OR '1'='1", "", None, "a b", "f(acct)",
])
def test_sql_normalize_apn_rejects_non_identifiers(bad):
    """The expression is interpolated into statements, so `column` must be a
    plain identifier — same guard as addr.sql_normalize."""
    with pytest.raises(ValueError):
        sql_normalize_apn(bad)


def test_sql_normalize_apn_accepts_a_qualified_column():
    assert "h.acct" in sql_normalize_apn("h.acct")
