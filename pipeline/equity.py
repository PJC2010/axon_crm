"""
Equity estimation — replaces the old flat `value * 0.6` proxy.

Pure functions (no DB / no network) so they're unit-testable like scoring.
Estimation, best source first:
  1. value - outstanding mortgage balance     (when a source supplies a balance)
  2. value - amortized remaining principal     (from last sale price + years held)
  3. value * EQUITY_FALLBACK_PCT               (configurable fallback)

Which basis produced a stored number matters to scoring: the flat fallback is a
home-value proxy, not measured equity, and the scorer scales its signal by
EQUITY_FALLBACK_SIGNAL_SCALE. That provenance used to live only in the scorer's
memory, so it applied on the one path where the scorer derived equity itself and
never on the HCAD / RentCast paths that persisted the identical number first —
the same house graded differently depending on which step got there first. Every
writer now stamps ``enrichment_flags[EQUITY_SOURCE_FLAG]`` and the scorer reads it
back through ``stored_equity_source``.
"""
from datetime import date

from config import EQUITY_FALLBACK_PCT

# enrichment_flags key carrying the basis of the stored estimated_equity.
EQUITY_SOURCE_FLAG = "equity_source"
BALANCE_SOURCE = "balance"
AMORTIZED_SOURCE = "amortized"
FALLBACK_SOURCE = "fallback"
# A vendor supplied a measured figure (the demographic append's
# valuation.equityPercent × our AVM). Not the flat proxy, so never haircut.
PROVIDER_SOURCE = "provider"

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
    return max(int(value * EQUITY_FALLBACK_PCT), 0), FALLBACK_SOURCE


def equity_source_for(value, last_sale_price=None, last_sale_date=None,
                      mortgage_balance=None) -> str | None:
    """The basis estimate_equity uses for these inputs, without the number.

    For writers that already hold the equity (pipeline/reconcile.py derives it
    through the same inputs) and only need to stamp its provenance.
    """
    return _estimate(value, last_sale_price, last_sale_date, mortgage_balance)[1]


def stored_equity_source(row: dict) -> str | None:
    """Provenance of the estimated_equity a property row carries, or None.

    Resolution order:
      1. the persisted ``enrichment_flags.equity_source`` stamp (every writer
         sets it: hcad_enrichment, the RentCast detail step, the backfill
         sweep, and the scorer's own backfill);
      2. the scorer's in-process hint ``estimated_equity_is_fallback`` for a
         row it derived equity for in this very run;
      3. re-derivation, for rows written before the stamp existed: the flat
         fallback is a deterministic function of estimated_value, so a stored
         equity that equals it (and nothing else — an amortized figure drifts
         with the calendar and a hand-entered one is arbitrary) is the fallback.
    Unknown provenance is reported as None and scored at full weight — the
    scorer never haircuts a number it cannot attribute.
    """
    flags = row.get("enrichment_flags")
    if isinstance(flags, dict):
        stamped = flags.get(EQUITY_SOURCE_FLAG)
        if stamped:
            return stamped
    if row.get("estimated_equity_is_fallback"):
        return FALLBACK_SOURCE
    equity = row.get("estimated_equity")
    if equity is None:
        return None
    derived, source = _estimate(row.get("estimated_value"), row.get("last_sale_price"),
                                row.get("last_sale_date"), None)
    if derived is None or source != FALLBACK_SOURCE:
        return None
    try:
        return FALLBACK_SOURCE if int(equity) == derived else None
    except (TypeError, ValueError):
        return None
