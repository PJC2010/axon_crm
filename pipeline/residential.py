"""
Non-residential parcel guard — single source of truth for "this is not a home".

Axon targets residential homeowners (see docs/hcad_real_property_mapping.md), but
the free HCAD seed path takes a whole ZIP off the county roll. The county roll is
every *parcel*, not every *house*: shopping centres, churches, school-district
land, warehouses and vacant lots all come with it. The RentCast seed path has
filtered on `propertyType` since day one (config.SEED_PROPERTY_TYPES,
pipeline/seed.py::_wanted_type); the HCAD path — the cheaper one, and therefore
the one most accounts run — had no equivalent, so a mall seeded, scored, and sat
in the pipeline as a live B-grade lead.

That is expensive in three separate ways:

  * The skip-trace and demographic steps bill per row (pipeline/contact.py,
    pipeline/demographics.py). A mall's "owner" is a holding company; the lookup
    can never produce a homeowner to call.
  * `estimated_value` and `square_footage` feed scoring and the neighborhood
    benchmark, so a $13M/147,000 sqft parcel moves the numbers every legitimate
    house in its cell is compared against.
  * A rep works the list. Time spent on a parcel nobody lives at is the costliest
    part of all.

Like pipeline/addr.py and pipeline/owner.py, the one rule lives here in two
byte-compatible forms, because it is needed on both sides of the wire:

  classify()          Python: the reasons a row looks non-residential.
  sql_non_residential()  The same rule as a SQL expression, so the audit can
                      count a whole account without reading it into memory and
                      the seed can filter server-side.

Both are exercised against a real engine in tests/test_residential.py, the same
guard tests/test_addr.py puts on the address rules — a Python rule and a SQL rule
that quietly disagree is the failure mode this codebase has already been bitten
by once.

── What this deliberately does NOT do ────────────────────────────────────────

It does not try to be the county's land-use classifier. HCAD publishes
`state_class` on `real_acct.txt` (A1 single-family, B multi-family, C vacant,
F1/F2 commercial/industrial…), which is the authoritative answer, and
tools/build_hcad_duckdb.py now carries it through — but that only takes effect
after the next HCAD load, and it will never exist for RentCast- or CSV-sourced
rows. Everything here is computable from columns `properties` already holds
today, on any account, with zero re-ingest and zero vendor calls. When
`state_class` is present it is used as the strongest signal; when it is absent
the heuristics below still work.

── Erring in the right direction ─────────────────────────────────────────────

The two failure modes are not symmetric, so the reasons are tiered.

A false positive throws away a real customer. A large, expensive, LLC-owned,
non-owner-occupied house is a *premium* roofing lead: in 77024 (Memorial) or
77019 (River Oaks) a legitimate 8,000 sqft home is worth $3M+ and is routinely
held in an LLC or family trust with the tax bill going to a wealth manager
downtown. Nothing here may key on value, on owner-occupancy, on lot size, or on
an LLC/LP/INC/TRUST suffix alone — every one of those describes that house as
well as it describes a strip mall.

A false negative just leaves a bad row on the list, where the operator can see
it. So `EXCLUDE` reasons are the ones that are structurally impossible for a
home, and everything else is `REVIEW` — surfaced, counted, but never acted on
automatically.
"""
import re

from config import (
    NONRESIDENTIAL_MIN_SQFT, NONRESIDENTIAL_REVIEW_SQFT, SEED_PROPERTY_TYPES,
)
from pipeline.addr import has_situs, normalize, sql_has_situs, sql_normalize

# A table alias plus its dot ("p."), or empty. Mirrors addr._SQL_IDENT's posture:
# validate, never quote.
_ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.$")

# ── Reason tiers ─────────────────────────────────────────────────────────────
# EXCLUDE: structurally impossible for a residence. Safe to archive in bulk.
# REVIEW:  suspicious, but a legitimate home can look like this. Report only.
EXCLUDE = "exclude"
REVIEW = "review"

