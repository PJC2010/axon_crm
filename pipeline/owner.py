"""
Junk owner-name guard — single source of truth for placeholder detection.

County assessor rolls carry placeholder owner names on parcels whose owner is
unrecorded or masked: HCAD stamps these "CURRENT OWNER" (423 of ~20k parcels in
ZIP 77396 alone, plus variants like "CURRENT PROPERTY OWNER"). A placeholder is
worse than a NULL everywhere downstream:

  * `owner_name` is in SOURCE_FIELDS["rentcast"], so only a NULL makes the row
    eligible for the paid RentCast fill — a stored placeholder blocks the gap
    from ever being filled.
  * The skip-trace step (pipeline/contact.py) sends owner_name to a paid
    provider; "CURRENT OWNER" parses as a plausible person and bills two
    lookups that can never match anyone.

So placeholders must become NULL at ingestion. Like pipeline/addr.py, the one
rule lives here in two byte-compatible forms:

  clean_owner_name()      Python: None for junk/empty, the trimmed name otherwise.
  sql_clean_owner_name()  The same rule as a SQL expression (DuckDB + Postgres),
                          for queries that ship owner_name out of the database
                          (hcad_store) or move it entirely server-side
                          (parcels.ensure_from_hcad).

Membership is tested on the *whole* normalized name, never on substrings — a
real owner named "OWENS CURRENT" or a business like "OWNER FINANCE LLC" must
pass. Err toward keeping: a false positive throws away a name we could have
skip-traced; a false negative just wastes what the guard exists to save.
"""
from pipeline.addr import normalize, sql_normalize

# Placeholder names as they look after addr.normalize() (lowercase, punctuation
# dropped, whitespace collapsed) — so "N/A" matches as "na". Full-string matches
# only; add here when a new placeholder shows up in an assessor roll.
JUNK_OWNER_NAMES = frozenset({
    "current owner",
    "current property owner",
    "owner current",
    "property owner",
    "owner of record",
    "current resident",
    "resident",
    "current occupant",
    "occupant",
    "homeowner",
    "home owner",
    "owner",
    "taxpayer",
    "unknown",
    "unknown owner",
    "owner unknown",
    "not available",
    "na",
    "none",
    "null",
    "confidential",
    "withheld",
    "name withheld",
})


def is_junk_owner_name(name) -> bool:
    """True when the whole name is a known placeholder (or empty)."""
    if name is None:
        return True
    key = normalize(str(name))
    return not key or key in JUNK_OWNER_NAMES


def clean_owner_name(name) -> str | None:
    """None for empty/placeholder names, the trimmed original otherwise.

    Casing and punctuation of a real name are preserved — this cleans junk, it
    does not reformat.
    """
    if name is None:
        return None
    text = str(name).strip()
    if not text or normalize(text) in JUNK_OWNER_NAMES:
        return None
    return text


def sql_clean_owner_name(column: str) -> str:
    """`clean_owner_name()` as a SQL expression over `column`.

    Serves both DuckDB and Postgres, exactly like addr.sql_normalize (whose
    expression this builds on, so the two rules can never disagree on what
    "the normalized name" is). `column` is validated as a plain identifier by
    sql_normalize; the junk list is module-constant, never user input.
    """
    junk = ", ".join(f"'{v}'" for v in sorted(JUNK_OWNER_NAMES))
    return (
        f"CASE WHEN {sql_normalize(column)} IN ({junk}) "
        f"THEN NULL ELSE NULLIF(TRIM({column}), '') END"
    )
