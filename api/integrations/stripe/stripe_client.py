"""Stripe Connect Express client helpers.

Owners onboard Express connected accounts; customers pay via Checkout Sessions
created ON the connected account (direct charges: the owner is merchant of
record, pays Stripe fees, owns disputes) with Axon taking a platform fee via
``application_fee_amount``. Funds never touch an Axon-controlled account.

Fail-soft like api/notifications.py: ``stripe_configured()`` gates every call,
the SDK is imported lazily, and callers get a clear RuntimeError when the
platform key is missing.
"""
from config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PLATFORM_FEE_PCT


def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def _stripe():
    if not stripe_configured():
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY)")
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


def platform_fee_cents(amount_cents: int) -> int:
    """Axon's cut of a charge. Never meets or exceeds the amount itself
    (Stripe rejects application_fee_amount >= amount)."""
    fee = round(amount_cents * STRIPE_PLATFORM_FEE_PCT / 100)
    return max(0, min(fee, amount_cents - 1))


def create_express_account(*, email: str | None, business_name: str) -> str:
    """Create the owner's Express connected account; returns the acct_… id."""
    stripe = _stripe()
    account = stripe.Account.create(
        type="express",
        email=email or None,
        business_profile={"name": business_name},
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
    )
    return account["id"]


def create_account_link(stripe_account_id: str, *, refresh_url: str, return_url: str) -> str:
    """One-time hosted onboarding link for an Express account."""
    stripe = _stripe()
    link = stripe.AccountLink.create(
        account=stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link["url"]


def fetch_account_status(stripe_account_id: str) -> dict:
    stripe = _stripe()
    account = stripe.Account.retrieve(stripe_account_id)
    return {
        "charges_enabled": bool(account.get("charges_enabled")),
        "payouts_enabled": bool(account.get("payouts_enabled")),
        "details_submitted": bool(account.get("details_submitted")),
    }


def create_checkout_session(*, stripe_account_id: str, amount_cents: int, fee_cents: int,
                            invoice_number: str, business_name: str,
                            success_url: str, cancel_url: str, metadata: dict):
    """Checkout Session on the connected account (direct charge).

    ``metadata`` (invoice_id / account_id / pay_token) is stamped on both the
    session and the PaymentIntent so the webhook can resolve the invoice from
    either event shape.
    """
    stripe = _stripe()
    payment_intent_data = {"metadata": metadata}
    if fee_cents > 0:
        payment_intent_data["application_fee_amount"] = fee_cents
    return stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": amount_cents,
                "product_data": {"name": f"Invoice {invoice_number} — {business_name}"},
            },
            "quantity": 1,
        }],
        payment_intent_data=payment_intent_data,
        metadata=metadata,
        success_url=success_url,
        cancel_url=cancel_url,
        stripe_account=stripe_account_id,
    )


def expire_checkout_session(stripe_account_id: str, session_id: str) -> None:
    """Expire a still-open Checkout Session on the connected account.

    Raises if the session is already completed/expired — callers treat that as
    success (the goal is simply that no *second* payable link stays live).
    """
    stripe = _stripe()
    stripe.checkout.Session.expire(session_id, stripe_account=stripe_account_id)


def construct_webhook_event(payload: bytes, sig_header: str):
    """Verify the webhook signature and parse the event. Raises on a bad
    signature. STRIPE_WEBHOOK_SECRET must be the CONNECT endpoint's secret —
    direct charges emit events on the connected account."""
    if not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("Stripe webhook is not configured (STRIPE_WEBHOOK_SECRET)")
    import stripe
    return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
