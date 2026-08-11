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


# ── Comparing two owner names ────────────────────────────────────────────────
# HCAD writes owner names LAST-FIRST ("CAPUCHINA LIZETTE", "LANGLEY DONNA M");
# RentCast returns them FIRST-LAST ("Lizette Capuchina"). reconcile compared
# them with a plain case/whitespace fold, so every such pair read as two sources
# disagreeing about who owns the house — 21 of 24 owner names in one 25-property
# sweep of ZIP 77007. That buries the real findings the discrepancy report
# exists to surface, which is the same reason location and derived fields are
# excluded from it.
#
# Like addr.same_address, this errs toward "same": a false positive here hides a
# genuine ownership change from review, but a false negative floods the report
# and trains an operator to ignore it. owner_name is fill_only either way, so
# the stored county value is never overwritten on the strength of this call.

# Dropped before comparing — they carry no identity and the two sources differ
# freely on whether to include them.
_NAME_NOISE = {
    "MR", "MRS", "MS", "DR", "REV",              # honorifics
    "JR", "SR", "II", "III", "IV", "V",          # generational suffixes
    "ET", "AL", "ETAL", "ETUX", "ETVIR",         # "and others/wife/husband"
    "AND", "THE", "OF",
}


def name_tokens(name) -> frozenset[str]:
    """Significant, order-independent word tokens of an owner name.

    Uppercased, punctuation dropped, honorifics/suffixes/joiners removed, and
    single letters (middle initials) discarded — sources disagree on all of
    those without disagreeing about the owner.
    """
    if not name:
        return frozenset()
    words = normalize(str(name)).upper().split()
    return frozenset(w for w in words
                     if len(w) > 1 and w not in _NAME_NOISE)


def same_owner(a, b) -> bool:
    """True when two owner strings plausibly name the same party.

    Order-independent, because the two sources order names oppositely. Two
    shared significant tokens (a surname and a given name) are treated as the
    same party, which tolerates a middle name, a suffix, or a second owner
    present on only one side — "MADDUX DOUGLAS H JR & LISA" and
    "Douglas Maddux" are the same household. A single shared token is not
    enough: "SMITH JOHN" and "SMITH JANE" are different people.
    """
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False           # nothing to compare — do not claim a match
    if ta == tb:
        return True
    shared = ta & tb
    if len(shared) >= 2:
        return True
    # A one-token name (a mononym, or a business reduced to one word) can only
    # ever share one token, so require that its whole set be contained.
    if shared and (len(ta) == 1 or len(tb) == 1):
        return True
    return False
