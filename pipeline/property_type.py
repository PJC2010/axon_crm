"""HCAD state class → the CRM's `property_type` vocabulary.

`properties.property_type` is written ONLY by RentCast (config.SOURCE_FIELDS),
so on an HCAD-seeded account it is NULL on every row — the gap migration 0072
was written around. The county has always known the answer: `state_class` is
the Texas Comptroller State Category Code, and HCAD publishes the decode table
for it (tools/build_hcad_duckdb.py loads it as `state_class_codes`). This turns
that code into the vocabulary the rest of the app already speaks.

Two rules govern what may live in the table below, and both are load-bearing.

**Only dwellings map. Everything else returns None.**  It is tempting to map
F1 → "Commercial" and C1 → "Land" and let the classifier take it from there,
but `non_residential_type` is an EXCLUDE-tier reason (pipeline/residential.py)
— archivable in bulk — and `county_class` ALREADY excludes F/J/L/S by reading
`state_class` directly. A non-residential label here would add a second, weaker
path to the same archive decision: one that launders a county code into a
vendor-vocabulary string and then denylist-matches it, so the audit trail says
"property type is not residential" where it could have said "the county
classifies this parcel as non-residential". This module answers one question —
*what kind of dwelling is this?* — and says nothing when the answer is "not a
dwelling". It can therefore never archive a row that signal 1 was not already
archiving.

**The vocabulary is RentCast's, not HCAD's.**  Writing the county's own label
("Real, Residential, Single-Family") would fail `seed._wanted_type`'s allowlist
(config.SEED_PROPERTY_TYPES) and read as a foreign spelling everywhere the
column surfaces. Every value below is one the app already handles, and none of
them normalizes into residential.NON_RESIDENTIAL_PROPERTY_TYPES — asserted by
tests/test_property_type.py, so a future edit here cannot silently make the
cleanup sweep archive an account's homes.

Filling this column is also a cost win: `property_type` is a RentCast
SOURCE_FIELDS trigger, so a row whose type the county already supplied is one
fewer genuine gap to buy a paid lookup for.
"""
import re

# A bare column, or one qualified by a table alias. Same guard as
# pipeline/parcel_id.py::_SQL_IDENT and pipeline/addr.py — validate, never quote.
_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

# Every HCAD state class that names a dwelling, from the county's own decode
# table (desc_r_01_state_class.txt). Codes absent here are deliberate:
#
#   A3  Auxiliary Buildings — a shed or detached garage ON a residential
#       parcel. The county files it dept=A1, so the rollup calls it
#       residential, but it is not a *type of home* and every one of the
#       10,972 in Harris County carries bld_ar = 0. Naming it would put a
#       type on a row that has no dwelling to describe.
#   Z0  Condo - Without Improvements — vacant, dept=C1. `no_structure`
#       (REVIEW tier) is the right place for it, not a type.
#   C*, F*, J*, L*, S*, X*, D*, G*, O*  Not dwellings. See the module
#       docstring: silence here, exclusion in pipeline/residential.py.
DWELLING_BY_STATE_CLASS: dict[str, str] = {
    "A1": "Single Family",
    # "Mobile Homes" (A2, on owned land) and "Personal Prop. Mobile Home" (M3,
    # in a park on a rented lot) differ in how title is held, not in what
    # stands there. The CRM sells to the roof, so both are Manufactured.
    "A2": "Manufactured",
    "M3": "Manufactured",
    # "1/2 Duplex" is one separately-owned half of a two-family structure. The
    # county's word is Duplex and that is what a crew quoting the roof will
    # find, so it keeps the county's word rather than being flattened into
    # Single Family.
    "A4": "Duplex",
    "B1": "Multi-Family",
    "B2": "Duplex",
    "B3": "Triplex",
    "B4": "Fourplex",
    # "Farm & Ranch Improved" — a house on acreage. `E` is residential in
    # pipeline/residential.py's allowlist for the same reason.
    "E1": "Single Family",
    # The Z family is condominium, invisible to an A/B/E/M prefix rule. The
    # county's own `dept` rollup files every improved one of these as A1, and
    # its own wording splits them: Z2/Z3 say Townhouse, the rest say Condo.
    "Z1": "Condo",
    "Z2": "Townhouse",
    "Z3": "Townhouse",
    "Z4": "Condo",
    "Z5": "Condo",
}


