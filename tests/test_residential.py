"""Tests for pipeline/residential.py — the non-residential parcel guard.

Two things are being protected here, and they pull in opposite directions.

The SQL/Python equivalence tests are the same guard tests/test_addr.py puts on
the address rules: a rule implemented twice, where one copy builds the audit's
counts and the other explains an individual row, fails *silently* when the two
drift. Nothing else in the system notices.

The rest is the false-positive suite. Excluding a lead is destructive to a
business — a large, expensive, LLC-owned, non-owner-occupied house in Memorial
or River Oaks is a *premium* roofing lead, and every one of those attributes
also describes a strip mall. The fixtures below are deliberately weighted toward
homes that look commercial, because that is the failure mode that costs money.
"""
import duckdb
import pytest

from pipeline import residential
from pipeline.addr import normalize
from pipeline.residential import (
    ALL_REASONS, COMMERCIAL_OWNER_PHRASES, COMMERCIAL_OWNER_TOKENS, EXCLUDE,
    EXCLUDE_REASONS, REASON_LABELS, REASON_TIERS, REVIEW, classify,
    is_non_residential, sql_non_residential, sql_reason,
)

# Columns the rule reads, in the order the DuckDB fixture table declares them.
COLS = ["address", "owner_name", "property_type", "square_footage",
        "year_built", "state_class"]


def _row(address="123 MAIN ST", owner_name="SMITH JOHN", property_type=None,
         square_footage=2200, year_built=1995, state_class=None) -> dict:
    return dict(zip(COLS, [address, owner_name, property_type,
                           square_footage, year_built, state_class]))


# ── Fixtures ─────────────────────────────────────────────────────────────────
# (label, row, expected reasons). Every edge that separates the rules, plus the
# homes that must survive them.
CASES: list[tuple[str, dict, set[str]]] = [
    # The reported row, from the screenshot that prompted this module.
    ("memorial city mall",
     _row(address="0 BARRYKNOLL LN 656", owner_name="MEMORIAL CITY MALL LP",
          square_footage=147089, year_built=2001),
     {"commercial_owner", "oversized_structure", "no_situs"}),

    # ── Homes that must NOT be flagged ───────────────────────────────────────
    ("plain house", _row(), set()),
    # Held in an LLC for privacy, mail goes to a wealth manager: still a home.
    ("estate in an llc",
     _row(address="3 INWOOD DR", owner_name="INWOOD HOLDINGS LLC",
          square_footage=9800, year_built=1968), set()),
    ("family trust",
     _row(owner_name="SMITH FAMILY TRUST"), set()),
    ("estate in probate",
     _row(owner_name="ESTATE OF JOHN A SMITH"), set()),
    ("builder spec home",
     _row(owner_name="PERRY HOMES LLC", year_built=2024), set()),
    ("investor rental",
     _row(owner_name="ACME PROPERTIES INC"), set()),
    # Substring traps: these words CONTAIN commercial tokens.
    ("owner named mallory", _row(owner_name="MALLORY JOHN R"), set()),
    ("churchill downs", _row(address="9 CHURCHILL DOWNS DR",
                             owner_name="CHURCHILL DONNA"), set()),
    ("innes not inn", _row(owner_name="INNES ROBERT"), set()),
    ("plazak surname", _row(owner_name="PLAZAK MARIA"), set()),
    # A big house is not a commercial building. Harris County trophy estates
    # reach 25,000-35,000 sqft and the largest Texas home is ~48,000 — all of
    # which land in REVIEW, never in the archivable tier.
    ("trophy estate",
     _row(square_footage=30_000, owner_name="RICH SAMUEL"),
     {"large_structure"}),
    ("largest texas home",
     _row(square_footage=48_000, owner_name="RICH SAMUEL"),
     {"large_structure"}),
    ("ordinary luxury home",
     _row(square_footage=11_999, owner_name="RICH SAMUEL"), set()),
    # Acreage: huge lot, ordinary house. lot_size is not read at all.
    ("house on acreage",
     _row(address="18 FARM TO MARKET RD 1960", square_footage=2400), set()),
    ("condo unit", _row(address="5 POST OAK LN 1204", property_type="Condo",
                        square_footage=1400), set()),
    ("manufactured home", _row(property_type="Manufactured",
                               square_footage=1100), set()),

    # ── Parcels that must be flagged ─────────────────────────────────────────
    ("county class F1", _row(state_class="F1"), {"county_class"}),
    ("county class A1 is residential", _row(state_class="A1"), set()),
    ("county class B multifamily kept", _row(state_class="B2"), set()),
    ("school district", _row(owner_name="HOUSTON ISD"), {"commercial_owner"}),
    ("municipality", _row(owner_name="CITY OF HOUSTON"), {"commercial_owner"}),
    ("self storage", _row(owner_name="ACME SELF STORAGE LTD"),
     {"commercial_owner"}),
    # Institution words that are ALSO surnames land in REVIEW, not EXCLUDE.
    ("church", _row(owner_name="FIRST BAPTIST CHURCH"),
     {"possible_commercial_owner"}),
    ("county exempt", _row(state_class="X3"), {"county_exempt"}),
    # "Apartment" is deliberately NOT excludable: RentCast uses it for both a
    # unit and a building, and a duplex is a roof we sell to.
    ("apartment type", _row(property_type="Apartment"), set()),
    ("multi family type", _row(property_type="Multi-Family"), set()),
    ("land type", _row(property_type="Land"), {"non_residential_type"}),
    ("retail type", _row(property_type="Retail"), {"non_residential_type"}),
    ("strip centre sized", _row(square_footage=60_000),
     {"oversized_structure"}),
    ("no street number", _row(address="0 LEE RD"), {"no_situs"}),
    ("vacant lot", _row(address="0 TRUXTON ST", square_footage=0,
                        year_built=0), {"no_situs", "no_structure"}),
    ("empty structure only", _row(square_footage=0, year_built=0),
     {"no_structure"}),
]

