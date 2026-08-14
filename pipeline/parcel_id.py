"""
Parcel identity — the one rule for assessor parcel numbers (APNs).

The same parcel is identified as `acct` in HCAD ("0660640130020") and as
`assessorID` by RentCast (which may style it "066-064-013-0020" or drop the
leading zeros). This module is the single place that decides whether two such
strings name the same parcel, in the same spirit as pipeline/addr.py for
addresses. Pure and stdlib-only so it can be unit-tested without a DB.

Parcel numbers are never a SQL join key ACROSS VENDORS — a RentCast assessorID
is only ever compared to an HCAD acct through ``same_parcel`` in Python,
because vendors disagree on padding. Within HCAD's own data there is now one
sanctioned equality join: parcels.parcel_apn = hcad_parcel_centroids.acct
(pipeline/parcels.py::fill_coords_from_centroids), where both sides are stored
pre-normalized by ``sql_normalize_apn`` below — the same rule, one expression,
so byte-compatibility holds by construction and is additionally parity-tested
against ``normalize_apn`` in a real DuckDB (tests/test_parcel_id.py).

``normalize_apn`` is the storage form: punctuation stripped, uppercased,
leading zeros KEPT (HCAD accounts are conventionally 13-digit zero-padded and
operators recognize them that way). ``same_parcel`` is the comparison: it
additionally ignores leading zeros, because vendors disagree on padding.
"""
import re

# A bare column, or one qualified by a table alias — same guard as
# pipeline/addr.py::sql_normalize for expressions built by interpolation.
_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def normalize_apn(value) -> str | None:
    """Canonical stored form of an assessor parcel number.

    Keeps alphanumerics only, uppercased. Returns None for anything that
    cannot identify a parcel: empty/junk input, or an all-zero placeholder —
    two different properties both carrying a zero-filled APN must never be
    treated as the same parcel.
    """
    if value is None:
        return None
    text = "".join(ch for ch in str(value) if ch.isalnum()).upper()
    if not text or text.strip("0") == "":
        return None
    return text


def sql_normalize_apn(column: str) -> str:
    """``normalize_apn()`` as a SQL expression over `column`, for Postgres and DuckDB.

    This one expression writes BOTH sides of the centroid fill join:
    parcels.parcel_apn (pipeline/parcels.py::ensure_from_hcad) and
    hcad_parcel_centroids.acct (tools/load_parcel_centroids.py). Producing the
    two stored forms from the same rule is what lets the join be plain equality.
    tests/test_parcel_id.py runs the expression in a real DuckDB and compares
    row-for-row with ``normalize_apn`` — keep that test working rather than
    hand-copying this text.

    The all-zero test is TRANSLATE(x, '0', '') = '' rather than the more
    natural BTRIM(x, '0') = '' because DuckDB's btrim has no character-set
    form and one expression must serve both engines; the two are equivalent
    for an equals-empty check. Scope is ASCII — real APNs are — where Python's
    ``str.isalnum`` and SQL's [a-zA-Z0-9] agree.

    Callers interpolate the result into a statement. `column` is validated as a
    plain identifier, the same guard sql_normalize/pipeline/db.py use.
    """
    if not _SQL_IDENT.match(column or ""):
        raise ValueError(f"Not a plain SQL identifier: {column!r}")
    clean = f"REGEXP_REPLACE({column}, '[^a-zA-Z0-9]', '', 'g')"
    return (f"CASE WHEN {column} IS NULL OR TRANSLATE({clean}, '0', '') = '' "
            f"THEN NULL ELSE UPPER({clean}) END")


def same_parcel(left, right) -> bool:
    """True when two APN strings identify the same parcel.

    Case, punctuation, and leading-zero padding are stylistic; everything else
    is identity. Missing/junk on either side is False — absence of an
    identifier is not evidence of a match (mirrors same_address's empty-input
    rule).
    """
    a, b = normalize_apn(left), normalize_apn(right)
    if not a or not b:
        return False
    return a.lstrip("0") == b.lstrip("0")
