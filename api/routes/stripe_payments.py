"""
POST /api/stripe/connect               — create/resume Express onboarding (owner)
GET  /api/stripe/status                — platform + connected-account readiness
POST /api/invoices/{id}/checkout       — checkout URL for an invoice (staff-initiated)

Public (token-addressed / Stripe-called, registered ungated in main.py):
GET  /api/public/pay/{pay_token}           — customer-safe pay-page payload
POST /api/public/pay/{pay_token}/checkout  — create a Checkout Session, return its URL
POST /api/public/stripe/webhook            — signature-verified, idempotent event sink

Stripe Connect Express with direct charges: Checkout Sessions are created ON the
owner's connected account, so payment events (checkout.session.completed,
payment_intent.succeeded) arrive on the CONNECTED account — the dashboard
webhook endpoint must be a Connect endpoint ("events on connected accounts")
pointed at /api/public/stripe/webhook, and STRIPE_WEBHOOK_SECRET is that
endpoint's signing secret. The webhook inserts an invoice_payments row and
funnels through _update_invoice_payment_state — the same path manual payments
use — so AR summaries and aging need no special casing.
"""
import datetime
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn

from config import APP_BASE_URL
from api.deps import get_db, dict_fetchone, get_current_user, require_owner
from api.integrations.stripe import stripe_client
from api.invoice_logic import _load_invoice, _update_invoice_payment_state
from api.models import StripeStatus, PublicPayInfo
from api.ratelimit import client_ip, public_pay_limiter

log = logging.getLogger(__name__)

router = APIRouter()

