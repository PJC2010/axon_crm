"""Tests for pipeline/equity.py — pure equity estimation (no DB/network)."""
from datetime import date

import config
from pipeline.equity import estimate_equity


def test_none_value_returns_none():
    assert estimate_equity(None) is None
    assert estimate_equity(0) is None


def test_known_mortgage_balance_is_used():
    # value - balance, regardless of sale data
    assert estimate_equity(400_000, mortgage_balance=150_000) == 250_000


def test_mortgage_balance_clamped_at_zero():
    assert estimate_equity(100_000, mortgage_balance=250_000) == 0


def test_amortization_from_recent_sale_is_low_equity():
    # Bought a year ago for 300k at 80% LTV — little principal paid down, so
    # equity is roughly the 20% down payment plus appreciation (value==price here).
    last_year = date.today().replace(year=date.today().year - 1)
    eq = estimate_equity(300_000, last_sale_price=300_000, last_sale_date=last_year)
    assert 0 < eq < 100_000   # well under the flat-60% fallback of 180k


def test_old_sale_has_more_equity_than_recent():
    old = date.today().replace(year=date.today().year - 20)
    recent = date.today().replace(year=date.today().year - 2)
    eq_old = estimate_equity(300_000, last_sale_price=200_000, last_sale_date=old)
    eq_recent = estimate_equity(300_000, last_sale_price=200_000, last_sale_date=recent)
    assert eq_old > eq_recent


def test_fallback_uses_configured_pct():
    expected = int(500_000 * config.EQUITY_FALLBACK_PCT)
    assert estimate_equity(500_000) == expected


def test_iso_string_sale_date_accepted():
    eq = estimate_equity(300_000, last_sale_price=250_000, last_sale_date="2010-06-01")
    assert isinstance(eq, int) and eq > 0


def test_future_sale_date_falls_back_gracefully():
    future = date.today().replace(year=date.today().year + 1).isoformat()
    # Negative "years held" is rejected → flat fallback, not a crash.
    assert estimate_equity(200_000, last_sale_price=200_000, last_sale_date=future) == \
        int(200_000 * config.EQUITY_FALLBACK_PCT)