IDS = [c[0] for c in CASES]


@pytest.mark.parametrize("label,row,expected", CASES, ids=IDS)
def test_classify(label, row, expected):
    assert set(classify(row)) == expected


# ── Regressions: rows an earlier version of this rule would have archived ────
# Each of these is a real, paying-customer-shaped row. They are kept as their own
# named tests rather than fixtures so a failure says exactly who got deleted.

ADDRESSLESS_LEADS = [
    ("inbound call", {"address": None, "contact_name": "Maria Garcia"}),
    ("inbound sms", {"address": None, "contact_phone": "7135551234"}),
    ("web intake", {"address": "", "contact_email": "bob@example.com"}),
    ("csv contact", {"address": None, "owner_name": "GARCIA MARIA"}),
]


@pytest.mark.parametrize("label,row", ADDRESSLESS_LEADS,
                         ids=[c[0] for c in ADDRESSLESS_LEADS])
def test_address_less_leads_are_never_flagged(label, row):
    """`properties` is the contact book as well as the parcel table.

    address is nullable (migration 0018) and four production paths create leads
    with none: inbound call (twilio_voice), inbound SMS (twilio_inbound), the
    public web form (public_intake) and address-less CSV contacts (imports).
    addr.has_situs(None) is False, so testing it directly flagged every one of
    them EXCLUDE — one click on the archive endpoint would have wiped an
    account's entire inbound book.
    """
    assert classify(row) == []
    assert is_non_residential(row) is False


# HCAD writes owner names LAST-FIRST, so a surname is a whole-word token in
# exactly the position the owner rule inspects.
SURNAME_HOMEOWNERS = [
    ("CHURCH JOHN A", "4102 INKER ST"),
    ("PARISH MARY E", "11 W FRIAR TUCK"),
    ("PLAZA JOSE L", "7710 ELMHURST"),
    ("CHAPEL DIANE", "902 OAK ST"),
    ("INN SOO KIM", "9 INWOOD DR"),
    ("TEMPLE ROBERT", "44 PINE"),
    ("BISHOP ANNE M", "8 CEDAR CT"),
    ("HOSPITAL ANA", "17 ELM"),
]


