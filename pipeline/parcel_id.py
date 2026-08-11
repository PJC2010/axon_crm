"""
Parcel identity — the one rule for assessor parcel numbers (APNs).

The same parcel is identified as `acct` in HCAD ("0660640130020") and as
`assessorID` by RentCast (which may style it "066-064-013-0020" or drop the
leading zeros). This module is the single place that decides whether two such
strings name the same parcel, in the same spirit as pipeline/addr.py for
addresses. Pure and dependency-free so it can be unit-tested without a DB.

Unlike addresses, parcel numbers are never a SQL join key — every comparison
goes through ``same_parcel`` in Python — so there is no byte-compatible SQL
twin to keep in sync. The SQL that carries HCAD's acct into parcel_apn
(pipeline/parcels.py::ensure_from_hcad) applies the same cleanup for storage
consistency, but nothing correctness-critical rides on the two matching
byte-for-byte.

``normalize_apn`` is the storage form: punctuation stripped, uppercased,
leading zeros KEPT (HCAD accounts are conventionally 13-digit zero-padded and
operators recognize them that way). ``same_parcel`` is the comparison: it
additionally ignores leading zeros, because vendors disagree on padding.
"""


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
