"""
Equity estimation — replaces the old flat `value * 0.6` proxy.

Pure functions (no DB / no network) so they're unit-testable like scoring.
Estimation, best source first:
  1. value - outstanding mortgage balance     (when a source supplies a balance)
  2. value - amortized remaining principal     (from last sale price + years held)
  3. value * EQUITY_FALLBACK_PCT               (configurable fallback)
"""
from datetime import date

from config import EQUITY_FALLBACK_PCT

# Assumptions for the amortization fallback when no live mortgage balance exists.
_ASSUMED_RATE = 0.06        # annual interest
_ASSUMED_TERM_YEARS = 30
_ASSUMED_LTV = 0.8          # buyers typically finance ~80% at purchase


def _years_since(sale_date) -> float | None:
    """Whole/fractional years between sale_date and today. Accepts date or ISO str."""
    if sale_date is None:
        return None
    if isinstance(sale_date, str):
        try:
            sale_date = date.fromisoformat(sale_date[:10])
        except ValueError:
            return None
    if not isinstance(sale_date, date):
        return None
    days = (date.today() - sale_date).days
    return days / 365.25 if days >= 0 else None


def _remaining_principal(orig_loan: float, years_elapsed: float) -> float:
    """Standard amortization: remaining balance on a fixed-rate loan."""
    n = _ASSUMED_TERM_YEARS * 12
    p = min(int(years_elapsed * 12), n)
    r = _ASSUMED_RATE / 12
    if r == 0:
        return orig_loan * (1 - p / n)
    factor = (1 + r)
    bal = orig_loan * (factor ** n - factor ** p) / (factor ** n - 1)
    return max(bal, 0.0)


def estimate_equity(value, last_sale_price=None, last_sale_date=None,
                    mortgage_balance=None, return_source: bool = False):
    """Best-available equity estimate in whole dollars, or None if value is unknown.

    With return_source=True returns (equity, source) where source is "balance",
    "amortized", or "fallback" — the scorer uses it to down-weight the flat
    fallback, which proxies home value rather than measuring equity.
    """
    result = _estimate(value, last_sale_price, last_sale_date, mortgage_balance)
    return result if return_source else result[0]


def _estimate(value, last_sale_price, last_sale_date, mortgage_balance):
    if not value:
        return None, None
    value = float(value)

    # 1. Known mortgage balance — most accurate.
    if mortgage_balance is not None:
        return max(int(value - float(mortgage_balance)), 0), "balance"

    # 2. Amortize from the original loan implied by the last sale.
    years = _years_since(last_sale_date)
    if last_sale_price and years is not None:
        orig_loan = float(last_sale_price) * _ASSUMED_LTV
        remaining = _remaining_principal(orig_loan, years)
        return max(int(value - remaining), 0), "amortized"

    # 3. Flat fallback.
    return max(int(value * EQUITY_FALLBACK_PCT), 0), "fallback"
