"""
Tests for the Stripe Connect client helpers (api/integrations/stripe/) that run
without a database or the real SDK — a fake `stripe` module is injected via
sys.modules, mirroring how test_invoice_send.py stubs provider config.
"""
import sys
import types

import pytest

from api.integrations.stripe import stripe_client as sc


def test_configured_gate(monkeypatch):
    monkeypatch.setattr(sc, "STRIPE_SECRET_KEY", "", raising=False)
    assert sc.stripe_configured() is False
    with pytest.raises(RuntimeError):
        sc.create_account_link("acct_1", refresh_url="r", return_url="t")
    monkeypatch.setattr(sc, "STRIPE_SECRET_KEY", "sk_test_x", raising=False)
    assert sc.stripe_configured() is True


def test_webhook_secret_gate(monkeypatch):
    monkeypatch.setattr(sc, "STRIPE_WEBHOOK_SECRET", "", raising=False)
    with pytest.raises(RuntimeError):
        sc.construct_webhook_event(b"{}", "sig")


def test_platform_fee_cents(monkeypatch):
    monkeypatch.setattr(sc, "STRIPE_PLATFORM_FEE_PCT", 2.0, raising=False)
    assert sc.platform_fee_cents(10000) == 200
    assert sc.platform_fee_cents(101) == 2       # round(2.02)
    monkeypatch.setattr(sc, "STRIPE_PLATFORM_FEE_PCT", 0.0, raising=False)
    assert sc.platform_fee_cents(10000) == 0
    # Stripe rejects a fee >= the amount; the helper caps below it.
    monkeypatch.setattr(sc, "STRIPE_PLATFORM_FEE_PCT", 100.0, raising=False)
    assert sc.platform_fee_cents(10000) == 9999


def _fake_stripe(recorder: dict) -> types.ModuleType:
    fake = types.ModuleType("stripe")

    class Session:
        @staticmethod
        def create(**kwargs):
            recorder["session"] = kwargs
            return {"id": "cs_test_1", "url": "https://checkout.stripe.test/pay"}

    class Account:
        @staticmethod
        def create(**kwargs):
            recorder["account"] = kwargs
            return {"id": "acct_new"}

        @staticmethod
        def retrieve(acct_id):
            recorder["retrieved"] = acct_id
            return {"charges_enabled": True, "payouts_enabled": False, "details_submitted": True}

    fake.checkout = types.SimpleNamespace(Session=Session)
    fake.Account = Account
    return fake


def test_create_checkout_session_params(monkeypatch):
    monkeypatch.setattr(sc, "STRIPE_SECRET_KEY", "sk_test_x", raising=False)
    rec = {}
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe(rec))
    meta = {"invoice_id": "7", "account_id": "3", "pay_token": "tok"}

    session = sc.create_checkout_session(
        stripe_account_id="acct_9", amount_cents=12345, fee_cents=247,
        invoice_number="INV-7", business_name="Biz",
        success_url="https://x/pay/tok?status=success",
        cancel_url="https://x/pay/tok?status=cancelled", metadata=meta,
    )
    assert session["url"].startswith("https://")

    kw = rec["session"]
    # Direct charge on the connected account with the platform fee + metadata
    # on both the session and the PaymentIntent.
    assert kw["stripe_account"] == "acct_9"
    assert kw["mode"] == "payment"
    assert kw["payment_intent_data"]["application_fee_amount"] == 247
    assert kw["payment_intent_data"]["metadata"] == meta
    assert kw["metadata"] == meta
    assert kw["line_items"][0]["price_data"]["unit_amount"] == 12345
    assert kw["line_items"][0]["price_data"]["currency"] == "usd"


def test_zero_fee_omits_application_fee(monkeypatch):
    monkeypatch.setattr(sc, "STRIPE_SECRET_KEY", "sk_test_x", raising=False)
    rec = {}
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe(rec))
    sc.create_checkout_session(
        stripe_account_id="acct_9", amount_cents=500, fee_cents=0,
        invoice_number="INV-8", business_name="Biz",
        success_url="s", cancel_url="c", metadata={},
    )
    assert "application_fee_amount" not in rec["session"]["payment_intent_data"]


def test_express_account_and_status(monkeypatch):
    monkeypatch.setattr(sc, "STRIPE_SECRET_KEY", "sk_test_x", raising=False)
    rec = {}
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe(rec))

    acct_id = sc.create_express_account(email="o@biz.com", business_name="Biz")
    assert acct_id == "acct_new"
    assert rec["account"]["type"] == "express"
    assert rec["account"]["capabilities"]["card_payments"] == {"requested": True}

    status = sc.fetch_account_status("acct_new")
    assert status == {"charges_enabled": True, "payouts_enabled": False, "details_submitted": True}