@pytest.mark.parametrize("owner,address", SURNAME_HOMEOWNERS,
                         ids=[o for o, _ in SURNAME_HOMEOWNERS])
def test_homeowners_with_institutional_surnames_are_not_archived(owner, address):
    """Guarding against substring collisions (MALLORY != MALL) is not enough
    when the token IS the whole word. These are homeowners."""
    row = _row(address=address, owner_name=owner,
               square_footage=1800, year_built=1960)
    assert is_non_residential(row) is False, owner
    assert classify(row) == ["possible_commercial_owner"], owner


def test_exempt_class_does_not_archive_a_disabled_veterans_home():
    """Texas state class X is a TAX STATUS, not a use category. It covers
    100%-disabled-veteran residence homesteads (Tax Code 11.131), parsonages and
    charitable housing — all houses with roofs, in a county with a large veteran
    population."""
    vet = _row(address="5514 ARBOLES DR", owner_name="RAMIREZ LUIS",
               square_footage=2050, year_built=1979, state_class="X")
    assert classify(vet) == ["county_exempt"]
    assert is_non_residential(vet) is False


def test_owner_reasons_are_mutually_exclusive():
    """`elif` in classify(), so the audit's per-reason counts cannot
    double-count one owner name."""
    for owner in ["MEMORIAL CITY MALL LP", "CHURCH JOHN A", "HOUSTON ISD",
                  "FIRST BAPTIST CHURCH", "SMITH JOHN"]:
        reasons = classify(_row(owner_name=owner))
        assert not ({"commercial_owner", "possible_commercial_owner"}
                    <= set(reasons)), owner


def test_classify_orders_most_decisive_first():
    """The first reason is what a UI shows, so ordering is behaviour."""
    reasons = classify(_row(address="0 BARRYKNOLL LN 656",
                            owner_name="MEMORIAL CITY MALL LP",
                            square_footage=147089, state_class="F1"))
    assert reasons[0] == "county_class"
    assert reasons == [r for r in ALL_REASONS if r in reasons]


def test_unknown_row_is_not_flagged():
    """Absence of evidence is never evidence: an all-NULL row must survive.

    A row this empty is exactly what a fresh seed looks like before enrichment
    runs, and flagging it would archive an account's entire new ZIP.
    """
    empty = {c: None for c in COLS}
    empty["address"] = "77 OAK LN"
    assert classify(empty) == ["no_structure"]
    assert is_non_residential(empty) is False


def test_missing_keys_are_treated_as_unknown():
    assert classify({"address": "1 ELM ST"}) == ["no_structure"]


def test_is_non_residential_ignores_review_tier():
    """`no_structure` is REVIEW, so it must not make a row auto-excludable."""
    vacant = _row(square_footage=0, year_built=0)
    assert classify(vacant) == ["no_structure"]
    assert is_non_residential(vacant) is False


# ── Reason metadata ──────────────────────────────────────────────────────────

def test_every_reason_has_a_tier_and_a_label():
    assert set(REASON_LABELS) == set(REASON_TIERS) == set(ALL_REASONS)
    assert set(REASON_TIERS.values()) <= {EXCLUDE, REVIEW}


def test_exclude_reasons_are_the_excludable_ones():
    assert EXCLUDE_REASONS == [r for r in ALL_REASONS
                               if REASON_TIERS[r] == EXCLUDE]
    assert "no_structure" not in EXCLUDE_REASONS


# ── Owner-token safety ───────────────────────────────────────────────────────

def test_owner_tokens_are_pre_normalized():
    """Membership is tested against addr.normalize's output, so the constants
    must already be in that form or they can never match."""
    for token in COMMERCIAL_OWNER_TOKENS:
        assert token == normalize(token), token
    for phrase in COMMERCIAL_OWNER_PHRASES:
        assert phrase == normalize(phrase), phrase


