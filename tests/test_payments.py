"""
Tests for payment-automation logic that runs without a database.

Covers the platform-fee math (Axon's revenue share) and the provider-config
guards in api/notifications.py. DB-backed flows (webhook → invoice_payments →
_update_invoice_payment_state) are exercised manually via the Stripe CLI per the
plan's verification section.
"""
import importlib

import pytest

import config


def _reload_stripe_client():
    import api.stripe_client as sc
    return importlib.reload(sc)


def test_platform_fee_cents_default_2pct():
    sc = _reload_stripe_client()
    # 2% of $100.00 = $2.00 = 200 cents
    assert sc.platform_fee_cents(100.0) == 200
    assert sc.platform_fee_cents(0.0) == 0


def test_platform_fee_cents_rounds_to_nearest_cent():
    sc = _reload_stripe_client()
    # 2% of $10.10 = 20.2 cents -> rounds to 20
    assert sc.platform_fee_cents(10.10) == 20
    # 2% of $12.75 = 25.5 cents -> banker's/half rounding to 26 via round()
    assert sc.platform_fee_cents(12.75) in (25, 26)


def test_platform_fee_respects_configured_pct(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_PLATFORM_FEE_PCT", 0.05, raising=False)
    sc = _reload_stripe_client()
    assert sc.platform_fee_cents(100.0) == 500
    # restore module to default config for other tests
    monkeypatch.setattr(config, "STRIPE_PLATFORM_FEE_PCT", 0.02, raising=False)
    _reload_stripe_client()


def test_notifications_config_guards(monkeypatch):
    import api.notifications as notif
    importlib.reload(notif)
    # With empty creds (default in test env), both channels report unconfigured
    monkeypatch.setattr(notif, "RESEND_API_KEY", "", raising=False)
    monkeypatch.setattr(notif, "RESEND_FROM_EMAIL", "", raising=False)
    monkeypatch.setattr(notif, "TWILIO_ACCOUNT_SID", "", raising=False)
    assert notif.email_configured() is False
    assert notif.sms_configured() is False

    with pytest.raises(RuntimeError):
        notif.send_invoice_email(to_email="a@b.com", business_name="Biz",
                                 invoice_number="INV-1", amount_due=10.0, pay_url="http://x")
    with pytest.raises(RuntimeError):
        notif.send_invoice_sms(to_phone="+15555550123", business_name="Biz",
                               invoice_number="INV-1", amount_due=10.0, pay_url="http://x")
