"""Authenticated payment-automation endpoints.

POST /api/stripe/connect/onboard        — create/reuse Express account + onboarding link
GET  /api/stripe/connect/status         — connected-account status
POST /api/invoices/{id}/checkout-session — Stripe Checkout URL (direct charge + app fee)
POST /api/invoices/{id}/send            — deliver invoice via email and/or SMS

Public pay-page + Stripe webhook live in api/routes/public_invoices.py.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api import stripe_client
from api import notifications
from api.deps import get_db, dict_fetchone, get_current_user, require_owner
from api.invoice_logic import _load_invoice
from api.models import (
    ConnectStatus, OnboardingLink, CheckoutSessionResponse, SendInvoiceRequest, Invoice,
)
from config import PUBLIC_APP_URL

router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_account_row(db: PGConn, user_id: int) -> dict | None:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM stripe_accounts WHERE user_id = %s", (user_id,))
        return dict_fetchone(cur)


def _ensure_pay_token(db: PGConn, invoice_id: int, existing: str | None) -> str:
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    with db.cursor() as cur:
        cur.execute("UPDATE invoices SET pay_token = %s WHERE id = %s", (token, invoice_id))
        db.commit()
    return token


# ── Stripe Connect onboarding ───────────────────────────────────────────────

@router.post("/stripe/connect/onboard", response_model=OnboardingLink)
def stripe_onboard(current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    if not stripe_client.is_configured():
        raise HTTPException(status_code=503, detail="Stripe is not configured on the server")

    row = _get_account_row(db, current_user["id"])
    if row:
        account_id = row["stripe_account_id"]
    else:
        account_id = stripe_client.create_express_account(email=current_user.get("email"))
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO stripe_accounts (user_id, stripe_account_id) VALUES (%s, %s)",
                (current_user["id"], account_id),
            )
            db.commit()

    url = stripe_client.create_account_link(account_id)
    return OnboardingLink(url=url)


@router.get("/stripe/connect/status", response_model=ConnectStatus)
def stripe_status(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    row = _get_account_row(db, current_user["id"])
    if not row:
        return ConnectStatus(connected=False)

    # Refresh live status from Stripe so the UI reflects completed onboarding.
    if stripe_client.is_configured():
        try:
            live = stripe_client.retrieve_account(row["stripe_account_id"])
            new_status = "active" if live["charges_enabled"] else (
                "pending" if not live["details_submitted"] else "restricted"
            )
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE stripe_accounts SET charges_enabled=%s, payouts_enabled=%s, "
                    "details_submitted=%s, onboarding_status=%s WHERE user_id=%s",
                    (live["charges_enabled"], live["payouts_enabled"],
                     live["details_submitted"], new_status, current_user["id"]),
                )
                db.commit()
            row.update(live)
            row["onboarding_status"] = new_status
        except Exception:
            pass  # fall back to stored values

    return ConnectStatus(
        connected=True,
        onboarding_status=row["onboarding_status"],
        charges_enabled=row["charges_enabled"],
        payouts_enabled=row["payouts_enabled"],
        details_submitted=row["details_submitted"],
    )


# ── Checkout ────────────────────────────────────────────────────────────────

@router.post("/invoices/{invoice_id}/checkout-session", response_model=CheckoutSessionResponse)
def create_checkout(invoice_id: int, current_user: dict = Depends(get_current_user),
                    db: PGConn = Depends(get_db)):
    inv = _load_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv["status"] in ("void", "paid"):
        raise HTTPException(status_code=400, detail=f"Invoice is {inv['status']}")
    if inv["balance_due"] <= 0:
        raise HTTPException(status_code=400, detail="Nothing left to pay")

    acct = _get_account_row(db, current_user["id"])
    if not acct or not acct["charges_enabled"]:
        raise HTTPException(status_code=400, detail="Connect Stripe and finish onboarding to accept payments")

    token = _ensure_pay_token(db, invoice_id, inv.get("pay_token"))
    session = stripe_client.create_checkout_session_for_invoice(
        account_id=acct["stripe_account_id"],
        invoice_id=invoice_id,
        invoice_number=inv["invoice_number"],
        amount_due=float(inv["balance_due"]),
        pay_token=token,
        client_email=inv.get("client_email"),
    )
    with db.cursor() as cur:
        cur.execute(
            "UPDATE invoices SET stripe_checkout_session_id = %s WHERE id = %s",
            (session.id, invoice_id),
        )
        db.commit()
    return CheckoutSessionResponse(url=session.url)


# ── Send invoice (email / SMS) ──────────────────────────────────────────────

@router.post("/invoices/{invoice_id}/send", response_model=Invoice)
def send_invoice(invoice_id: int, body: SendInvoiceRequest,
                 current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    inv = _load_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv["status"] == "void":
        raise HTTPException(status_code=400, detail="Cannot send a voided invoice")

    channels = [c for c in body.channels if c in ("email", "sms")]
    if not channels:
        raise HTTPException(status_code=400, detail="No valid channels (email, sms)")

    token = _ensure_pay_token(db, invoice_id, inv.get("pay_token"))
    pay_url = f"{PUBLIC_APP_URL}/pay/{token}"
    business_name = current_user.get("username") or "Axon"
    amount_due = float(inv["balance_due"])
    errors: list[str] = []
    sent: list[str] = []

    if "email" in channels:
        if not inv.get("client_email"):
            errors.append("No client email on file")
        else:
            try:
                notifications.send_invoice_email(
                    to_email=inv["client_email"], business_name=business_name,
                    invoice_number=inv["invoice_number"], amount_due=amount_due, pay_url=pay_url,
                )
                sent.append("email")
            except Exception as e:
                errors.append(f"Email: {e}")

    if "sms" in channels:
        if not inv.get("client_phone"):
            errors.append("No client phone on file")
        else:
            try:
                notifications.send_invoice_sms(
                    to_phone=inv["client_phone"], business_name=business_name,
                    invoice_number=inv["invoice_number"], amount_due=amount_due, pay_url=pay_url,
                )
                sent.append("sms")
            except Exception as e:
                errors.append(f"SMS: {e}")

    if not sent:
        raise HTTPException(status_code=400, detail="; ".join(errors) or "Failed to send")

    new_status = "sent" if inv["status"] == "draft" else inv["status"]
    with db.cursor() as cur:
        cur.execute(
            "UPDATE invoices SET status=%s, sent_at=NOW(), sent_channels=%s, "
            "last_emailed_at = CASE WHEN %s THEN NOW() ELSE last_emailed_at END, "
            "last_sms_at     = CASE WHEN %s THEN NOW() ELSE last_sms_at END, "
            "updated_at=NOW() WHERE id=%s",
            (new_status, sent, "email" in sent, "sms" in sent, invoice_id),
        )
        db.commit()

    return Invoice(**_load_invoice(db, invoice_id))
