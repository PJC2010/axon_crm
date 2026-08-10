"""Tests for pipeline/owner.py — the junk owner-name guard.

The SQL/Python equivalence tests are the same guard tests/test_addr.py runs for
address keys: a placeholder nulled by Python ingestion but kept by a SQL path
(or vice versa) would silently re-open the cost leak — a stored "CURRENT OWNER"
blocks the RentCast fill and bills skip-trace lookups for a person who does not
exist.
"""
import duckdb
import pytest

from pipeline.owner import (
    JUNK_OWNER_NAMES, clean_owner_name, is_junk_owner_name, sql_clean_owner_name,
)

# Real-shaped values from the HCAD export alongside every placeholder variant.
NAMES = [
    "CURRENT OWNER",             # the placeholder HCAD actually stamps
    "CURRENT PROPERTY OWNER",    # seen in ZIP 77396
    "Current Owner",             # casing must not matter
    "  CURRENT  OWNER  ",        # spacing must not matter
    "N/A",                       # normalizes to "na"
    "UNKNOWN",
    "HWANG PETER",               # real person — must pass
    "CAPUCHINA LIZETTE",
    "OWENS CURRENT",             # placeholder words, different name — must pass
    "OWNER FINANCE LLC",         # business containing 'owner' — must pass
    "COUNTY OF HARRIS",          # government owner is real, not junk
    "O'CONNOR, MARY",            # punctuation in a real name
    "",
]


# ── clean_owner_name ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("junk", [
    "CURRENT OWNER", "current owner", "Current  Owner", "CURRENT PROPERTY OWNER",
    "PROPERTY OWNER", "OWNER", "UNKNOWN", "N/A", "HOMEOWNER", "TAXPAYER",
    "CONFIDENTIAL", "", "   ", None,
])
def test_placeholders_become_none(junk):
    assert clean_owner_name(junk) is None
    assert is_junk_owner_name(junk) is True


@pytest.mark.parametrize("real", [
    "HWANG PETER", "OWENS CURRENT", "OWNER FINANCE LLC", "COUNTY OF HARRIS",
    "O'CONNOR, MARY", "SMITH JOHN JR", "NAOMI NG",   # 'na' must not match on prefix
])
def test_real_names_pass_through(real):
    assert clean_owner_name(real) == real
    assert is_junk_owner_name(real) is False


def test_real_names_keep_their_casing_and_punctuation():
    assert clean_owner_name("  O'Connor, Mary  ") == "O'Connor, Mary"


def test_junk_list_is_pre_normalized():
    """Membership is tested against addr.normalize output, so every entry must
    already be in that form or it can never match."""
    from pipeline.addr import normalize
    for entry in JUNK_OWNER_NAMES:
        assert entry == normalize(entry), f"{entry!r} is not in normalized form"


# ── sql_clean_owner_name ──────────────────────────────────────────────────────

def test_sql_expression_matches_python_exactly():
    """Run the generated SQL in a real engine and compare, value for value."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t (owner_name VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [[n] for n in NAMES])
    rows = con.execute(
        f"SELECT owner_name, {sql_clean_owner_name('owner_name')} FROM t"
    ).fetchall()
    con.close()

    assert rows, "fixture did not load"
    for raw, sql_cleaned in rows:
        expected = clean_owner_name(raw)
        # SQL TRIM strips spaces; Python .strip() also strips tabs/newlines.
        # The fixture stays within spaces, so the two must agree byte for byte.
        assert sql_cleaned == expected, (
            f"{raw!r}: SQL {sql_cleaned!r} != Python {expected!r}")


def test_sql_expression_handles_null_like_python():
    con = duckdb.connect()
    out = con.execute(
        f"SELECT {sql_clean_owner_name('a')} FROM (SELECT NULL::VARCHAR AS a)"
    ).fetchone()[0]
    con.close()
    assert out is None is clean_owner_name(None)


def test_non_identifier_is_rejected():
    """The expression is interpolated into queries, so the identifier check
    (delegated to addr.sql_normalize) is the injection guard."""
    for bad in ["x; DROP TABLE y", "a' OR '1'='1", "", None, "a b"]:
        with pytest.raises(ValueError):
            sql_clean_owner_name(bad)


def test_hcad_store_uses_the_shared_rule():
    """Regression guard: every hcad_store query must ship owner_name through
    this one expression, or a placeholder sneaks back in via one code path."""
    from pipeline import hcad_store
    assert hcad_store._OWNER_CLEAN_PS == sql_clean_owner_name("ps.owner_name")
    assert hcad_store._OWNER_CLEAN == sql_clean_owner_name("owner_name")


def test_migration_0067_list_matches_python():
    """The one-time cleanup migration hardcodes the junk list; if the Python
    list grows, the migration is history — but the two must agree on what was
    junk at the time it shipped, and this pins that every entry it names is in
    JUNK_OWNER_NAMES."""
    import re
    from pathlib import Path
    sql = (Path(__file__).parent.parent /
           "db/migrations/0067_null_junk_owner_names.sql").read_text()
    in_lists = set(re.findall(r"'([a-z /]+)'", sql.split("IN (")[1].split(")")[0]))
    assert in_lists == set(JUNK_OWNER_NAMES)