def from_state_class(state_class) -> str | None:
    """The dwelling type an HCAD state class names, or None if it names none.

    None is "no opinion", never "not a home" — it is what an unrecognised code,
    a NULL, and an affirmatively non-residential class all return, because the
    caller's only use for the answer is filling a NULL column.
    """
    if state_class is None:
        return None
    return DWELLING_BY_STATE_CLASS.get(str(state_class).strip().upper())


def sql_from_state_class(column: str) -> str:
    """``from_state_class()`` as a SQL expression, for Postgres and DuckDB.

    pipeline/parcels.py::ensure_from_hcad fills the shared cache with one
    INSERT … SELECT and never sees a Python row, so the rule has to exist in
    both languages — the same Python/SQL pair pipeline/addr.py and
    pipeline/parcel_id.py keep. tests/test_property_type.py runs this
    expression in a real DuckDB and compares code-for-code against
    ``from_state_class``; keep that test working rather than hand-editing one
    side of the pair.

    Callers interpolate the result into a statement, so `column` is validated
    as a plain identifier. The keys and values are code-defined and asserted
    quote-free, which is what makes the interpolation below safe — the same
    posture as pipeline/db.py's ALL_COLS allowlist.
    """
    if not _SQL_IDENT.match(column or ""):
        raise ValueError(f"Not a plain SQL identifier: {column!r}")
    whens = []
    for code, label in sorted(DWELLING_BY_STATE_CLASS.items()):
        if "'" in code or "'" in label:  # pragma: no cover - guarded by tests
            raise ValueError(f"Quote in state-class mapping: {code!r} -> {label!r}")
        whens.append(f"WHEN '{code}' THEN '{label}'")
    return f"CASE UPPER(TRIM({column})) {' '.join(whens)} ELSE NULL END"


# ── Seeding: which dwelling types a deployment actually wants ────────────────
# A SEPARATE QUESTION from pipeline/residential.py, and the separation is the
# point. That module asks "is this a home?" — a correctness rule, whose EXCLUDE
# tier is structurally impossible for a dwelling and may be bulk-archived. This
# asks "is this a home WE SELL TO?", which is a business preference: a condo is
# unambiguously a home, and an account working HOA or investor angles may want
# every one of them. Folding "condo" into residential.py's EXCLUDE tier would
# corrupt a load-bearing correctness rule with a per-deployment opinion, so the
# allowlist lives here and is read only at seed time.
#
# The allowlist is config.SEED_PROPERTY_TYPES — the same knob that has always
# governed the RentCast seed (pipeline/seed.py::_wanted_type), so one setting
# now covers both seed paths rather than two overlapping ones.

# A property-type label safe to interpolate as a SQL literal. This allowlist IS
# the injection guard, the same posture as pipeline/db.py's ALL_COLS check: the
# values come from an env var, and psycopg2 binds %s positionally by statement
# text order, so seed_account's filters are literal SQL by design (a bind param
# added there would silently shift every other one).
_SQL_TYPE_LITERAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /&.+-]*$")


def sql_type_allowlist(column: str, allowed) -> str:
    """A seed filter keeping only `allowed` types, or "" for "no filter".

    Returns "" when the allowlist is empty or contains "*", matching
    ``seed._wanted_type``'s treatment of the same config value.

    **A NULL type is kept.** That mirrors ``_wanted_type``'s documented rule
    ("a record with no propertyType is kept — we have no grounds to drop it"),
    and here it is load-bearing in a second way: property_type is derived from
    `state_class`, so it is NULL for every parcel outside a county whose mirror
    carries that column. Dropping NULLs would make a seed of such a ZIP return
    zero rows — silently, looking exactly like an empty ZIP. Non-dwellings that
    ride along on the NULL branch are the `residential_only` / `built_only`
    filters' job, not this one's.
    """
    if not _SQL_IDENT.match(column or ""):
        raise ValueError(f"Not a plain SQL identifier: {column!r}")
    types = [t.strip() for t in (allowed or []) if str(t).strip()]
    if not types or "*" in types:
        return ""
    for t in types:
        if not _SQL_TYPE_LITERAL.match(t):
            raise ValueError(f"Not a valid property-type label: {t!r}")
    joined = ", ".join(f"'{t}'" for t in sorted(set(types)))
    return f"({column} IS NULL OR {column} IN ({joined}))"