# Ordered most- to least-decisive; `classify` returns them in this order so the
# first reason is always the best explanation to show a human.
REASON_TIERS: dict[str, str] = {
    "county_class":        EXCLUDE,
    "commercial_owner":    EXCLUDE,
    "non_residential_type": EXCLUDE,
    "oversized_structure": EXCLUDE,
    "no_situs":            EXCLUDE,
    "county_exempt":       REVIEW,
    "possible_commercial_owner": REVIEW,
    "large_structure":     REVIEW,
    "no_structure":        REVIEW,
}

REASON_LABELS: dict[str, str] = {
    "county_class":        "County classifies this parcel as non-residential",
    "commercial_owner":    "Owner name identifies a business or institution",
    "county_exempt":       ("County records this parcel as tax-exempt — a "
                            "church or school, or a disabled veteran's home"),
    "possible_commercial_owner": ("Owner name may identify a business — or may "
                                  "be a surname"),
    "non_residential_type": "Property type is not residential",
    "oversized_structure": f"Building is {NONRESIDENTIAL_MIN_SQFT:,}+ sqft — larger than any dwelling",
    "no_situs":            "No street address — parcel is numbered 0 on the county roll",
    "large_structure":     (f"Building is {NONRESIDENTIAL_REVIEW_SQFT:,}–"
                            f"{NONRESIDENTIAL_MIN_SQFT:,} sqft — a large estate "
                            f"or a small commercial building"),
    "no_structure":        "No building on the parcel (vacant land)",
}

ALL_REASONS = list(REASON_TIERS)
EXCLUDE_REASONS = [r for r, t in REASON_TIERS.items() if t == EXCLUDE]
REVIEW_REASONS = [r for r, t in REASON_TIERS.items() if t == REVIEW]


# ── Signal 1: the county's own classification ────────────────────────────────
# HCAD state_class prefixes (pdataCodebook). Only the unambiguous ones; anything
# not listed is treated as "no opinion" rather than guessed at, because a wrong
# guess here excludes a paying customer.
#
#   A  real property, single-family        ← residential
#   B  real property, multi-family         ← 2-4 units is still a roof we sell
#   C  real property, vacant               ← handled by `no_structure`, not here
#   E  real property, rural/farm w/ improvement ← often a house on acreage
#   F  real property, commercial/industrial
#   J  utilities
#   L  personal property, commercial/industrial
#   M  mobile homes                        ← residential (Manufactured)
#   S  special inventory (dealer stock)
#   X  totally exempt  ← NOT a use category. See below.
#
# Residential is the allowlist; the rest of the alphabet is not automatically
# commercial, so only these prefixes trigger the reason.
RESIDENTIAL_STATE_CLASS_PREFIXES = ("A", "B", "E", "M")
COMMERCIAL_STATE_CLASS_PREFIXES = ("F", "J", "L", "S")

# X is deliberately NOT in the list above. It is a *tax status* — "Totally
# Exempt Property" — not a statement about what stands on the land, and it
# covers 100%-disabled-veteran residence homesteads (Texas Tax Code 11.131),
# church-owned parsonages and charitable housing. Every one of those is a house
# with a roof, and Harris County has a large veteran population, so treating X
# as commercial would archive those homeowners the moment the HCAD load lands —
# and present it to the operator as county-verified. It carries real signal
# (government, school and church parcels are also X), so it is reported at
# REVIEW tier and never acted on automatically.
EXEMPT_STATE_CLASS_PREFIXES = ("X",)