# Same rationale as invoices.public_router: customers and Stripe must reach
# these without the seller's login/plan, and module-gating would attach
# get_current_user's `?token=` query param to a `{pay_token}` path.
public_router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _business_name(db: PGConn, account_id: int) -> str:
    with db.cursor() as cur:
        cur.execute("SELECT name FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
    return (row[0] if row and row[0] else "Axon")


def _stripe_account_row(db: PGConn, account_id: int) -> dict | None:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM stripe_accounts WHERE account_id = %s", (account_id,))
        return dict_fetchone(cur)


def _checkout_url_for_invoice(db: PGConn, inv: dict) -> str:
    """Create a Checkout Session for the invoice's outstanding balance and
    record its id on the invoice. Shared by the staff and public routes."""
    if inv["status"] == "void":
        raise HTTPException(status_code=400, detail="This invoice has been voided")
    balance = float(inv["total"]) - float(inv["amount_paid"])
    if balance <= 0:
        raise HTTPException(status_code=400, detail="This invoice is already paid")

    sa = _stripe_account_row(db, inv["account_id"])
    if not sa or not sa["charges_enabled"]:
        raise HTTPException(status_code=409, detail="Online payments are not set up for this business")

    amount_cents = round(balance * 100)
    fee_cents = stripe_client.platform_fee_cents(amount_cents)
    pay_url = f"{APP_BASE_URL}/pay/{inv['pay_token']}"

    # Kill the previous still-open session first so at most ONE payable link
    # exists per invoice. Checkout Sessions stay payable ~24h; an emailed link
    # plus a fresh pay-page session were two live charges for the same balance
    # — the double-payment path. Best-effort: an already completed/expired
    # session raises, and that's fine.
    if inv.get("stripe_checkout_session_id"):
        try:
            stripe_client.expire_checkout_session(
                sa["stripe_account_id"], inv["stripe_checkout_session_id"])
        except Exception:
            log.info("Previous checkout session %s for invoice %d not expirable "
                     "(already completed or expired)",
                     inv["stripe_checkout_session_id"], inv["id"])

    try:
        session = stripe_client.create_checkout_session(
            stripe_account_id=sa["stripe_account_id"],
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            invoice_number=inv["invoice_number"],
            business_name=_business_name(db, inv["account_id"]),
            success_url=f"{pay_url}?status=success",
            cancel_url=f"{pay_url}?status=cancelled",
            metadata={
                "invoice_id": str(inv["id"]),
                "account_id": str(inv["account_id"]),
                "pay_token": inv["pay_token"],
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.exception("Stripe checkout creation failed for invoice %d", inv["id"])
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")

    with db.cursor() as cur:
        cur.execute(
            "UPDATE invoices SET stripe_checkout_session_id = %s, platform_fee_amount = %s, "
            "updated_at = NOW() WHERE id = %s",
            (session["id"], fee_cents / 100, inv["id"]),
        )
        db.commit()
    return session["url"]


# ── Authenticated routes ──────────────────────────────────────────────────────

@router.post("/stripe/connect")
def connect_stripe(current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    """Create the account's Express connected account on first call, then (and
    on every later call) return a fresh hosted-onboarding link."""
    if not stripe_client.stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe is not configured on this server")
    account_id = current_user["account_id"]

    sa = _stripe_account_row(db, account_id)
    try:
        if sa:
            stripe_account_id = sa["stripe_account_id"]
        else:
            stripe_account_id = stripe_client.create_express_account(
                email=current_user.get("email"),
                business_name=_business_name(db, account_id),
            )
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO stripe_accounts (account_id, stripe_account_id, created_by) "
                    "VALUES (%s, %s, %s)",
                    (account_id, stripe_account_id, current_user["id"]),
                )
                db.commit()
        url = stripe_client.create_account_link(
            stripe_account_id,
            refresh_url=f"{APP_BASE_URL}/settings?stripe=refresh",
            return_url=f"{APP_BASE_URL}/settings?stripe=return",
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Stripe Connect onboarding failed for account %d", account_id)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return {"url": url}


@router.get("/stripe/status", response_model=StripeStatus)
def stripe_status(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    available = stripe_client.stripe_configured()
    sa = _stripe_account_row(db, user["account_id"])
    if not available or not sa:
        return StripeStatus(available=available, connected=False)

    # Refresh onboarding flags from Stripe; fall back to stored values so the
    # settings page still renders when Stripe is briefly unreachable.
    flags = {k: sa[k] for k in ("charges_enabled", "payouts_enabled", "details_submitted")}
    try:
        fresh = stripe_client.fetch_account_status(sa["stripe_account_id"])
        if fresh != flags:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE stripe_accounts SET charges_enabled = %s, payouts_enabled = %s, "
                    "details_submitted = %s, updated_at = NOW() WHERE id = %s",
                    (fresh["charges_enabled"], fresh["payouts_enabled"],
                     fresh["details_submitted"], sa["id"]),
                )
                db.commit()
            flags = fresh
    except Exception:
        log.warning("Stripe status refresh failed for account %d", user["account_id"], exc_info=True)

    return StripeStatus(available=True, connected=True, **flags)


@router.post("/invoices/{invoice_id}/checkout")
def create_invoice_checkout(invoice_id: int, user: dict = Depends(get_current_user),
                            db: PGConn = Depends(get_db)):
    """Checkout link for staff to hand to a customer (or take a card payment
    on the spot). The public pay page uses the tokenized route below."""
    inv = _load_invoice(db, invoice_id)
    if not inv or inv["account_id"] != user["account_id"]:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"url": _checkout_url_for_invoice(db, inv)}


# ── Public pay page ───────────────────────────────────────────────────────────

def _get_public_invoice(db: PGConn, pay_token: str) -> dict:
    with db.cursor() as cur:
        cur.execute("SELECT id FROM invoices WHERE pay_token = %s", (pay_token,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _load_invoice(db, row[0])


def _public_pdf_url(request: Request, inv: dict) -> str:
    url = str(request.url_for("public_invoice_pdf", token=inv["public_token"]))
    # Render terminates TLS at its proxy (uvicorn sees plain http) — force https
    # for non-local hosts so the link works outside the cluster.
    if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
        url = "https://" + url[len("http://"):]
    return url


@public_router.get("/public/pay/{pay_token}", response_model=PublicPayInfo)
def public_pay_info(pay_token: str, request: Request, db: PGConn = Depends(get_db)):
    public_pay_limiter.check(client_ip(request))
    inv = _get_public_invoice(db, pay_token)
    sa = _stripe_account_row(db, inv["account_id"])
    balance = float(inv["total"]) - float(inv["amount_paid"])
    return PublicPayInfo(
        business_name=_business_name(db, inv["account_id"]),
        invoice_number=inv["invoice_number"],
        status=inv["status"],
        total=float(inv["total"]),
        amount_paid=float(inv["amount_paid"]),
        balance_due=balance,
        issue_date=inv["issue_date"],
        due_date=inv["due_date"],
        payable=bool(
            stripe_client.stripe_configured()
            and sa and sa["charges_enabled"]
            and balance > 0
            and inv["status"] != "void"
        ),
        pdf_url=_public_pdf_url(request, inv),
    )


@public_router.post("/public/pay/{pay_token}/checkout")
def public_create_checkout(pay_token: str, request: Request, db: PGConn = Depends(get_db)):
    public_pay_limiter.check(client_ip(request))
    inv = _get_public_invoice(db, pay_token)
    return {"url": _checkout_url_for_invoice(db, inv)}


# ── Webhook ───────────────────────────────────────────────────────────────────

def _mark_event(db: PGConn, event_id: str, status: str, error: str | None = None) -> None:
    with db.cursor() as cur:
        cur.execute(
            "UPDATE stripe_webhook_events SET status = %s, error = %s, processed_at = NOW() "
            "WHERE event_id = %s",
            (status, error, event_id),
        )
        db.commit()


def _record_stripe_payment(db: PGConn, *, invoice_id: int, amount: float,
                           payment_intent_id: str | None, charge_id: str | None) -> None:
    """Insert the payment row (deduped on the PaymentIntent — both
    checkout.session.completed and payment_intent.succeeded land here) and
    recompute the invoice's payment state."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO invoice_payments (invoice_id, amount, payment_date, payment_method, "
            "notes, stripe_payment_intent_id, stripe_charge_id) "
            "VALUES (%s, %s, %s, 'stripe', %s, %s, %s) "
            "ON CONFLICT (stripe_payment_intent_id) WHERE stripe_payment_intent_id IS NOT NULL "
            "DO NOTHING",
            (invoice_id, amount, datetime.date.today(), "Paid online via Stripe",
             payment_intent_id, charge_id),
        )
        cur.execute(
            "UPDATE invoices SET stripe_payment_intent_id = COALESCE(%s, stripe_payment_intent_id), "
            "updated_at = NOW() WHERE id = %s",
            (payment_intent_id, invoice_id),
        )
    _update_invoice_payment_state(db, invoice_id)
    db.commit()


def _handle_payment_event(db: PGConn, event) -> str:
    obj = event["data"]["object"]
    metadata = obj.get("metadata") or {}
    if "invoice_id" not in metadata or "account_id" not in metadata:
        return "ignored"  # a charge on the connected account that isn't ours
    invoice_id, account_id = int(metadata["invoice_id"]), int(metadata["account_id"])

    # The event arrives on a connected account; require it to be the one we
    # have on file for the claimed tenant, so forged metadata in someone
    # else's account can't mark our invoices paid.
    sa = _stripe_account_row(db, account_id)
    if not sa or sa["stripe_account_id"] != event.get("account"):
        raise ValueError(
            f"event account {event.get('account')!r} does not match "
            f"the connected account on file for account {account_id}"
        )

    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM invoices WHERE id = %s AND account_id = %s",
                    (invoice_id, account_id))
        if not cur.fetchone():
            raise ValueError(f"invoice {invoice_id} not found for account {account_id}")

    if event["type"] == "checkout.session.completed":
        if obj.get("payment_status") not in (None, "paid"):
            return "ignored"  # async payment methods complete via payment_intent.succeeded
        amount = (obj.get("amount_total") or 0) / 100
        payment_intent_id = obj.get("payment_intent")
        charge_id = None
    else:  # payment_intent.succeeded
        amount = (obj.get("amount_received") or obj.get("amount") or 0) / 100
        payment_intent_id = obj.get("id")
        charge_id = obj.get("latest_charge")
    if amount <= 0:
        return "ignored"

    _record_stripe_payment(db, invoice_id=invoice_id, amount=amount,
                           payment_intent_id=payment_intent_id, charge_id=charge_id)
    return "processed"


def _handle_charge_refunded(db: PGConn, event) -> str:
    """Mirror a Stripe refund into the books as a negative payment row.

    Without this, an owner refunding a customer in the Stripe dashboard leaves
    the invoice `paid` forever and AR/aging overstates collections. The charge
    is resolved through the PaymentIntent we recorded at payment time (charge
    metadata isn't stamped; invoice_payments.stripe_payment_intent_id is).
    `amount_refunded` is cumulative across partial refunds, so only the delta
    beyond already-recorded refund rows is inserted — redeliveries and repeat
    events net to zero.
    """
    obj = event["data"]["object"]  # the charge, with cumulative amount_refunded
    payment_intent_id = obj.get("payment_intent")
    if not payment_intent_id:
        return "ignored"
    with db.cursor() as cur:
        cur.execute(
            "SELECT invoice_id FROM invoice_payments "
            "WHERE stripe_payment_intent_id = %s AND amount > 0",
            (payment_intent_id,),
        )
        row = cur.fetchone()
    if not row:
        return "ignored"  # not a payment this app recorded
    invoice_id = row[0]

    with db.cursor() as cur:
        cur.execute("SELECT account_id FROM invoices WHERE id = %s", (invoice_id,))
        inv_row = cur.fetchone()
    if not inv_row:
        return "ignored"
    account_id = inv_row[0]
    # Same forged-account guard as _handle_payment_event.
    sa = _stripe_account_row(db, account_id)
    if not sa or sa["stripe_account_id"] != event.get("account"):
        raise ValueError(
            f"event account {event.get('account')!r} does not match "
            f"the connected account on file for account {account_id}"
        )

    refunded_total = (obj.get("amount_refunded") or 0) / 100
    charge_id = obj.get("id")
    with db.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(-amount), 0) FROM invoice_payments "
            "WHERE invoice_id = %s AND stripe_charge_id = %s AND amount < 0",
            (invoice_id, charge_id),
        )
        already_recorded = float(cur.fetchone()[0])
    delta = round(refunded_total - already_recorded, 2)
    if delta <= 0:
        return "ignored"

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO invoice_payments (invoice_id, amount, payment_date, "
            "payment_method, notes, stripe_charge_id) "
            "VALUES (%s, %s, %s, 'stripe', %s, %s)",
            (invoice_id, -delta, datetime.date.today(),
             "Refunded via Stripe", charge_id),
        )
    _update_invoice_payment_state(db, invoice_id)
    db.commit()
    return "processed"


def _handle_account_updated(db: PGConn, event) -> str:
    obj = event["data"]["object"]
    with db.cursor() as cur:
        cur.execute(
            "UPDATE stripe_accounts SET charges_enabled = %s, payouts_enabled = %s, "
            "details_submitted = %s, updated_at = NOW() WHERE stripe_account_id = %s "
            "RETURNING id",
            (bool(obj.get("charges_enabled")), bool(obj.get("payouts_enabled")),
             bool(obj.get("details_submitted")), obj.get("id")),
        )
        updated = cur.fetchone()
        db.commit()
    return "processed" if updated else "ignored"


def _handle_event(db: PGConn, event) -> str:
    """Process one webhook event. Returns processed|ignored|duplicate|error.

    Idempotency: the event id is claimed in stripe_webhook_events first; a
    redelivery of an already processed/ignored event short-circuits, while an
    event that previously errored is retried (Stripe redelivers on non-2xx).
    """
    event_id, event_type = event["id"], event["type"]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stripe_webhook_events (event_id, event_type, stripe_account_id, payload) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING RETURNING id",
            (event_id, event_type, event.get("account"), json.dumps(event, default=str)),
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
        if event_type in ("checkout.session.completed", "payment_intent.succeeded"):
            outcome = _handle_payment_event(db, event)
        elif event_type == "charge.refunded":
            outcome = _handle_charge_refunded(db, event)
        elif event_type == "account.updated":
            outcome = _handle_account_updated(db, event)
        else:
            outcome = "ignored"
    except Exception as exc:
        db.rollback()
        log.exception("Stripe webhook %s (%s) failed", event_id, event_type)
        _mark_event(db, event_id, "error", str(exc))
        return "error"

    _mark_event(db, event_id, outcome if outcome != "duplicate" else "processed")
    return outcome


@public_router.post("/public/stripe/webhook")
async def stripe_webhook(request: Request, db: PGConn = Depends(get_db)):
    if not stripe_client.stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.construct_webhook_event(payload, sig_header)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    outcome = _handle_event(db, event)
    if outcome == "error":
        # Non-2xx makes Stripe redeliver; the idempotency log retries errored
        # events but skips already-processed ones.
        raise HTTPException(status_code=500, detail="Event processing failed")
    return {"received": True}
