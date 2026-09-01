"""Subscription billing for Axon plans (Stripe Billing).

How accounts pay for Axon itself — the missing half of the funnel the
prospective-user audit flagged. Distinct from Stripe Connect
(api/integrations/stripe/), where an account's customers pay that account's
invoices; both share the platform STRIPE_SECRET_KEY.

Fail-soft like the rest of the integrations: ``billing_configured()`` gates
every call, the SDK is imported lazily, and with no price ids configured the
billing endpoints 503 while plans stay admin-managed
(scripts/set_account_plan.py).

Plan **entitlements** stay in account_plans (api/entitlements.py is the single
source of truth); this module writes plan_name there when billing events land,
and keeps the subscription state behind it in account_billing.

``PLAN_PRICING`` is the advertised catalog — keep it in sync with
PLAN_CATALOG's module sets and the landing page's pricing section
(frontend/components/LandingContent.tsx).
"""
from psycopg2.extras import Json

from config import (
    STRIPE_SECRET_KEY, STRIPE_BILLING_WEBHOOK_SECRET,
    STRIPE_PRICE_STARTER, STRIPE_PRICE_GROWTH, STRIPE_PRICE_PRO,
)
from api.entitlements import _plan_defaults

# Advertised pricing (prospective-user audit §6.3). Monthly, USD, flat — the
# advertised price is the real price, no seat math. Annual pricing is a
# deliberate later decision (prove retention first); never require a contract.
PLAN_PRICING: dict[str, dict] = {
    "starter": {
        "label": "Starter",
        "monthly_usd": 49,
        "blurb": "Get organized — plus 25 scored, graded leads from your ZIPs every month.",
    },
    "growth": {
        "label": "Growth",
        "monthly_usd": 129,
        "blurb": "Run the back office: quotes, invoicing, automations — plus 100 scored leads a month.",
    },
    "pro": {
        "label": "Pro",
        "monthly_usd": 249,
        "blurb": "The lead machine: unlimited scored lists, storm signals, maps — plus everything in Growth.",
    },
}

# Trial/local statuses vs. Stripe subscription statuses that keep a paid plan's
# access. past_due keeps access as a grace period (Stripe retries the charge).
ACTIVE_STATUSES = ("trialing", "active", "past_due")


def _price_map() -> dict[str, str]:
    """plan name → configured Stripe price id (empty entries dropped)."""
    return {
        plan: price_id
        for plan, price_id in (
            ("starter", STRIPE_PRICE_STARTER),
            ("growth", STRIPE_PRICE_GROWTH),
            ("pro", STRIPE_PRICE_PRO),
        )
        if price_id
    }


def price_id_for_plan(plan_name: str) -> str | None:
    return _price_map().get(plan_name)


def plan_for_price(price_id: str | None) -> str | None:
    """Reverse lookup used by the subscription webhook (price → plan)."""
    if not price_id:
        return None
    for plan, configured in _price_map().items():
        if configured == price_id:
            return plan
    return None


def billing_configured() -> bool:
    """True when self-serve subscriptions can actually be sold.

    The webhook secret is part of "configured" on purpose: without it, Checkout
    would happily collect money while every entitlement-granting delivery 503s —
    the account stays `trialing` with no subscription id, which is exactly the
    state the daily trial-expiry tick downgrades to starter. A paying customer
    silently losing their plan is far worse than checkout refusing to open.
    """
    return (bool(STRIPE_SECRET_KEY) and bool(_price_map())
            and bool(STRIPE_BILLING_WEBHOOK_SECRET))


def _stripe():
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY)")
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


def ensure_customer(db, account_id: int, *, email: str | None, name: str) -> str:
    """Return the account's Stripe customer id, creating (and storing) one on
    first use."""
    with db.cursor() as cur:
        cur.execute("SELECT stripe_customer_id FROM account_billing WHERE account_id = %s",
                    (account_id,))
        row = cur.fetchone()
    if row and row[0]:
        return row[0]

    stripe = _stripe()
    customer = stripe.Customer.create(
        email=email or None,
        name=name,
        metadata={"account_id": str(account_id)},
    )
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO account_billing (account_id, stripe_customer_id) VALUES (%s, %s) "
            "ON CONFLICT (account_id) DO UPDATE SET stripe_customer_id = %s, updated_at = NOW()",
            (account_id, customer["id"], customer["id"]),
        )
        db.commit()
    return customer["id"]


def create_subscription_checkout(*, customer_id: str, price_id: str, account_id: int,
                                 plan_name: str, success_url: str, cancel_url: str) -> str:
    """Hosted Checkout for a plan subscription; returns the session URL.

    account_id/plan ride the session AND the subscription metadata so the
    webhook can resolve the tenant from either event shape.
    """
    stripe = _stripe()
    meta = {"account_id": str(account_id), "plan": plan_name}
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        subscription_data={"metadata": meta},
        metadata=meta,
        allow_promotion_codes=True,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session["url"]


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Stripe customer portal (change plan, update card, cancel)."""
    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=return_url,
    )
    return session["url"]


def construct_billing_webhook_event(payload: bytes, sig_header: str):
    """Verify + parse a billing webhook delivery. The secret belongs to a
    *platform* endpoint ("events on your account") — not the Connect endpoint
    used by invoice payments."""
    if not STRIPE_BILLING_WEBHOOK_SECRET:
        raise RuntimeError("Billing webhook is not configured (STRIPE_BILLING_WEBHOOK_SECRET)")
    import stripe
    return stripe.Webhook.construct_event(payload, sig_header, STRIPE_BILLING_WEBHOOK_SECRET)


def apply_plan(db, account_id: int, plan_name: str) -> None:
    """Point account_plans at a new plan, resetting module overrides to the
    plan's defaults — the same semantics as scripts/set_account_plan.py --plan
    (owners re-toggle within the new plan via PATCH /account/plan). Caller
    commits."""
    defaults = _plan_defaults(plan_name)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO account_plans (account_id, plan_name, modules, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (account_id) DO UPDATE SET plan_name = %s, modules = %s, updated_at = NOW()",
            (account_id, plan_name, Json(defaults), plan_name, Json(defaults)),
        )
    # A downgrade may leave more scheduled territories active than the new plan
    # allows — deactivate the extras (oldest ZIPs survive) in the same
    # transaction. Local import: api.territory lazily reaches back into
    # api.scheduler, which imports this module.
    from api.territory import trim_schedules_to_limit
    trim_schedules_to_limit(db, account_id)


def expire_stale_trials(conn) -> int:
    """Downgrade expired self-serve trials with no subscription to `starter`.

    Called by the daily scheduler tick (api/scheduler.py). Core features are
    always-on by design, so an expired trial keeps its data and day-to-day CRM
    — only the optional modules gate behind an upgrade. Returns the number of
    accounts downgraded. Commits.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE account_billing SET status = 'trial_expired', updated_at = NOW() "
            "WHERE status = 'trialing' AND trial_ends_at IS NOT NULL "
            "  AND trial_ends_at < NOW() AND stripe_subscription_id IS NULL "
            "RETURNING account_id",
        )
        expired = [r[0] for r in cur.fetchall()]
    for account_id in expired:
        apply_plan(conn, account_id, "starter")
    conn.commit()
    return len(expired)
