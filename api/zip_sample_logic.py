"""Pure helpers for the public ZIP-sample teaser (api/routes/zip_sample.py).

The widget's whole trust contract is "real data, but not the product": show
enough of a property to prove the scoring is real (street, grade, why) while
holding back what people pay for (exact address, owner, contact info). These
helpers are dependency-free — see tests/test_zip_sample.py.
"""
import re

_LEADING_NUMBER = re.compile(r"^(\d+)(\s+.*)$")


def mask_address(address: str | None) -> str:
    """Partially hide a street address: '1842 Westheimer Rd' → '18XX Westheimer Rd'.

    Keeps the leading half of the house number (minimum one digit shown, at
    least one masked) so the street context is convincing but the parcel isn't
    identifiable. Addresses with no leading house number get every digit run
    masked; digit-free strings pass through untouched.
    """
    text = (address or "").strip()
    if not text:
        return ""
    match = _LEADING_NUMBER.match(text)
    if match:
        number, rest = match.groups()
        # Show the leading half, mask the rest (a lone digit masks entirely) —
        # always at least one X, so the parcel is never recoverable.
        keep = len(number) // 2
        return number[:keep] + "X" * (len(number) - keep) + rest
    return re.sub(r"\d", "X", text)


def teaser_rank_key(row: dict, score: float) -> tuple:
    """Sort key for the masked teaser sample: benchmarked rows first.

    The neighborhood benchmark is a weighted scoring signal, and an
    unbenchmarked row scores 0 on it — so a freshly seeded ZIP whose rows have
    no benchmark yet (no square footage, no value, not geocoded, or the
    recompute hasn't reached them) ranks its whole sample as if every home were
    at or below its block median, and the A/B leads it does have disappear from
    the teaser.

    Two tiers, highest first:
      1. Rows WITH a benchmark, by their re-ranked score — the honest ranking,
         unchanged from before.
      2. Rows WITHOUT one, by the stored `lead_score` — a presentation fallback
         so the widget shows this ZIP's best leads instead of looking empty.

    Deliberately NOT a fix to the numbers: no benchmark is invented for an
    unbenchmarked row, and it never outranks a benchmarked one. Sorting is
    descending, so a missing `lead_score` sorts last within its tier.
    """
    benchmarked = row.get("neighborhood_value_pctile") is not None
    if benchmarked:
        return (1, float(score))
    try:
        fallback = float(row.get("lead_score") or 0.0)
    except (TypeError, ValueError):
        fallback = 0.0
    return (0, fallback)


def value_label(estimated_value) -> str:
    """Rounded, approximate home value for the teaser ('~$480K', '~$1.2M').

    Deliberately imprecise — precision is a paid feature, and county values
    are estimates anyway. Empty string when the value is missing/unusable.
    """
    try:
        value = float(estimated_value)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value >= 1_000_000:
        return f"~${value / 1_000_000:.1f}M".replace(".0M", "M")
    return f"~${round(value / 5000) * 5}K"
