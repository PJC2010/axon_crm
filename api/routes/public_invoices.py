"""Unauthenticated endpoints: the customer-facing pay page and the Stripe webhook.

These routes deliberately have NO `Depends(get_current_user)`:
  * Pay-page reads are authorized by the unguessable `pay_token` and return a
    redacted view only — never internal ids or other clients' data.
  * The webhook is authorized by Stripe signature verification + an idempotency
    table, and must read the RAW request body (no Pydantic parsing).
"""
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn

from api import stripe_client
from api.deps import get_db, dict_fetchone, dict_fetchall
from api.invoice_logic import _update_invoice_payment_state
from api.models import PublicInvoiceView, PublicLineItem, CheckoutSessionResponse
from config import STRIPE_WEBHOOK_SECRET, PUBLIC_APP_URL

router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _load_by_token(db: PGConn, token: str) -> dict | None:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM invoices WHERE pay_token = %s", (token,))
        inv = dict_fetchone(cur)
        if not inv:
            return None
        cur.execute(
            "SELECT description, quantity, unit_price FROM invoice_line_items "
            "WHERE invoice_id = %s ORDER BY sort_order, id",
            (inv["id"],),
        )
        inv["line_items"] = dict_fetchall(cur)
    return inv


def _owner_charges_enabled(db: PGConn, created_by: int | None) -> tuple[bool, str | None, str | None]:
    """Return (charges_enabled, stripe_account_id, business_name) for the invoice owner."""
    if created_by is None:
        return False, None, None
    with db.cursor() as cur:
        cur.execute(
            "SELECT sa.charges_enabled, sa.stripe_account_id, u.username "
            "FROM users u LEFT JOIN stripe_accounts sa ON sa.user_id = u.id WHERE u.id = %s",
            (created_by,),
        )
        row = cur.fetchone()
    if not row:
        return False, None, None
    return bool(row[0]), row[1], row[2]


# ── Public pay page ─────────────────────────────────────────────────────────

@router.get("/public/invoices/{token}", response_model=PublicInvoiceView)
def public_invoice(token: str, db: PGConn = Depends(get_db)):
    inv = _load_by_token(db, token)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    charges_enabled, _acct, business_name = _owner_charges_enabled(db, inv.get("created_by"))
    balance_due = float(inv["total"]) - float(inv["amount_paid"])
    items = [
        PublicLineItem(
            description=li["description"],
            quantity=float(li["quantity"]),
            unit_price=float(li["unit_price"]),
            amount=float(li["quantity"]) * float(li["unit_price"]),
        )
        for li in inv["line_items"]
    ]
    return PublicInvoiceView(
        invoice_number=inv["invoice_number"],
        business_name=business_name,
        client_name=inv["client_name"],
        status=inv["status"],
        subtotal=float(inv["subtotal"]),
        tax_rate=float(inv["tax_rate"]),
        tax_amount=float(inv["tax_amount"]),
        total=float(inv["total"]),
        amount_paid=float(inv["amount_paid"]),
        balance_due=balance_due,
        issue_date=inv["issue_date"],
        due_date=inv.get("due_date"),
        notes=inv.get("notes"),
        line_items=items,
        payable=charges_enabled and inv["status"] not in ("void", "paid") and balance_due > 0,
    )


@router.post("/public/invoices/{token}/checkout", response_model=CheckoutSessionResponse)
def public_checkout(token: str, db: PGConn = Depends(get_db)):
    inv = _load_by_token(db, token)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv["status"] in ("void", "paid"):
        raise HTTPException(status_code=400, detail=f"Invoice is {inv['status']}")

    balance_due = float(inv["total"]) - float(inv["amount_paid"])
    if balance_due <= 0:
        raise HTTPException(status_code=400, detail="Nothing left to pay")

    charges_enabled, account_id, _name = _owner_charges_enabled(db, inv.get("created_by"))
    if not charges_enabled or not account_id:
        raise HTTPException(status_code=400, detail="This business cannot accept online payments yet")

    session = stripe_client.create_checkout_session_for_invoice(
        account_id=account_id,
        invoice_id=inv["id"],
        invoice_number=inv["invoice_number"],
        amount_due=balance_due,
        pay_token=token,
        client_email=inv.get("client_email"),
    )
    with db.cursor() as cur:
        cur.execute(
            "UPDATE invoices SET stripe_checkout_session_id = %s WHERE id = %s",
            (session.id, inv["id"]),
        )
        db.commit()
    return CheckoutSessionResponse(url=session.url)