@pytest.mark.parametrize("suffix", [
    "LLC", "LP", "INC", "LTD", "CORP", "TRUST", "ESTATE", "PROPERTIES",
    "HOLDINGS", "INVESTMENTS", "HOMES", "REALTY", "PARTNERS", "GROUP",
])
def test_entity_suffixes_are_not_commercial_signals(suffix):
    """How title is held says nothing about what was built on the land.

    This is the single most expensive false positive available: rentals,
    probate estates, builder inventory and privacy-held estates all carry these,
    and every one is a real lead.
    """
    assert classify(_row(owner_name=f"OAKWOOD {suffix}")) == []


def test_commercial_tokens_match_whole_words_only():
    """The owner.py lesson: 'MALLORY' must never satisfy 'mall'."""
    for token in sorted(COMMERCIAL_OWNER_TOKENS):
        glued = f"{token}wood".upper()
        assert classify(_row(owner_name=f"{glued} JOHN")) == [], glued


# ── Thresholds ───────────────────────────────────────────────────────────────

def test_size_bands_are_contiguous_and_inclusive_at_the_boundary(monkeypatch):
    monkeypatch.setattr(residential, "NONRESIDENTIAL_MIN_SQFT", 50_000)
    monkeypatch.setattr(residential, "NONRESIDENTIAL_REVIEW_SQFT", 12_000)
    assert classify(_row(square_footage=50_000)) == ["oversized_structure"]
    assert classify(_row(square_footage=49_999)) == ["large_structure"]
    assert classify(_row(square_footage=12_000)) == ["large_structure"]
    assert classify(_row(square_footage=11_999)) == []


def test_no_house_sized_row_is_ever_auto_archived(monkeypatch):
    """The overlap band between the largest dwellings and the smallest
    commercial buildings must never be actionable on size alone."""
    monkeypatch.setattr(residential, "NONRESIDENTIAL_MIN_SQFT", 50_000)
    monkeypatch.setattr(residential, "NONRESIDENTIAL_REVIEW_SQFT", 12_000)
    for sqft in (12_000, 25_000, 35_000, 48_000, 49_999):
        row = _row(square_footage=sqft, owner_name="RICH SAMUEL")
        assert is_non_residential(row) is False, sqft


def test_property_type_denylist_disabled_flags_nothing(monkeypatch):
    """`SEED_PROPERTY_TYPES='*'` disables type filtering account-wide; this rule
    must honour the same switch rather than quietly keeping its own opinion."""
    monkeypatch.setattr(residential, "SEED_PROPERTY_TYPES", ["*"])
    assert classify(_row(property_type="Apartment")) == []
    assert sql_reason("non_residential_type") == "(FALSE)"


def test_residential_types_are_never_flagged():
    """Includes spellings the allowlist would have missed: addr.normalize DROPS
    punctuation, so "Single-Family" keys as "singlefamily" and matches no
    allowlist entry. Under the denylist an unrecognised spelling is kept.
    """
    for spelling in ["Single Family", "SINGLE FAMILY", "single  family",
                     "Single-Family", "Duplex", "Multi-Family", "Townhouse",
                     "Mobile Home", ""]:
        assert classify(_row(property_type=spelling)) == [], spelling


def test_denylist_entries_are_pre_normalized():
    from pipeline.residential import NON_RESIDENTIAL_PROPERTY_TYPES
    for entry in NON_RESIDENTIAL_PROPERTY_TYPES:
        assert entry == normalize(entry), entry


# ── SQL / Python parity ──────────────────────────────────────────────────────
# `no_situs` is excluded from the DuckDB run for the reason addr.py documents:
# sql_has_situs is Postgres-only, because Postgres's `~` is an unanchored match
# where DuckDB's is a full match. It is covered by the Python tests above and by
# the composition test below.
_DUCKDB_REASONS = [r for r in ALL_REASONS if r != "no_situs"]


def _duckdb_fixture():
    con = duckdb.connect()
    con.execute("""CREATE TABLE properties (
        address VARCHAR, owner_name VARCHAR, property_type VARCHAR,
        square_footage BIGINT, year_built BIGINT, state_class VARCHAR)""")
    con.executemany(
        "INSERT INTO properties VALUES (?, ?, ?, ?, ?, ?)",
        [[row[c] for c in COLS] for _, row, _ in CASES],
    )
    return con


