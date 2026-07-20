"""
Tests for subscription billing (api/billing.py) that run without a database or
the real SDK — a fake `stripe` module is injected via sys.modules, mirroring
test_stripe_client.py.
"""
import sys
import types

import pytest

from api import billing as b
from api.entitlements import MODULE_KEYS, PLAN_CATALOG


# ── catalog consistency ───────────────────────────────────────────────────────

def test_pricing_catalog_matches_entitlements():
    # Every advertised plan must exist in the entitlements catalog (and vice
    # versa) so a checkout can never sell a plan gating can't resolve.
    assert set(b.PLAN_PRICING) == set(PLAN_CATALOG)
    for meta in b.PLAN_PRICING.values():
        assert meta["monthly_usd"] > 0
        assert meta["label"] and meta["blurb"]


def test_pro_grants_everything_but_marketing_starter_gets_scoring():
    # Positioning plan: marketing (Meta CSV insights) is granted by no named
    # plan (re-grantable per-account via overrides), and prospecting — the moat
    # — is in front of every tier, metered on lower tiers.
    assert PLAN_CATALOG["pro"] == set(MODULE_KEYS) - {"marketing"}
    assert PLAN_CATALOG["starter"] == {"prospecting"}
    for plan, granted in PLAN_CATALOG.items():
        assert "marketing" not in granted, plan
        assert "prospecting" in granted, plan


def test_scoring_limits_cover_every_plan():
    from api.entitlements import PLAN_SCORING_LIMITS
    assert set(PLAN_SCORING_LIMITS) == set(PLAN_CATALOG)
    assert PLAN_SCORING_LIMITS["pro"] is None            # unlimited
    assert PLAN_SCORING_LIMITS["starter"] == 25
    assert PLAN_SCORING_LIMITS["growth"] == 100


# ── price-id mapping ──────────────────────────────────────────────────────────

def _set_prices(monkeypatch, starter="", growth="", pro=""):
    monkeypatch.setattr(b, "STRIPE_PRICE_STARTER", starter, raising=False)
    monkeypatch.setattr(b, "STRIPE_PRICE_GROWTH", growth, raising=False)
    monkeypatch.setattr(b, "STRIPE_PRICE_PRO", pro, raising=False)


def test_price_mapping_roundtrip(monkeypatch):
    _set_prices(monkeypatch, starter="price_s", growth="price_g", pro="price_p")
    assert b.price_id_for_plan("growth") == "price_g"
    assert b.plan_for_price("price_p") == "pro"
    assert b.plan_for_price("price_unknown") is None
    assert b.plan_for_price(None) is None


def test_unconfigured_plans_drop_out(monkeypatch):
    _set_prices(monkeypatch, pro="price_p")   # only pro sellable
    assert b.price_id_for_plan("starter") is None
    assert b.plan_for_price("price_p") == "pro"


def test_billing_configured_requires_key_and_a_price(monkeypatch):
    monkeypatch.setattr(b, "STRIPE_SECRET_KEY", "", raising=False)
    _set_prices(monkeypatch, pro="price_p")
    assert b.billing_configured() is False    # no secret key
    monkeypatch.setattr(b, "STRIPE_SECRET_KEY", "sk_test_x", raising=False)
    assert b.billing_configured() is True
    _set_prices(monkeypatch)                   # key but no prices
    assert b.billing_configured() is False


# ── stripe calls (fake SDK) ───────────────────────────────────────────────────

def _fake_stripe(recorder: dict) -> types.ModuleType:
    fake = types.ModuleType("stripe")

    class CheckoutSession:
        @staticmethod
        def create(**kwargs):
            recorder["checkout"] = kwargs
            return {"id": "cs_sub_1", "url": "https://checkout.stripe.test/sub"}

    class PortalSession:
        @staticmethod
        def create(**kwargs):
            recorder["portal"] = kwargs
            return {"url": "https://billing.stripe.test/portal"}

    class Customer:
        @staticmethod
        def create(**kwargs):
            recorder["customer"] = kwargs
            return {"id": "cus_new"}

    fake.checkout = types.SimpleNamespace(Session=CheckoutSession)
    fake.billing_portal = types.SimpleNamespace(Session=PortalSession)
    fake.Customer = Customer
    return fake


def test_subscription_checkout_params(monkeypatch):
    monkeypatch.setattr(b, "STRIPE_SECRET_KEY", "sk_test_x", raising=False)
    rec = {}
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe(rec))

    url = b.create_subscription_checkout(
        customer_id="cus_7", price_id="price_p", account_id=3, plan_name="pro",
        success_url="https://x/settings?billing=success",
        cancel_url="https://x/settings?billing=cancelled",
    )
    assert url.startswith("https://")

    kw = rec["checkout"]
    assert kw["mode"] == "subscription"
    assert kw["customer"] == "cus_7"
    assert kw["line_items"] == [{"price": "price_p", "quantity": 1}]
    # account/plan metadata must ride BOTH the session and the subscription so
    # the webhook can resolve the tenant from either event shape.
    expected_meta = {"account_id": "3", "plan": "pro"}
    assert kw["metadata"] == expected_meta
    assert kw["subscription_data"]["metadata"] == expected_meta


def test_portal_session_params(monkeypatch):
    monkeypatch.setattr(b, "STRIPE_SECRET_KEY", "sk_test_x", raising=False)
    rec = {}
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe(rec))
    url = b.create_portal_session(customer_id="cus_7", return_url="https://x/settings")
    assert url.startswith("https://")
    assert rec["portal"] == {"customer": "cus_7", "return_url": "https://x/settings"}


def test_gates_raise_without_config(monkeypatch):
    monkeypatch.setattr(b, "STRIPE_SECRET_KEY", "", raising=False)
    with pytest.raises(RuntimeError):
        b.create_portal_session(customer_id="cus_7", return_url="r")
    monkeypatch.setattr(b, "STRIPE_BILLING_WEBHOOK_SECRET", "", raising=False)
    with pytest.raises(RuntimeError):
        b.construct_billing_webhook_event(b"{}", "sig")
