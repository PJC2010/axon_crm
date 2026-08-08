"""
Shared address normalization — single source of truth for matching the same
property across sources (HCAD, RentCast).

Enrichment steps key their upserts off the address already stored on the row,
so the critical requirement is that any code comparing addresses uses the SAME
normalization. This module is that one implementation; hcad_store and any future
matcher import from here rather than rolling their own.

Three things live here, for three different jobs:

  normalize()      Python: the canonical key. Used to look matches up.
  sql_normalize()  The same rule as a SQL expression, so a query that builds
                   match keys in the database produces keys this module's
                   lookups can actually find.
  same_address()   A deliberately looser test for "did the vendor answer about
                   the property we asked about?" — not a key, a sanity check.
"""
import re

# Everything that is not a lowercase letter, a digit, or a space is dropped
# (not replaced with a space): "st. charles" and "st charles" must land on the
# same key, and so must "main-st" and "mainst".
_DROP = re.compile(r"[^a-z0-9 ]")
_RUNS = re.compile(r"\s+")


def normalize(address: str) -> str:
    """Lowercase, drop punctuation (keep spaces), collapse whitespace.

    This is the match key. `sql_normalize` and `axon_normalize_address` (SQL,
    db/migrations/0065) must stay byte-compatible with it — a key built by one
    and looked up by another that disagrees fails silently, which is exactly the
    bug that made HCAD enrichment skip every address containing punctuation.
    """
    if not address:
        return ""
    return _RUNS.sub(" ", _DROP.sub("", address.lower())).strip()


# A bare column, or one qualified by a table alias. These expressions are built
# from hardcoded column names, never user input, but the check keeps it that way.
_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def sql_normalize(column: str) -> str:
    """`normalize()` as a SQL expression over `column`, for DuckDB and Postgres.

    Both read RE2/POSIX classes the same way here, and neither interprets the
    backslash in '\\s+' as a string escape (Postgres has
    standard_conforming_strings on), so one expression serves both.

    Callers interpolate the result into a SELECT list. `column` is validated as
    a plain identifier rather than quoted, the same guard pipeline/db.py uses for
    dynamic column references.
    """
    if not _SQL_IDENT.match(column or ""):
        raise ValueError(f"Not a plain SQL identifier: {column!r}")
    return (
        "TRIM(REGEXP_REPLACE(REGEXP_REPLACE("
        f"LOWER(COALESCE({column}, '')), '[^a-z0-9 ]', '', 'g'), '\\s+', ' ', 'g'))"
    )


# ── Verifying a vendor's answer ───────────────────────────────────────────────

# Folded so an abbreviation and its long form compare equal. Only forms that are
# unambiguous in a US street address — deliberately not a full USPS table, which
# would add failure modes without helping the check this backs.
_SUFFIXES = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr",
    "boulevard": "blvd", "lane": "ln", "court": "ct", "circle": "cir",
    "place": "pl", "trail": "trl", "parkway": "pkwy", "highway": "hwy",
    "terrace": "ter", "square": "sq", "loop": "lp", "way": "wy",
}
# Dropped entirely: they qualify a street rather than name it, and sources
# disagree on whether to include them ("123 W Main St" vs "123 Main St").
_NOISE = {
    "n", "s", "e", "w", "ne", "nw", "se", "sw",
    "north", "south", "east", "west",
    "st", "ave", "rd", "dr", "blvd", "ln", "ct", "cir", "pl", "trl", "pkwy",
    "hwy", "ter", "sq", "lp", "wy",
}


def same_address(requested: str, returned: str) -> bool:
    """True when two address strings plausibly describe the same street address.

    This gates whether a vendor's record is accepted, so it errs toward True: a
    false negative silently throws away data we already paid for. It rejects only
    what is clearly a different property —

      * a different house number ("123 Main St" vs "125 Main St"), or
      * no shared street-name word once suffixes and directionals are folded
        away ("123 Main St" vs "123 Oak St").

    Everything else passes, including a unit the other side omits, a spelled-out
    suffix, and a directional prefix present on only one side.
    """
    left, right = normalize(requested), normalize(returned)
    if not left or not right:
        return False        # nothing to check against — do not claim a match
    if left == right:
        return True

    left_num, left_words = _split(left)
    right_num, right_words = _split(right)

    # The house number is the one part of an address that is never stylistic.
    if left_num and right_num and left_num != right_num:
        return False
    # Two addresses sharing a number but naming different streets are different
    # properties. Require at least one street word in common.
    if left_words and right_words and not (left_words & right_words):
        return False
    return True


def _split(address: str) -> tuple[str | None, set[str]]:
    """Split a normalized address into (house number, significant street words)."""
    tokens = address.split()
    number = tokens[0] if tokens and tokens[0].isdigit() else None
    words = {_SUFFIXES.get(t, t) for t in tokens[1:]}
    return number, words - _NOISE
