"""
Shared address normalization — single source of truth for matching the same
property across sources (HCAD, RentCast).

Enrichment steps key their upserts off the address already stored on the row,
so the critical requirement is that any code comparing addresses uses the SAME
normalization. This module is that one implementation; hcad_store and any future
matcher import `normalize` from here rather than rolling their own.
"""
import re


def normalize(address: str) -> str:
    """Lowercase, drop punctuation (keep spaces), collapse whitespace.

    Byte-compatible with the original hcad_store.normalize so existing HCAD
    address matching is unchanged.
    """
    if not address:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", address.lower())).strip()
