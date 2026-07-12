"""
Subscription billing routes (the account paying for Axon).

GET  /billing                    — plan catalog + this account's billing state
POST /billing/checkout           — {plan} → Stripe Checkout URL (owner)
POST /billing/portal             — Stripe customer-portal URL (owner)

Public (Stripe-called, registered ungated in main.py):
POST /api/public/stripe/billing-webhook — signature-verified, idempotent sink

The webhook endpoint is a *platform* endpoint ("events on your account"),
separate from the Connect endpoint in stripe_payments.py — subscription events
land on the platform account. Idempotency reuses the stripe_webhook_events
table from migration 047. Plan changes funnel through api.billing.apply_plan so
entitlements (account_plans) always match the subscription.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn

from config import APP_BASE_URL
from api import billing
from api.deps import get_db, dict_fetchone, get_current_user, require_owner
from api.entitlements import PLAN_CATALOG, MODULE_KEYS

log = logging.getLogger(__name__)

router = APIRouter()
public_router = APIRouter()


# ── Account-facing routes ─────────────────────────────────────────────────────

def _billing_row(db: PGConn, account_id: int) -> dict | None:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM account_billing WHERE account_id = %s", (account_id,))
        return dict_fetchone(cur)


def _plan_catalog() -> list[dict]:
    """Advertised plans + the modules each grants (for the billing UI)."""
    return [
        {
            "plan": plan,
            **meta,
            "modules": sorted(PLAN_CATALOG.get(plan, set(MODULE_KEYS))),
            "purchasable": billing.price_id_for_plan(plan) is not None,
        }
        for plan, meta in billing.PLAN_PRICING.items()
    ]


@router.get("/billing")
def billing_info(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    acct = current_user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT plan_name FROM account_plans WHERE account_id = %s", (acct,))
        row = cur.fetchone()
    plan_name = row[0] if row else "pro"

    b = _billing_row(db, acct) or {}
    return {
        "configured": billing.billing_configured(),
        "plan_name": plan_name,
        "status": b.get("status"),
        "trial_ends_at": b.get("trial_ends_at"),
        "current_period_end": b.get("current_period_end"),
        "cancel_at_period_end": bool(b.get("cancel_at_period_end")),
        "has_subscription": bool(b.get("stripe_subscription_id")),
        "plans": _plan_catalog(),
    }


@router.post("/billing/checkout")
def billing_checkout(body: dict, current_user: dict = Depends(require_owner),
                     db: PGConn = Depends(get_db)):
    plan = (body or {}).get("plan", "")
    if plan not in billing.PLAN_PRICING:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {plan}")
    price_id = billing.price_id_for_plan(plan)
    if not billing.billing_configured() or not price_id:
        raise HTTPException(
            status_code=503,
            detail="Self-serve billing isn't configured on this server yet.",
        )

    acct = current_user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT name FROM accounts WHERE id = %s", (acct,))
        row = cur.fetchone()
    try:
        customer_id = billing.ensure_customer(
            db, acct, email=current_user.get("email"),
            name=(row[0] if row and row[0] else f"Account {acct}"),
        )
        url = billing.create_subscription_checkout(
            customer_id=customer_id,
            price_id=price_id,
            account_id=acct,
            plan_name=plan,
            success_url=f"{APP_BASE_URL}/settings?billing=success",
            cancel_url=f"{APP_BASE_URL}/settings?billing=cancelled",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.exception("Billing checkout failed for account %d", acct)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return {"url": url}


@router.post("/billing/portal")
def billing_portal(current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    b = _billing_row(db, current_user["account_id"])
    if not b or not b.get("stripe_customer_id"):
        raise HTTPException(status_code=409, detail="No billing profile yet — subscribe first.")
    try:
        url = billing.create_portal_session(
            customer_id=b["stripe_customer_id"],
            return_url=f"{APP_BASE_URL}/settings",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.exception("Billing portal failed for account %d", current_user["account_id"])
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return {"url": url}


# ── Webhook ───────────────────────────────────────────────────────────────────

def _mark_event(db: PGConn, event_id: str, status: str, error: str | None = None) -> None:
    with db.cursor() as cur:
        cur.execute(
            "UPDATE stripe_webhook_events SET status = %s, error = %s, processed_at = NOW() "
            "WHERE event_id = %s",
            (status, error, event_id),
        )
        db.commit()


def _resolve_account(db: PGConn, *, metadata: dict, customer_id: str | None) -> int | None:
    """Find the tenant a billing event belongs to: subscription/session metadata
    first (we stamp account_id at checkout), then the stored customer id."""
    if metadata.get("account_id"):
        try:
            return int(metadata["account_id"])
        except (TypeError, ValueError):
            pass
    if customer_id:
        with db.cursor() as cur:
            cur.execute("SELECT account_id FROM account_billing WHERE stripe_customer_id = %s",
                        (customer_id,))
            row = cur.fetchone()
        if row:
            return row[0]
    return None


def _upsert_billing(db: PGConn, account_id: int, **fields) -> None:
    cols = ["account_id"] + list(fields.keys())
    vals = [account_id] + list(fields.values())
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields) + ", updated_at = NOW()"
    with db.cursor() as cur:
        cur.execute(
            f"INSERT INTO account_billing ({', '.join(cols)}) "
            f"VALUES ({', '.join(['%s'] * len(vals))}) "
            f"ON CONFLICT (account_id) DO UPDATE SET {updates}",
            vals,
        )


def _handle_checkout_completed(db: PGConn, event) -> str:
    obj = event["data"]["object"]
    if obj.get("mode") != "subscription":
        return "ignored"  # invoice payments ride the Connect endpoint, not this one
    metadata = obj.get("metadata") or {}
    account_id = _resolve_account(db, metadata=metadata, customer_id=obj.get("customer"))
    plan = metadata.get("plan")
    if not account_id or plan not in billing.PLAN_PRICING:
        raise ValueError(f"unresolvable checkout session {obj.get('id')!r} "
                         f"(account={account_id}, plan={plan!r})")
    _upsert_billing(
        db, account_id,
        stripe_customer_id=obj.get("customer"),
        stripe_subscription_id=obj.get("subscription"),
        plan_name=plan,
        status="active",
        trial_ends_at=None,  # a paid subscription supersedes the local trial
    )
    billing.apply_plan(db, account_id, plan)
    db.commit()
    log.info("Account %d subscribed to %s", account_id, plan)
    return "processed"


def _handle_subscription_event(db: PGConn, event) -> str:
    """customer.subscription.created/updated/deleted — mirror Stripe's state and
    keep account_plans in step (grace on past_due; starter once truly gone)."""
    obj = event["data"]["object"]
    items = ((obj.get("items") or {}).get("data")) or []
    price_id = (items[0].get("price") or {}).get("id") if items else None
    metadata = obj.get("metadata") or {}
    plan = billing.plan_for_price(price_id) or metadata.get("plan")
    account_id = _resolve_account(db, metadata=metadata, customer_id=obj.get("customer"))
    if not account_id:
        return "ignored"  # a subscription this deployment didn't create

    status = obj.get("status") or ("canceled" if event["type"].endswith("deleted") else None)
    _upsert_billing(
        db, account_id,
        stripe_customer_id=obj.get("customer"),
        stripe_subscription_id=obj.get("id"),
        plan_name=plan,
        status=status,
        cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
    )
    # current_period_end arrives as epoch seconds; cast it SQL-side.
    period_end = obj.get("current_period_end")
    if period_end:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE account_billing SET current_period_end = to_timestamp(%s) "
                "WHERE account_id = %s",
                (period_end, account_id),
            )

    if status in billing.ACTIVE_STATUSES and plan:
        billing.apply_plan(db, account_id, plan)
    elif status in ("canceled", "unpaid", "incomplete_expired"):
        # Access ends: back to the always-on core (never a data lockout).
        billing.apply_plan(db, account_id, "starter")
    db.commit()
    return "processed"


def _handle_event(db: PGConn, event) -> str:
    """Claim + process one billing event. Same idempotency contract as the
    Connect webhook (stripe_payments._handle_event): duplicates short-circuit,
    errored events are retried on Stripe's redelivery."""
    event_id, event_type = event["id"], event["type"]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stripe_webhook_events (event_id, event_type, stripe_account_id, payload) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING RETURNING id",
            (event_id, event_type, None, json.dumps(event, default=str)),
        )
        claimed = cur.fetchone()
        if not claimed:
            cur.execute("SELECT status FROM stripe_webhook_events WHERE event_id = %s", (event_id,))
            row = cur.fetchone()
            if row and row[0] in ("processed", "ignored"):
                db.commit()
                return "duplicate"
        db.commit()

    try:
        if event_type == "checkout.session.completed":
            outcome = _handle_checkout_completed(db, event)
        elif event_type in ("customer.subscription.created",
                            "customer.subscription.updated",
                            "customer.subscription.deleted"):
            outcome = _handle_subscription_event(db, event)
        else:
            outcome = "ignored"
    except Exception as exc:
        db.rollback()
        log.exception("Billing webhook %s (%s) failed", event_id, event_type)
        _mark_event(db, event_id, "error", str(exc))
        return "error"

    _mark_event(db, event_id, outcome if outcome != "duplicate" else "processed")
    return outcome


@public_router.post("/public/stripe/billing-webhook")
async def billing_webhook(request: Request, db: PGConn = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = billing.construct_billing_webhook_event(payload, sig_header)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    outcome = _handle_event(db, event)
    if outcome == "error":
        raise HTTPException(status_code=500, detail="Event processing failed")
    return {"received": True}
