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


def normalize_zip(raw) -> str:
    """Reduce a raw ZIP value to its canonical 5-digit form, or "" if absent.

    HCAD's site ZIP (`real_acct.site_addr_3`) is not guaranteed to be a clean
    5-digit code — many parcels carry a ZIP+4 ("77008-2317" / "770082317") or
    stray formatting. Storing that verbatim as `properties.zip` files a parcel
    under a ZIP that no 5-digit query (the public sample, coverage checks,
    enrichment) will ever match, so a valid Harris County ZIP looks uncovered.

    This collapses any such value to the first five digits: "77008-2317" and
    "770082317" both become "77008"; an already-clean "77008" is unchanged.
    """
    if raw is None:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    return digits[:5]
