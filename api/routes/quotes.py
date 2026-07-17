"""
GET    /api/quotes               — list (filters: status, property_id, page)
POST   /api/quotes               — create with line items
GET    /api/quotes/{id}          — single with line_items
PATCH  /api/quotes/{id}          — update header + optionally replace line items
DELETE /api/quotes/{id}          — delete (owner only)
POST   /api/quotes/{id}/send     — deliver to client by email and/or SMS
POST   /api/quotes/{id}/convert  — accept + convert to a fresh invoice

Public (unauthenticated, token-addressed, IP rate-limited):
GET    /api/public/quotes/{token}          — customer view (stamps viewed_at)
POST   /api/public/quotes/{token}/accept   — customer accepts
POST   /api/public/quotes/{token}/decline  — customer declines (optional reason)

Quotes use their own number sequence (Q-YYYY-NNNN). Converting creates a brand
new invoice through next_invoice_number(), keeping the invoice sequence gapless.

Lifecycle events (sent / accepted / declined) fire quote_event workflow rules,
which can move the linked lead and chain into status_change automations.
"""
import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extensions import connection as PGConn

from config import APP_BASE_URL
from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner
from api.invoice_logic import _calc_totals, _load_invoice
from api.notifications import send_quote_email, send_quote_sms
from api.ratelimit import client_ip, public_quote_limiter
from api.models import (
    Quote, QuoteCreate, QuoteUpdate, ConvertQuoteRequest, PublicDeclineRequest,
    Invoice, SendInvoiceRequest,
    QUOTE_STATUSES,
)

log = logging.getLogger(__name__)

router = APIRouter()

# Public, token-addressed routes (see module docstring). Registered on their own
# router in main.py, without the `require_module("quotes")` gate: a customer
# opening a shared quote link shouldn't need the seller's plan/module, and
# gating them would also attach `get_current_user` (which accepts a `?token=`
# query param for CSV-export auth) to a route whose *path* parameter is also
# named `token`, tripping FastAPI's path/query param collision check.
public_router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_quote(db: PGConn, quote_id: int) -> Optional[dict]:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM quotes WHERE id = %s", (quote_id,))
        quote = dict_fetchone(cur)
        if not quote:
            return None
        cur.execute(
            "SELECT * FROM quote_line_items WHERE quote_id = %s ORDER BY sort_order, id",
            (quote_id,),
        )
        quote["line_items"] = dict_fetchall(cur)
        for li in quote["line_items"]:
            li["amount"] = float(li["quantity"]) * float(li["unit_price"])
    return quote


