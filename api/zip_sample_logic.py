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
