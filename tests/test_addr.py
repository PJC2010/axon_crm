"""Tests for pipeline/addr.py — shared address normalization.

The SQL/Python equivalence tests here are the guard against the failure mode
that made HCAD enrichment silently skip parcels: match keys built by a query and
looked up by Python must agree byte for byte, and nothing else in the system
notices when they don't.
"""
import duckdb
import pytest

from pipeline.addr import (
    has_situs, normalize, same_address, sql_has_situs, sql_normalize,
)
from pipeline import hcad_store

# Address shapes that separate the two rules. Anything carrying punctuation or a
# double space keyed differently under the old inlined expression.
ADDRESSES = [
    "13403 BRIAR FOREST DR",     # clean — matched even before the fix
    "1234 MAIN-ST",              # hyphen
    "500 W 12TH 1/2 ST",         # fraction
    "77 OAK LN #5",              # unit marker
    "9 ST. CHARLES BLVD",        # period
    "12  ELM  ST",               # double space
    "45 O'CONNOR RD",            # apostrophe
    "88 A&M CIRCLE",             # ampersand
    "  7 LEAD SPACE RD  ",       # leading/trailing space
    "1 TAB\tSEP ST",             # tab
    "",
]


def test_lowercase_and_strip_punctuation():
    assert normalize("123 Main St.") == "123 main st"


def test_collapses_whitespace():
    assert normalize("123   Main    St") == "123 main st"


def test_empty_and_none_safe():
    assert normalize("") == ""
    assert normalize(None) == ""


def test_hcad_store_uses_shared_normalize():
    # hcad_store re-exports the same function (single source of truth).
    assert hcad_store.normalize("456 Oak Ave!") == normalize("456 Oak Ave!")


# ── sql_normalize ─────────────────────────────────────────────────────────────

def test_sql_expression_matches_python_exactly():
    """Run the generated SQL in a real engine and compare, key for key.

    This is the test that would have caught the original bug: the two rules only
    diverge on punctuation and repeated spaces, so a clean-address fixture passes
    under either one.
    """
    con = duckdb.connect()
    con.execute("CREATE TABLE t (site_address VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [[a] for a in ADDRESSES])
    rows = con.execute(
        f"SELECT site_address, {sql_normalize('site_address')} FROM t"
    ).fetchall()
    con.close()

    assert rows, "fixture did not load"
    for raw, sql_key in rows:
        assert sql_key == normalize(raw), f"{raw!r}: SQL {sql_key!r} != Python {normalize(raw)!r}"


def test_sql_expression_handles_null_like_python():
    con = duckdb.connect()
    key = con.execute(
        f"SELECT {sql_normalize('a')} FROM (SELECT NULL::VARCHAR AS a)"
    ).fetchone()[0]
    con.close()
    assert key == normalize(None) == ""


def test_qualified_column_is_accepted():
    assert "ps.site_address" in sql_normalize("ps.site_address")


def test_non_identifier_is_rejected():
    """The expression is interpolated, so the identifier check is the guard."""
    for bad in ["x; DROP TABLE y", "a' OR '1'='1", "", None, "a b"]:
        with pytest.raises(ValueError):
            sql_normalize(bad)


def test_hcad_store_keys_are_built_from_the_shared_rule():
    """Regression: every query in hcad_store used to inline its own expression."""
    import pipeline.hcad_store as store
    import inspect

    source = inspect.getsource(store)
    assert "[^a-zA-Z0-9 ]" not in source, "an old-rule expression is back"
    assert store._ADDR_NORM_PS == sql_normalize("ps.site_address")
    assert store._ADDR_NORM_HP == sql_normalize("hp.site_address")
    assert store._ADDR_NORM == sql_normalize("site_address")


# ── has_situs ─────────────────────────────────────────────────────────────────
# Gates paid, address-keyed lookups: a no-situs parcel (HCAD's zero house
# number) can never be matched by RentCast or a skip-trace, so it must never
# earn a call — and being the emptiest rows, they hog any capped budget that
# does not exclude them.

@pytest.mark.parametrize("address", [
    "0 TRUXTON ST", "0 LEE RD", "00 RANKIN RD", "  0 SMITH RD", "0", "", None,
])
def test_no_situs_addresses_are_rejected(address):
    assert has_situs(address) is False


@pytest.mark.parametrize("address", [
    "16727 TRUXTON ST",
    "07 MAIN ST",           # zero-padded, not all zeros
    "1050 ZERO RD",
    "13935 SMITH RD 112",
    "500 W 12TH 1/2 ST",
])
def test_real_addresses_pass(address):
    assert has_situs(address) is True


def test_sql_has_situs_identifier_guard():
    for bad in ["x; DROP TABLE y", "a' OR '1'='1", "", None, "a b"]:
        with pytest.raises(ValueError):
            sql_has_situs(bad)


def test_paid_candidate_queries_carry_the_situs_guard():
    """Regression: both fetch_missing_* builders must exclude no-situs rows, or
    a capped sweep goes back to spending its whole budget on vacant land."""
    import inspect
    import pipeline.db as db
    source = inspect.getsource(db.fetch_missing_any) + \
        inspect.getsource(db.fetch_missing_field)
    assert source.count("sql_has_situs('address')") == 2


# ── same_address ──────────────────────────────────────────────────────────────
# Used to check a vendor answered about the property we asked about. It gates
# whether data is accepted, so it errs toward True — a false negative silently
# discards data we already paid for.

@pytest.mark.parametrize("requested, returned", [
    ("123 Main St", "123 Main St"),            # identical
    ("123 Main St", "123 MAIN ST"),            # casing
    ("123 Main St", "123 Main Street"),        # spelled-out suffix
    ("123 Main Ave", "123 Main Avenue"),
    ("123 W Main St", "123 Main St"),          # directional on one side only
    ("123 Main St", "123 N Main St"),
    ("123 Main St", "123 Main St Apt 4"),      # unit the other side omits
    ("500 W 12TH 1/2 ST", "500 W 12th 1/2 St"),
    ("9 ST. CHARLES BLVD", "9 St Charles Blvd"),
])
def test_accepts_the_same_property(requested, returned):
    assert same_address(requested, returned) is True


@pytest.mark.parametrize("requested, returned", [
    ("123 Main St", "125 Main St"),            # different house number
    ("123 Main St", "1230 Main St"),
    ("123 Main St", "123 Oak St"),             # different street
    ("123 Main St", "456 Elm Ave"),
])
def test_rejects_a_different_property(requested, returned):
    assert same_address(requested, returned) is False


def test_missing_side_is_never_a_match():
    """No evidence is not evidence of a match — do not accept the record."""
    assert same_address("123 Main St", "") is False
    assert same_address("", "123 Main St") is False
    assert same_address(None, None) is False


def test_suffix_only_difference_does_not_reject():
    """After folding, '123 St' vs '123 Street' has no street words left on either
    side — that is not grounds to reject."""
    assert same_address("123 St", "123 Street") is True
