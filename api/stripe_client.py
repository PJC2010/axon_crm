"""Stripe Connect helpers.

Axon is the Connect *platform*; each owner is an Express *connected account*.
Invoices are paid via Stripe Checkout Sessions created as **direct charges on
the connected account** (the `stripe_account=` request option), with an
`application_fee_amount` routed to the Axon platform balance.

All functions here are thin wrappers so routes/webhooks stay readable and the
`stripe_account=` header usage is centralized.
"""
from typing import Optional

import stripe

from config import (
    STRIPE_SECRET_KEY,
    STRIPE_PLATFORM_FEE_PCT,
    PUBLIC_APP_URL,
)

stripe.api_key = STRIPE_SECRET_KEY


def is_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def platform_fee_cents(total: float) -> int:
    """Application fee Axon collects on a payment, in integer cents."""
    return round(total * 100 * STRIPE_PLATFORM_FEE_PCT)


# ── Connect onboarding ─────────────────────────────────────────────────────────

def create_express_account(email: Optional[str] = None) -> str:
    """Create an Express connected account; return its acct_ id."""
    acct = stripe.Account.create(
        type="express",
        email=email or None,
        capabilities={"card_payments": {"requested": True}, "transfers": {"requested": True}},
    )
    return acct.id


def create_account_link(account_id: str) -> str:
    """Hosted onboarding URL. Both refresh/return land back in app settings."""
    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=f"{PUBLIC_APP_URL}/settings?stripe=refresh",
        return_url=f"{PUBLIC_APP_URL}/settings?stripe=return",
        type="account_onboarding",
    )
    return link.url


def retrieve_account(account_id: str) -> dict:
    acct = stripe.Account.retrieve(account_id)
    return {
        "charges_enabled": bool(acct.get("charges_enabled")),
        "payouts_enabled": bool(acct.get("payouts_enabled")),
        "details_submitted": bool(acct.get("details_submitted")),
    }


# ── Checkout ───────────────────────────────────────────────────────────────────

def create_checkout_session_for_invoice(
    *,
    account_id: str,
    invoice_id: int,
    invoice_number: str,
    amount_due: float,
    pay_token: str,
    client_email: Optional[str] = None,
) -> stripe.checkout.Session:
    """Create a Checkout Session as a direct charge on the connected account.

    A single line item for the outstanding balance keeps the fee math simple;
    the itemized breakdown lives on Axon's own pay page / invoice.
    """
    amount_cents = round(amount_due * 100)
    fee_cents = round(amount_cents * STRIPE_PLATFORM_FEE_PCT)
    success_url = f"{PUBLIC_APP_URL}/pay/{pay_token}?paid=1"
    cancel_url = f"{PUBLIC_APP_URL}/pay/{pay_token}"

    return stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Invoice {invoice_number}"},
                "unit_amount": amount_cents,
            },
            "quantity": 1,
        }],
        payment_intent_data={"application_fee_amount": fee_cents},
        client_reference_id=str(invoice_id),
        customer_email=client_email or None,
        success_url=success_url,
        cancel_url=cancel_url,
        # Direct charge on the connected account:
        stripe_account=account_id,
        idempotency_key=f"checkout-inv-{invoice_id}-{amount_cents}",
    )