# ── Signal 2: owner names that name a building, not a household ──────────────
# Matched as whole words against the normalized name, never as substrings — the
# lesson pipeline/owner.py records: "MALLORY" must not match "MALL", and
# "CHURCHILL DOWNS RD" must not match "CHURCH".
#
# Deliberately absent: LLC, LP, INC, LTD, CORP, TRUST, ESTATE, PROPERTIES,
# HOLDINGS, INVESTMENTS, HOMES, REALTY. Every one of them appears on the deed of
# a house we want to sell to — a rental held in an LLC, an estate in probate, a
# builder's spec home. An entity suffix says how title is held, not what was
# built on the land.
# Split by one question only: could this word plausibly be a person's surname?
#
# HCAD writes owner names LAST-FIRST ("CAPUCHINA LIZETTE", "LANGLEY DONNA M" —
# see pipeline/owner.py), so a surname is a whole-word token in exactly the
# position this rule inspects. "CHURCH JOHN A", "PARISH MARY E", "PLAZA JOSE L",
# "CHAPEL DIANE" and "INN SOO KIM" are homeowners, and an earlier version of
# this list archived every one of them. Guarding against substring collisions
# (MALLORY ≠ MALL) is not enough when the token IS the whole word.
#
# So: words that are essentially never American surnames are actionable, and
# words that are also surnames are reported at REVIEW tier for a human. The
# split costs some automation on genuine churches and hotels; it does not cost
# anyone their customers.
COMMERCIAL_OWNER_TOKENS = frozenset({
    # Retail / hospitality
    "mall", "malls", "shoppes", "outlets", "motel",
    # Industrial / logistics
    "warehouse", "warehouses", "refinery", "refining", "terminals",
    "distribution", "logistics", "manufacturing",
    # Worship
    "ministries", "ministry", "synagogue", "mosque", "archdiocese",
    "tabernacle", "iglesia", "templo",
    # Education / civic / medical
    "isd", "crematory", "mortuary",
    # Infrastructure / utility
    "pipeline", "railroad", "railway", "telecom", "utilities", "waterworks",
    "airlines",
})

# Real signal, but each is also a surname carried by real homeowners. Reported,
# never archived automatically.
AMBIGUOUS_OWNER_TOKENS = frozenset({
    "plaza", "hotel", "hotels", "inn", "restaurant", "cafeteria", "foundry",
    "church", "churches", "chapel", "parish", "congregation", "diocese",
    "fellowship", "temple", "abbey", "bishop", "priest",
    "hospital", "clinic", "university", "college", "seminary", "academy",
    "cemetery", "funeral", "telephone", "electric", "aviation", "airport",
    "towers", "storage", "school",
})

assert not (COMMERCIAL_OWNER_TOKENS & AMBIGUOUS_OWNER_TOKENS), \
    "a token must be actionable or ambiguous, not both"

# Multi-word phrases, matched on whole-word boundaries exactly like the single
# tokens above. A phrase is specific enough to be worth having where a bare word
# would be far too broad: "city" alone would hit "CITY VIEW HOMES LLC", but
# "city of" does not.
#
# The boundary is not optional, and a plain substring test is not good enough:
# "state of" is a substring of "e-state of", so "ESTATE OF JOHN A SMITH" — a
# house in probate, and a real lead — matched as government property. Padding
# both the name and the phrase with spaces is what separates them.
COMMERCIAL_OWNER_PHRASES = (
    "city of", "county of", "state of", "united states", "department of",
    "school district", "independent school", "housing authority",
    "port authority", "transit authority", "water authority",
    "municipal utility", "utility district", "improvement district",
    "flood control", "board of education", "public storage",
    "self storage", "storage center", "shopping center", "strip center",
    "office park", "business park", "industrial park", "medical center",
    "car wash", "gas station", "convenience store", "funeral home",
    "nursing home", "assisted living", "apartment homes", "apartments ltd",
)


def _owner_looks_commercial(owner_name) -> bool:
    """True when an owner name unambiguously identifies a business or institution.

    Whole-word membership for single tokens and for the multi-word phrases
    (padded on both sides), both against `addr.normalize`'s output so
    punctuation and casing cannot defeat them.
    """
    key = normalize(str(owner_name or ""))
    if not key:
        return False
    padded = f" {key} "
    if any(f" {phrase} " in padded for phrase in COMMERCIAL_OWNER_PHRASES):
        return True
    return bool(set(key.split()) & COMMERCIAL_OWNER_TOKENS)