# ── Stripe webhook ──────────────────────────────────────────────────────────

@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: PGConn = Depends(get_db)):
    payload = await request.body()  # RAW body — required for signature verification
    sig = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Idempotency: skip events we've already processed.
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stripe_webhook_events (event_id, event_type) VALUES (%s, %s) "
            "ON CONFLICT (event_id) DO NOTHING RETURNING id",
            (event["id"], event["type"]),
        )
        first_time = cur.fetchone() is not None
        db.commit()
    if not first_time:
        return {"status": "duplicate"}

    etype = event["type"]
    obj = event["data"]["object"]

    if etype in ("checkout.session.completed", "payment_intent.succeeded"):
        _handle_payment(db, etype, obj)
    elif etype == "account.updated":
        _handle_account_updated(db, obj)

    return {"status": "ok"}


def _handle_payment(db: PGConn, etype: str, obj: dict):
    # Resolve the invoice from whatever identifiers the event carries.
    invoice = None
    with db.cursor() as cur:
        if etype == "checkout.session.completed":
            if obj.get("payment_status") != "paid":
                return
            ref = obj.get("client_reference_id")
            if ref:
                cur.execute("SELECT * FROM invoices WHERE id = %s", (int(ref),))
                invoice = dict_fetchone(cur)
            if not invoice and obj.get("id"):
                cur.execute("SELECT * FROM invoices WHERE stripe_checkout_session_id = %s", (obj["id"],))
                invoice = dict_fetchone(cur)
            amount = float(obj.get("amount_total", 0)) / 100.0
            payment_intent_id = obj.get("payment_intent")
            charge_id = None
        else:  # payment_intent.succeeded
            cur.execute("SELECT * FROM invoices WHERE stripe_payment_intent_id = %s", (obj.get("id"),))
            invoice = dict_fetchone(cur)
            amount = float(obj.get("amount_received", 0)) / 100.0
            payment_intent_id = obj.get("id")
            charge_id = (obj.get("latest_charge") if isinstance(obj.get("latest_charge"), str) else None)

    if not invoice or amount <= 0:
        return

    invoice_id = invoice["id"]
    # Guard against the two payment events for the same checkout double-counting.
    with db.cursor() as cur:
        if payment_intent_id:
            cur.execute(
                "SELECT 1 FROM invoice_payments WHERE invoice_id = %s AND stripe_payment_intent_id = %s",
                (invoice_id, payment_intent_id),
            )
            if cur.fetchone():
                return

        cur.execute(
            "INSERT INTO invoice_payments "
            "(invoice_id, amount, payment_date, payment_method, notes, created_by, "
            " stripe_payment_intent_id, stripe_charge_id) "
            "VALUES (%s,%s,CURRENT_DATE,'stripe',%s,%s,%s,%s)",
            (invoice_id, amount, "Paid online via Stripe", invoice.get("created_by"),
             payment_intent_id, charge_id),
        )
        fee = stripe_client.platform_fee_cents(amount) / 100.0
        cur.execute(
            "UPDATE invoices SET stripe_payment_intent_id = COALESCE(stripe_payment_intent_id, %s), "
            "platform_fee_amount = COALESCE(platform_fee_amount, 0) + %s WHERE id = %s",
            (payment_intent_id, fee, invoice_id),
        )
        db.commit()

    _update_invoice_payment_state(db, invoice_id)
    db.commit()


def _handle_account_updated(db: PGConn, obj: dict):
    account_id = obj.get("id")
    if not account_id:
        return
    charges = bool(obj.get("charges_enabled"))
    payouts = bool(obj.get("payouts_enabled"))
    submitted = bool(obj.get("details_submitted"))
    status = "active" if charges else ("pending" if not submitted else "restricted")
    with db.cursor() as cur:
        cur.execute(
            "UPDATE stripe_accounts SET charges_enabled=%s, payouts_enabled=%s, "
            "details_submitted=%s, onboarding_status=%s WHERE stripe_account_id=%s",
            (charges, payouts, submitted, status, account_id),
        )
        db.commit()