@pytest.mark.parametrize("reason", _DUCKDB_REASONS)
def test_sql_expression_matches_python_exactly(reason):
    """Run the generated SQL in a real engine and compare, row for row.

    This is the test that catches the drift the audit could not: the counts come
    from this SQL, the per-row explanation comes from classify(), and a user
    reading both would see a total that does not match its own examples.
    """
    con = _duckdb_fixture()
    try:
        got = [r[0] for r in con.execute(
            f"SELECT {sql_reason(reason)} FROM properties").fetchall()]
    finally:
        con.close()
    expected = [reason in classify(row) for _, row, _ in CASES]
    assert got == expected, [
        (label, g, e) for (label, _, _), g, e in zip(CASES, got, expected) if g != e
    ]


def test_sql_null_parity():
    """An all-NULL row must read the same on both sides."""
    con = duckdb.connect()
    try:
        for reason in _DUCKDB_REASONS:
            (out,) = con.execute(f"""
                SELECT {sql_reason(reason)} FROM (
                    SELECT CAST(NULL AS VARCHAR) AS address,
                           CAST(NULL AS VARCHAR) AS owner_name,
                           CAST(NULL AS VARCHAR) AS property_type,
                           CAST(NULL AS BIGINT)  AS square_footage,
                           CAST(NULL AS BIGINT)  AS year_built,
                           CAST(NULL AS VARCHAR) AS state_class) q
            """).fetchone()
            empty = {c: None for c in COLS}
            assert bool(out) is (reason in classify(empty)), reason
    finally:
        con.close()


def test_sql_non_residential_tiers():
    con = _duckdb_fixture()
    try:
        # tier=EXCLUDE must never fire on a row whose only reason is REVIEW.
        excl_sql = " OR ".join(sql_reason(r) for r in EXCLUDE_REASONS
                               if r != "no_situs")
        got = [r[0] for r in con.execute(
            f"SELECT ({excl_sql}) FROM properties").fetchall()]
    finally:
        con.close()
    expected = [any(REASON_TIERS[x] == EXCLUDE and x != "no_situs"
                    for x in classify(row)) for _, row, _ in CASES]
    assert got == expected


# ── SQL construction safety ──────────────────────────────────────────────────

def test_generated_sql_contains_no_percent_metacharacter():
    """psycopg2 interpolates the statement whenever parameters are bound, so a
    literal '%' is read as the start of a placeholder — LIKE '%city of%' dies
    with "unsupported format character 'c'". Every reason is used in a
    parameterized query (the audit, and parcels.seed_account), so none of them
    may contain one.
    """
    for reason in ALL_REASONS:
        assert "%" not in sql_reason(reason), reason
    assert "%" not in sql_non_residential("p.", tier=None)


@pytest.mark.parametrize("bad", [
    "x; DROP TABLE properties;--", "a' OR '1'='1", "p", "p..", "1.", "f(p).",
])
def test_bad_alias_is_rejected(bad):
    with pytest.raises(ValueError):
        sql_reason("no_situs", prefix=bad)


def test_empty_prefix_is_allowed():
    assert "address" in sql_reason("no_situs", prefix="")


def test_unknown_reason_raises():
    with pytest.raises(ValueError):
        sql_reason("not_a_reason")


def test_prefix_qualifies_every_column():
    """A joined query must not accidentally read the wrong table's columns."""
    for reason in ALL_REASONS:
        expr = sql_reason(reason, prefix="p.")
        bare = sql_reason(reason, prefix="")
        assert expr != bare, reason
        assert "p." in expr, reason


def test_seed_filter_uses_the_shared_rule():
    """parcels.seed_account must apply this module's rule, not its own copy —
    what a seed refuses and what the audit archives have to be one rule.
    """
    import inspect

    from pipeline import parcels
    source = inspect.getsource(parcels.seed_account)
    assert "residential_only" in source
    assert "sql_non_residential" in source