def _owner_maybe_commercial(owner_name) -> bool:
    """True for the words that are institutions *and* surnames — review only."""
    key = normalize(str(owner_name or ""))
    if not key:
        return False
    return bool(set(key.split()) & AMBIGUOUS_OWNER_TOKENS)


# ── Signal 3: property_type is a known non-residential type ──────────────────
# A DENYLIST, deliberately, where the seed uses an allowlist
# (config.SEED_PROPERTY_TYPES / seed._wanted_type). The two answer different
# questions and carry opposite costs:
#
#   The seed asks "is this worth paying to enrich?" and runs before anything
#   exists. Refusing an unrecognised type there costs one lead nobody had yet.
#
#   This asks "should an existing lead be archived?". Under an allowlist, any
#   spelling the list does not happen to contain is treated as commercial — and
#   addr.normalize drops punctuation rather than replacing it, so "Single-Family"
#   keys as "singlefamily" and matches no allowlist entry. A CSV import writing
#   that spelling would have had every one of its homes archived.
#
# So only types that are affirmatively not a serviceable home are listed, and
# anything unrecognised is kept. Note that multi-family (duplex, fourplex) is
# absent on purpose: it is a roof we sell to, which is also why state class B
# counts as residential above.
NON_RESIDENTIAL_PROPERTY_TYPES = frozenset({
    "land", "vacant land", "lot", "commercial", "industrial", "retail",
    "office", "warehouse", "mixed use", "agricultural", "institutional",
    "parking",
})
# Absent on purpose, beyond the multi-family note above: "Apartment". RentCast
# uses it for both a unit inside a building and the building itself, and the
# seed already declines to buy it (config.SEED_PROPERTY_TYPES). Archiving on an
# ambiguous label would contradict this module's own treatment of HCAD state
# class B as residential, and a duplex or fourplex is a roof we sell to.


def _type_looks_non_residential(property_type) -> bool:
    """True only when a type is *present* and affirmatively non-residential.

    A NULL type is not evidence of anything — on an HCAD-seeded account it is
    NULL on every row, since only RentCast ever writes this column, and treating
    that as commercial would archive the account's whole book.
    """
    if not SEED_PROPERTY_TYPES or "*" in SEED_PROPERTY_TYPES:
        return False                    # type filtering disabled account-wide
    key = normalize(str(property_type or ""))
    return bool(key) and key in NON_RESIDENTIAL_PROPERTY_TYPES


# ── The rule ─────────────────────────────────────────────────────────────────