def _get_quote_or_404(db: PGConn, quote_id: int, account_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM quotes WHERE id = %s AND account_id = %s", (quote_id, account_id))
        quote = dict_fetchone(cur)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


def _fire_quote_event(db: PGConn, quote: dict, event: str) -> None:
    """Run quote_event workflow rules; never let automation break the request.

    Public-page events have no acting user, so actions run as the quote's
    creator (matching how signal_event rules run as the rule's creator).
    """
    from api.workflow_engine import execute_quote_event_rules
    try:
        execute_quote_event_rules(
            db, account_id=quote["account_id"], lead_id=quote["property_id"],
            event=event, user_id=quote["created_by"],
        )
    except Exception:
        log.exception("quote_event rules failed for quote %d (%s)", quote["id"], event)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/quotes", response_model=dict)
def list_quotes(
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    conditions, params = ["account_id = %s"], [user["account_id"]]
    if status:
        conditions.append("status = %s"); params.append(status)
    if property_id is not None:
        conditions.append("property_id = %s"); params.append(property_id)
    where = "WHERE " + " AND ".join(conditions)
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM quotes {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT * FROM quotes {where} ORDER BY issue_date DESC, id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    items = []
    for r in rows:
        r["line_items"] = []
        items.append(Quote(**r).model_dump())

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/quotes", response_model=Quote, status_code=201)
def create_quote(
    body: QuoteCreate,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    if not body.line_items:
        raise HTTPException(status_code=400, detail="At least one line item required")

    items_raw = [{"quantity": li.quantity, "unit_price": li.unit_price} for li in body.line_items]
    subtotal, tax_amount, total = _calc_totals(items_raw, body.tax_rate)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO quotes (property_id, client_name, client_phone, client_email, client_address, "
            "tax_rate, subtotal, tax_amount, total, issue_date, valid_until, notes, created_by, account_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (body.property_id, body.client_name, body.client_phone, body.client_email,
             body.client_address, body.tax_rate, subtotal, tax_amount, total,
             body.issue_date, body.valid_until, body.notes,
             current_user["id"], current_user["account_id"]),
        )
        quote_id = cur.fetchone()[0]

        for li in body.line_items:
            cur.execute(
                "INSERT INTO quote_line_items (quote_id, description, quantity, unit_price, sort_order) "
                "VALUES (%s,%s,%s,%s,%s)",
                (quote_id, li.description, li.quantity, li.unit_price, li.sort_order),
            )
        db.commit()

    return Quote(**_load_quote(db, quote_id))


@router.get("/quotes/{quote_id}", response_model=Quote)
def get_quote(quote_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    _get_quote_or_404(db, quote_id, user["account_id"])
    return Quote(**_load_quote(db, quote_id))


@router.patch("/quotes/{quote_id}", response_model=Quote)
def update_quote(
    quote_id: int,
    body: QuoteUpdate,
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    existing = _get_quote_or_404(db, quote_id, user["account_id"])
    if existing["converted_invoice_id"]:
        raise HTTPException(status_code=400, detail="Cannot edit a quote that has been converted to an invoice")

    sets, params = ["updated_at = NOW()"], []
    for field in ("client_name", "client_phone", "client_email", "client_address", "notes"):
        val = getattr(body, field)
        if val is not None:
            sets.append(f"{field} = %s"); params.append(val)
    if body.status is not None:
        if body.status not in QUOTE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        sets.append("status = %s"); params.append(body.status)
        # Stamp lifecycle timestamps on first transition into accepted/declined.
        if body.status == "accepted" and not existing["accepted_at"]:
            sets.append("accepted_at = NOW()")
        if body.status == "declined" and not existing["declined_at"]:
            sets.append("declined_at = NOW()")
    if body.issue_date is not None:
        sets.append("issue_date = %s"); params.append(body.issue_date)
    if body.valid_until is not None:
        sets.append("valid_until = %s"); params.append(body.valid_until)

    # If line items provided, replace them and recalculate totals
    if body.line_items is not None:
        if not body.line_items:
            raise HTTPException(status_code=400, detail="At least one line item required")
        items_raw = [{"quantity": li.quantity, "unit_price": li.unit_price} for li in body.line_items]
        tax_rate = body.tax_rate if body.tax_rate is not None else float(existing["tax_rate"])
        subtotal, tax_amount, total = _calc_totals(items_raw, tax_rate)
        sets += ["tax_rate = %s", "subtotal = %s", "tax_amount = %s", "total = %s"]
        params += [tax_rate, subtotal, tax_amount, total]

        with db.cursor() as cur:
            cur.execute("DELETE FROM quote_line_items WHERE quote_id = %s", (quote_id,))
            for li in body.line_items:
                cur.execute(
                    "INSERT INTO quote_line_items (quote_id, description, quantity, unit_price, sort_order) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (quote_id, li.description, li.quantity, li.unit_price, li.sort_order),
                )
    elif body.tax_rate is not None:
        sets.append("tax_rate = %s"); params.append(body.tax_rate)

    params.append(quote_id)
    with db.cursor() as cur:
        cur.execute(f"UPDATE quotes SET {', '.join(sets)} WHERE id = %s", params)
        db.commit()

    # Owner manually marking the outcome fires the same automations as the
    # customer clicking the public page.
    if body.status in ("accepted", "declined") and body.status != existing["status"]:
        _fire_quote_event(db, existing, body.status)

    return Quote(**_load_quote(db, quote_id))


@router.delete("/quotes/{quote_id}", status_code=204)
def delete_quote(quote_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM quotes WHERE id = %s AND account_id = %s RETURNING id",
                    (quote_id, current_user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Quote not found")


@router.post("/quotes/{quote_id}/send", response_model=Quote)
def send_quote(
    quote_id: int,
    body: SendInvoiceRequest,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    """Deliver a quote summary to the client by email and/or SMS."""
    quote = _get_quote_or_404(db, quote_id, current_user["account_id"])
    if quote["status"] in ("declined", "expired"):
        raise HTTPException(status_code=400, detail=f"Cannot send a {quote['status']} quote")

    channels = [c for c in body.channels if c in ("email", "sms")]
    if not channels:
        raise HTTPException(status_code=400, detail="No valid channels (email, sms)")

    business_name = current_user.get("username") or "Axon"
    total = float(quote["total"])
    quote_url = f"{APP_BASE_URL}/q/{quote['public_token']}" if quote.get("public_token") else None
    errors: list[str] = []
    sent: list[str] = []

    if "email" in channels:
        if not quote.get("client_email"):
            errors.append("No client email on file")
        else:
            try:
                send_quote_email(
                    to_email=quote["client_email"], business_name=business_name,
                    quote_number=quote["quote_number"], total=total,
                    valid_until=quote.get("valid_until"), quote_url=quote_url,
                )
                sent.append("email")
            except Exception as e:
                errors.append(f"Email: {e}")

    if "sms" in channels:
        if not quote.get("client_phone"):
            errors.append("No client phone on file")
        else:
            try:
                send_quote_sms(
                    to_phone=quote["client_phone"], business_name=business_name,
                    quote_number=quote["quote_number"], total=total, quote_url=quote_url,
                )
                sent.append("sms")
            except Exception as e:
                errors.append(f"SMS: {e}")

    if not sent:
        raise HTTPException(status_code=400, detail="; ".join(errors) or "Failed to send")

    first_send = quote["status"] == "draft"
    new_status = "sent" if first_send else quote["status"]
    with db.cursor() as cur:
        cur.execute(
            "UPDATE quotes SET status=%s, sent_at=COALESCE(sent_at, NOW()), sent_channels=%s, "
            "last_emailed_at = CASE WHEN %s THEN NOW() ELSE last_emailed_at END, "
            "last_sms_at     = CASE WHEN %s THEN NOW() ELSE last_sms_at END, "
            "updated_at=NOW() WHERE id=%s",
            (new_status, sent, "email" in sent, "sms" in sent, quote_id),
        )
        db.commit()

    if first_send:
        _fire_quote_event(db, quote, "sent")
        # Feedback loop (Phase 2): a quote actually going out is the richest
        # quote_sent signal — it carries the amount. A workflow rule that also
        # moves the lead to the quote_sent stage emits its own (amount-less)
        # event; the labeling job keys off the earliest, so the overlap is
        # harmless. Best-effort, and only when the quote is tied to a lead.
        if quote.get("property_id"):
            from api.lead_events_emit import emit_event
            emit_event(
                db, quote["property_id"], quote["account_id"], "quote_sent",
                actor_user_id=current_user["id"],
                metadata={"quote_amount": float(quote["total"]), "quote_id": quote_id},
            )

    return Quote(**_load_quote(db, quote_id))


@router.post("/quotes/{quote_id}/convert", response_model=Invoice, status_code=201)
def convert_quote(
    quote_id: int,
    body: ConvertQuoteRequest,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    """Mark the quote accepted and copy it into a fresh invoice.

    The invoice gets the next number from the invoice sequence (not the quote's
    number), so invoice numbering stays gapless for bookkeeping.
    """
    quote = _get_quote_or_404(db, quote_id, current_user["account_id"])
    if quote["converted_invoice_id"]:
        raise HTTPException(status_code=400, detail="Quote has already been converted")
    if quote["status"] in ("declined", "expired"):
        raise HTTPException(status_code=400, detail=f"Cannot convert a {quote['status']} quote")

    line_items = _load_quote(db, quote_id)["line_items"]
    if not line_items:
        raise HTTPException(status_code=400, detail="Quote has no line items")

    due_date = body.due_date or (datetime.date.today() + datetime.timedelta(days=30))

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO invoices (property_id, client_name, client_phone, client_email, client_address, "
            "tax_rate, subtotal, tax_amount, total, issue_date, due_date, notes, created_by, account_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (quote["property_id"], quote["client_name"], quote["client_phone"], quote["client_email"],
             quote["client_address"], quote["tax_rate"], quote["subtotal"], quote["tax_amount"],
             quote["total"], datetime.date.today(), due_date,
             f"From quote {quote['quote_number']}",
             current_user["id"], current_user["account_id"]),
        )
        invoice_id = cur.fetchone()[0]

        for li in line_items:
            cur.execute(
                "INSERT INTO invoice_line_items (invoice_id, description, quantity, unit_price, sort_order) "
                "VALUES (%s,%s,%s,%s,%s)",
                (invoice_id, li["description"], li["quantity"], li["unit_price"], li["sort_order"]),
            )

        cur.execute(
            "UPDATE quotes SET status='accepted', accepted_at=COALESCE(accepted_at, NOW()), "
            "converted_invoice_id=%s, updated_at=NOW() WHERE id=%s",
            (invoice_id, quote_id),
        )
        db.commit()

    if quote["status"] != "accepted":
        _fire_quote_event(db, quote, "accepted")

    return Invoice(**_load_invoice(db, invoice_id))


# ── Public (customer-facing) routes ───────────────────────────────────────────
# Addressed by unguessable token, no auth. Rate-limited per client IP. The
# payload is sanitized: no ids, no account/lead internals — only what a
# customer reading their own quote should see.

def _get_public_quote(db: PGConn, token: str) -> dict:
    with db.cursor() as cur:
        cur.execute(
            "SELECT q.*, a.name AS business_name FROM quotes q "
            "JOIN accounts a ON a.id = q.account_id WHERE q.public_token = %s",
            (token,),
        )
        quote = dict_fetchone(cur)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


def _expire_if_past_validity(db: PGConn, quote: dict) -> dict:
    """Lazily expire an open quote whose valid_until has passed."""
    if quote["status"] == "sent" and quote["valid_until"] and quote["valid_until"] < datetime.date.today():
        with db.cursor() as cur:
            cur.execute("UPDATE quotes SET status='expired', updated_at=NOW() WHERE id=%s", (quote["id"],))
            db.commit()
        quote["status"] = "expired"
    return quote


def _public_payload(db: PGConn, quote: dict) -> dict:
    with db.cursor() as cur:
        cur.execute(
            "SELECT description, quantity, unit_price, sort_order FROM quote_line_items "
            "WHERE quote_id = %s ORDER BY sort_order, id",
            (quote["id"],),
        )
        items = dict_fetchall(cur)
    for li in items:
        li["quantity"] = float(li["quantity"])
        li["unit_price"] = float(li["unit_price"])
        li["amount"] = round(li["quantity"] * li["unit_price"], 2)
    return {
        "quote_number": quote["quote_number"],
        "business_name": quote["business_name"],
        "client_name": quote["client_name"],
        "status": quote["status"],
        "subtotal": float(quote["subtotal"]),
        "tax_rate": float(quote["tax_rate"]),
        "tax_amount": float(quote["tax_amount"]),
        "total": float(quote["total"]),
        "issue_date": quote["issue_date"],
        "valid_until": quote["valid_until"],
        "notes": quote["notes"],
        "accepted_at": quote["accepted_at"],
        "declined_at": quote["declined_at"],
        "line_items": items,
    }


@public_router.get("/public/quotes/{token}")
def public_view_quote(token: str, request: Request, db: PGConn = Depends(get_db)):
    public_quote_limiter.check(client_ip(request))
    quote = _get_public_quote(db, token)
    quote = _expire_if_past_validity(db, quote)

    # First open stamps the read receipt.
    if not quote["viewed_at"]:
        with db.cursor() as cur:
            cur.execute("UPDATE quotes SET viewed_at = NOW() WHERE id = %s AND viewed_at IS NULL", (quote["id"],))
            db.commit()

    return _public_payload(db, quote)


@public_router.post("/public/quotes/{token}/accept")
def public_accept_quote(token: str, request: Request, db: PGConn = Depends(get_db)):
    public_quote_limiter.check(client_ip(request))
    quote = _get_public_quote(db, token)
    quote = _expire_if_past_validity(db, quote)

    if quote["status"] == "accepted":
        return _public_payload(db, quote)  # idempotent re-click
    if quote["status"] == "declined":
        raise HTTPException(status_code=409, detail="This quote was already declined — contact us to reopen it")
    if quote["status"] == "expired":
        raise HTTPException(status_code=410, detail="This quote has expired — contact us for an updated one")

    with db.cursor() as cur:
        cur.execute(
            "UPDATE quotes SET status='accepted', accepted_at=NOW(), updated_at=NOW() WHERE id=%s",
            (quote["id"],),
        )
        db.commit()
    quote["status"] = "accepted"

    _fire_quote_event(db, quote, "accepted")
    return _public_payload(db, _get_public_quote(db, token))


@public_router.post("/public/quotes/{token}/decline")
def public_decline_quote(token: str, body: PublicDeclineRequest, request: Request, db: PGConn = Depends(get_db)):
    public_quote_limiter.check(client_ip(request))
    quote = _get_public_quote(db, token)
    quote = _expire_if_past_validity(db, quote)

    if quote["status"] == "declined":
        return _public_payload(db, quote)  # idempotent re-click
    if quote["status"] == "accepted":
        raise HTTPException(status_code=409, detail="This quote was already accepted — contact us to make changes")

    reason = (body.reason or "").strip()[:1000] or None
    with db.cursor() as cur:
        cur.execute(
            "UPDATE quotes SET status='declined', declined_at=NOW(), decline_reason=%s, updated_at=NOW() WHERE id=%s",
            (reason, quote["id"]),
        )
        db.commit()
    quote["status"] = "declined"

    _fire_quote_event(db, quote, "declined")
    return _public_payload(db, _get_public_quote(db, token))