def classify(row: dict) -> list[str]:
    """Every reason `row` looks non-residential, most decisive first.

    `row` is a mapping with the `properties` column names; missing keys are
    treated as unknown, never as evidence. An empty list means "looks like a
    home, or we cannot tell" — the two are deliberately not distinguished,
    because acting on the difference is what would delete real customers.
    """
    reasons: list[str] = []

    state_class = (row.get("state_class") or "").strip().upper()
    if state_class and state_class.startswith(COMMERCIAL_STATE_CLASS_PREFIXES):
        reasons.append("county_class")
    elif state_class and state_class.startswith(EXEMPT_STATE_CLASS_PREFIXES):
        reasons.append("county_exempt")

    if _owner_looks_commercial(row.get("owner_name")):
        reasons.append("commercial_owner")
    elif _owner_maybe_commercial(row.get("owner_name")):
        reasons.append("possible_commercial_owner")

    if _type_looks_non_residential(row.get("property_type")):
        reasons.append("non_residential_type")

    sqft = int(row.get("square_footage") or 0)
    if sqft >= NONRESIDENTIAL_MIN_SQFT:
        reasons.append("oversized_structure")
    elif sqft >= NONRESIDENTIAL_REVIEW_SQFT:
        # The band where the two populations overlap. Reported for a human, and
        # deliberately never archived: a 30,000 sqft parcel in 77024 is as
        # likely to be a trophy estate as a strip centre, and archiving the
        # estate deletes the best lead in the book.
        reasons.append("large_structure")

    # An address is required before its shape can say anything. `properties` is
    # not only the parcel table — it is also the contact book: address is
    # nullable (migration 0018) and four production paths create leads with no
    # address at all (inbound call, inbound SMS, public web intake, address-less
    # CSV contact import). addr.has_situs(None) is False, so testing it directly
    # flagged every one of those, and a single click on the archive endpoint
    # would have wiped an account's entire inbound book. A missing address is
    # unknown, not a zero house number.
    address = (row.get("address") or "").strip()
    if address and not has_situs(address):
        reasons.append("no_situs")

    # Vacant: no year and no structure — but, for the same reason, only for rows
    # that describe a parcel at all. An address-less contact has neither field
    # and is not vacant land.
    if address and not int(row.get("year_built") or 0) \
            and not int(row.get("square_footage") or 0):
        reasons.append("no_structure")

    return [r for r in ALL_REASONS if r in reasons]


def is_non_residential(row: dict) -> bool:
    """True when `row` carries at least one EXCLUDE-tier reason."""
    return any(REASON_TIERS[r] == EXCLUDE for r in classify(row))


# ── The same rule, in SQL ────────────────────────────────────────────────────
# Built by interpolation, so every fragment is either a module constant or a
# column name validated by addr.sql_normalize's identifier guard. Nothing here
# accepts user input.

def _q(prefix: str, column: str) -> str:
    """`prefix`-qualified column name, e.g. ("p.", "address") -> "p.address".

    The prefix is validated even though every caller passes a literal: not every
    reason below routes its column through addr.sql_normalize's identifier
    guard (the numeric ones interpolate directly), so this is the only thing
    standing between a future caller and injection. Same posture as
    backfill._guard_columns — a bad value must break loudly here.
    """
    if prefix and not _ALIAS.match(prefix):
        raise ValueError(f"Not a plain table alias: {prefix!r}")
    return f"{prefix}{column}"


def sql_reason(reason: str, prefix: str = "") -> str:
    """One reason as a **Postgres** boolean expression over the properties columns.

    `prefix` qualifies the table ("p." for a joined query). Raises for an unknown
    reason rather than silently producing FALSE — a typo must break loudly, the
    same posture as backfill._guard_columns.

    Postgres-only, and specifically because of `no_situs`: it delegates to
    addr.sql_has_situs, whose `!~` is an anchored *partial* match in Postgres but
    a *full* match in DuckDB. Run in DuckDB, that one expression reports
    has_situs = TRUE for "0 BARRYKNOLL LN 656" — the exact opposite of the Python
    rule. Every other reason is engine-portable and is parity-tested in DuckDB
    (tests/test_residential.py); `no_situs` is covered by the Python tests and by
    the fact that it is composed from addr.py rather than re-derived here. Do not
    "fix" a failing DuckDB comparison by loosening the Python rule.
    """
    if reason not in REASON_TIERS:
        raise ValueError(f"unknown reason: {reason!r}")

    address = _q(prefix, "address")
    owner = _q(prefix, "owner_name")
    ptype = _q(prefix, "property_type")
    sqft = _q(prefix, "square_footage")
    year = _q(prefix, "year_built")
    sclass = _q(prefix, "state_class")

    if reason == "county_class":
        classes = ", ".join(f"'{c}'" for c in COMMERCIAL_STATE_CLASS_PREFIXES)
        return f"(LEFT(UPPER(TRIM(COALESCE({sclass}, ''))), 1) IN ({classes}))"

    if reason == "county_exempt":
        classes = ", ".join(f"'{c}'" for c in EXEMPT_STATE_CLASS_PREFIXES)
        return f"(LEFT(UPPER(TRIM(COALESCE({sclass}, ''))), 1) IN ({classes}))"

    if reason == "commercial_owner":
        norm = sql_normalize(owner)
        # strpos rather than LIKE, deliberately. psycopg2 interpolates the query
        # string whenever parameters are bound, so a literal '%' in the SQL is
        # read as the start of a placeholder: LIKE '%city of%' dies with
        # "unsupported format character 'c'". Escaping to '%%' would then be
        # wrong in the DuckDB parity test, which binds nothing. strpos has no
        # metacharacter at all, and both engines implement it identically.
        phrases = " OR ".join(
            f"strpos(' ' || {norm} || ' ', ' {p} ') > 0"
            for p in COMMERCIAL_OWNER_PHRASES
        )
        # A whole-word test: pad both sides with spaces and look for the padded
        # token, so "mallory" cannot satisfy "mall". string_to_array + && would
        # read better but DuckDB has no `&&` for arrays, and this expression is
        # parity-tested there.
        words = " OR ".join(
            f"strpos(' ' || {norm} || ' ', ' {t} ') > 0"
            for t in sorted(COMMERCIAL_OWNER_TOKENS)
        )
        return f"(({phrases}) OR ({words}))"

    if reason == "possible_commercial_owner":
        norm = sql_normalize(owner)
        maybe = " OR ".join(
            f"strpos(' ' || {norm} || ' ', ' {t} ') > 0"
            for t in sorted(AMBIGUOUS_OWNER_TOKENS)
        )
        # `elif` in classify(), so the two reasons stay mutually exclusive and
        # the audit's per-reason counts do not double-count one owner name.
        return f"(({maybe}) AND NOT {sql_reason('commercial_owner', prefix)})"

    if reason == "non_residential_type":
        if not SEED_PROPERTY_TYPES or "*" in SEED_PROPERTY_TYPES:
            return "(FALSE)"
        keys = ", ".join(f"'{k}'" for k in sorted(NON_RESIDENTIAL_PROPERTY_TYPES))
        return f"({sql_normalize(ptype)} IN ({keys}))"

    if reason == "oversized_structure":
        return f"(COALESCE({sqft}, 0) >= {int(NONRESIDENTIAL_MIN_SQFT)})"

    if reason == "large_structure":
        return (f"(COALESCE({sqft}, 0) >= {int(NONRESIDENTIAL_REVIEW_SQFT)}"
                f" AND COALESCE({sqft}, 0) < {int(NONRESIDENTIAL_MIN_SQFT)})")

    # Both parcel-shape reasons require an address to exist. `properties` is
    # also the contact book — address is nullable and inbound call/SMS/web-form
    # leads carry none — and sql_has_situs is FALSE for NULL, so without this
    # guard every address-less lead in the account was flagged EXCLUDE.
    present = f"({address} IS NOT NULL AND TRIM({address}) <> '')"

    if reason == "no_situs":
        return f"({present} AND NOT {sql_has_situs(address)})"

    if reason == "no_structure":
        return (f"({present} AND COALESCE({year}, 0) = 0"
                f" AND COALESCE({sqft}, 0) = 0)")

    raise AssertionError(f"unhandled reason: {reason}")   # pragma: no cover


def sql_non_residential(prefix: str = "", *, tier: str = EXCLUDE) -> str:
    """Postgres boolean: does this row carry any reason at `tier`?

    `tier=EXCLUDE` is what the seed filter and the bulk archive use. Pass
    `tier=None` for "any reason at all", which is what the audit counts.
    """
    if tier is None:
        reasons = ALL_REASONS
    else:
        reasons = [r for r, t in REASON_TIERS.items() if t == tier]
    if not reasons:
        return "(FALSE)"
    return "(" + " OR ".join(sql_reason(r, prefix) for r in reasons) + ")"
