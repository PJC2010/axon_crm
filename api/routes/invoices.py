"""
GET    /api/invoices              — list (filters: status, year, month, property_id, page)
POST   /api/invoices              — create with line items
GET    /api/invoices/summary      — A/R overview totals
GET    /api/invoices/aging        — aging buckets
GET    /api/invoices/export       — CSV download
GET    /api/invoices/{id}         — single with line_items + payments
PATCH  /api/invoices/{id}         — update header + optionally replace line items
DELETE /api/invoices/{id}         — delete (owner only)
POST   /api/invoices/{id}/payments          — record payment
DELETE /api/invoices/{id}/payments/{pid}    — remove payment
"""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner
from api.invoice_logic import (
    _calc_totals, _recalc_paid, _update_invoice_payment_state, _load_invoice,
)
from api.notifications import send_invoice_email, send_invoice_sms
from api.models import (
    Invoice, InvoiceCreate, InvoiceUpdate,
    InvoicePayment, PaymentCreate, LineItem, SendInvoiceRequest,
    INVOICE_STATUSES, PAYMENT_METHODS,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────
# Payment-state helpers (_calc_totals, _recalc_paid, _update_invoice_payment_state,
# _load_invoice) live in api/invoice_logic.py so the Stripe webhook can reuse them.

def _build_where(account_id, status, year, month, property_id):
    conditions, params = ["account_id = %s"], [account_id]
    if status:
        conditions.append("status = %s"); params.append(status)
    if year:
        conditions.append("EXTRACT(YEAR FROM issue_date) = %s"); params.append(year)
    if month:
        conditions.append("EXTRACT(MONTH FROM issue_date) = %s"); params.append(month)
    if property_id is not None:
        conditions.append("property_id = %s"); params.append(property_id)
    where = "WHERE " + " AND ".join(conditions)
    return where, params


def _assert_invoice_account(db, invoice_id: int, account_id: int):
    """Raise 404 unless the invoice belongs to the caller's org."""
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM invoices WHERE id = %s AND account_id = %s", (invoice_id, account_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Invoice not found")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/invoices/summary")
def invoice_summary(
    year: Optional[int] = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    import datetime
    today = datetime.date.today()
    acct = user["account_id"]
    year_cond = "AND EXTRACT(YEAR FROM issue_date) = %s" if year else ""
    year_param = [year] if year else []

    with db.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(total),0), COUNT(*) FROM invoices WHERE account_id = %s AND status != 'void' {year_cond}",
            [acct] + year_param,
        )
        r = cur.fetchone()
        total_invoiced, invoice_count = float(r[0]), int(r[1])

        cur.execute(
            f"SELECT COALESCE(SUM(amount_paid),0) FROM invoices WHERE account_id = %s AND status != 'void' {year_cond}",
            [acct] + year_param,
        )
        total_collected = float(cur.fetchone()[0])

        cur.execute(
            f"SELECT COALESCE(SUM(total - amount_paid),0), COUNT(*) FROM invoices "
            f"WHERE account_id = %s AND status IN ('sent','partial','overdue') {year_cond}",
            [acct] + year_param,
        )
        r = cur.fetchone()
        total_outstanding, _ = float(r[0]), int(r[1])

        cur.execute(
            f"SELECT COALESCE(SUM(total - amount_paid),0), COUNT(*) FROM invoices "
            f"WHERE account_id = %s AND status IN ('sent','partial','overdue') AND due_date < %s {year_cond}",
            [acct, today] + year_param,
        )
        r = cur.fetchone()
        total_overdue, overdue_count = float(r[0]), int(r[1])

    return {
        "total_invoiced": total_invoiced,
        "total_collected": total_collected,
        "total_outstanding": total_outstanding,
        "total_overdue": total_overdue,
        "invoice_count": invoice_count,
        "overdue_count": overdue_count,
    }


@router.get("/invoices/aging")
def invoice_aging(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    # Bucket in SQL so only five rows cross the wire, however many invoices exist.
    with db.cursor() as cur:
        cur.execute(
            "SELECT CASE "
            "         WHEN due_date IS NULL OR due_date >= CURRENT_DATE THEN 'current' "
            "         WHEN CURRENT_DATE - due_date <= 30 THEN '1_30' "
            "         WHEN CURRENT_DATE - due_date <= 60 THEN '31_60' "
            "         WHEN CURRENT_DATE - due_date <= 90 THEN '61_90' "
            "         ELSE '90_plus' END AS bucket, "
            "       COUNT(*) AS count, "
            "       COALESCE(SUM(total - amount_paid), 0) AS amount "
            "FROM invoices "
            "WHERE account_id = %s AND status IN ('sent','partial','overdue') "
            "GROUP BY 1",
            (user["account_id"],),
        )
        rows = {bucket: (count, amount) for bucket, count, amount in cur.fetchall()}

    buckets = {
        "current":  {"label": "Current",   "count": 0, "amount": 0.0},
        "1_30":     {"label": "1–30 days",  "count": 0, "amount": 0.0},
        "31_60":    {"label": "31–60 days", "count": 0, "amount": 0.0},
        "61_90":    {"label": "61–90 days", "count": 0, "amount": 0.0},
        "90_plus":  {"label": "90+ days",   "count": 0, "amount": 0.0},
    }
    for key, (count, amount) in rows.items():
        buckets[key]["count"] = count
        buckets[key]["amount"] = float(amount)

    return list(buckets.values())


@router.get("/invoices/export")
def export_invoices(
    status: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    where, params = _build_where(user["account_id"], status, year, None, None)
    with db.cursor() as cur:
        cur.execute(
            f"SELECT invoice_number, client_name, issue_date, due_date, subtotal, tax_amount, total, amount_paid, "
            f"(total - amount_paid) AS balance_due, status FROM invoices {where} ORDER BY issue_date DESC",
            params,
        )
        rows = dict_fetchall(cur)

    output = io.StringIO()
    fields = ["invoice_number", "client_name", "issue_date", "due_date", "subtotal", "tax_amount", "total", "amount_paid", "balance_due", "status"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in fields})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=invoices_{year or 'all'}.csv"},
    )


@router.get("/invoices", response_model=dict)
def list_invoices(
    status: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    property_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    where, params = _build_where(user["account_id"], status, year, month, property_id)
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM invoices {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT *, (total - amount_paid) AS balance_due FROM invoices {where} "
            f"ORDER BY issue_date DESC, id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    items = []
    for r in rows:
        r["line_items"] = []
        r["payments"] = []
        r["balance_due"] = float(r["balance_due"])
        items.append(Invoice(**r).model_dump())

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/invoices", response_model=Invoice, status_code=201)
def create_invoice(
    body: InvoiceCreate,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    if not body.line_items:
        raise HTTPException(status_code=400, detail="At least one line item required")

    items_raw = [{"quantity": li.quantity, "unit_price": li.unit_price, "description": li.description, "sort_order": li.sort_order} for li in body.line_items]
    subtotal, tax_amount, total = _calc_totals(items_raw, body.tax_rate)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO invoices (property_id, client_name, client_phone, client_email, client_address, "
            "tax_rate, subtotal, tax_amount, total, issue_date, due_date, notes, created_by, account_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, invoice_number",
            (body.property_id, body.client_name, body.client_phone, body.client_email,
             body.client_address, body.tax_rate, subtotal, tax_amount, total,
             body.issue_date, body.due_date, body.notes, current_user["id"], current_user["account_id"]),
        )
        inv_row = cur.fetchone()
        inv_id, inv_num = inv_row[0], inv_row[1]

        for li in body.line_items:
            cur.execute(
                "INSERT INTO invoice_line_items (invoice_id, description, quantity, unit_price, sort_order) "
                "VALUES (%s,%s,%s,%s,%s)",
                (inv_id, li.description, li.quantity, li.unit_price, li.sort_order),
            )
        db.commit()

    inv = _load_invoice(db, inv_id)
    return Invoice(**inv)


@router.get("/invoices/{invoice_id}", response_model=Invoice)
def get_invoice(invoice_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    _assert_invoice_account(db, invoice_id, user["account_id"])
    inv = _load_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return Invoice(**inv)


@router.patch("/invoices/{invoice_id}", response_model=Invoice)
def update_invoice(
    invoice_id: int,
    body: InvoiceUpdate,
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM invoices WHERE id = %s AND account_id = %s", (invoice_id, user["account_id"]))
        existing = dict_fetchone(cur)
    if not existing:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if existing["status"] == "void":
        raise HTTPException(status_code=400, detail="Cannot edit a voided invoice")

    sets, params = ["updated_at = NOW()"], []
    for field in ("client_name", "client_phone", "client_email", "client_address", "due_date", "notes"):
        val = getattr(body, field)
        if val is not None:
            sets.append(f"{field} = %s"); params.append(val)
    if body.status is not None:
        if body.status not in INVOICE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        sets.append("status = %s"); params.append(body.status)
    if body.issue_date is not None:
        sets.append("issue_date = %s"); params.append(body.issue_date)

    # If line items provided, replace them and recalculate totals
    if body.line_items is not None:
        if not body.line_items:
            raise HTTPException(status_code=400, detail="At least one line item required")
        items_raw = [{"quantity": li.quantity, "unit_price": li.unit_price, "description": li.description, "sort_order": li.sort_order} for li in body.line_items]
        tax_rate = body.tax_rate if body.tax_rate is not None else float(existing["tax_rate"])
        subtotal, tax_amount, total = _calc_totals(items_raw, tax_rate)
        sets += ["tax_rate = %s", "subtotal = %s", "tax_amount = %s", "total = %s"]
        params += [tax_rate, subtotal, tax_amount, total]

        with db.cursor() as cur:
            cur.execute("DELETE FROM invoice_line_items WHERE invoice_id = %s", (invoice_id,))
            for li in body.line_items:
                cur.execute(
                    "INSERT INTO invoice_line_items (invoice_id, description, quantity, unit_price, sort_order) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (invoice_id, li.description, li.quantity, li.unit_price, li.sort_order),
                )
    elif body.tax_rate is not None:
        sets.append("tax_rate = %s"); params.append(body.tax_rate)

    params.append(invoice_id)
    with db.cursor() as cur:
        cur.execute(f"UPDATE invoices SET {', '.join(sets)} WHERE id = %s", params)
        db.commit()

    _update_invoice_payment_state(db, invoice_id)
    inv = _load_invoice(db, invoice_id)
    return Invoice(**inv)


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM invoices WHERE id = %s AND account_id = %s RETURNING id", (invoice_id, current_user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Invoice not found")


@router.post("/invoices/{invoice_id}/payments", response_model=InvoicePayment, status_code=201)
def record_payment(
    invoice_id: int,
    body: PaymentCreate,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    with db.cursor() as cur:
        cur.execute("SELECT id, total, status FROM invoices WHERE id = %s AND account_id = %s",
                    (invoice_id, current_user["account_id"]))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if row[2] == "void":
        raise HTTPException(status_code=400, detail="Cannot record payment on a voided invoice")
    if body.payment_method not in PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail=f"payment_method must be one of {PAYMENT_METHODS}")

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO invoice_payments (invoice_id, amount, payment_date, payment_method, notes, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
            (invoice_id, body.amount, body.payment_date, body.payment_method, body.notes, current_user["id"]),
        )
        payment_row = dict_fetchone(cur)
        db.commit()

    _update_invoice_payment_state(db, invoice_id)
    db.commit()
    return InvoicePayment(**payment_row)


@router.delete("/invoices/{invoice_id}/payments/{payment_id}", status_code=204)
def delete_payment(
    invoice_id: int,
    payment_id: int,
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    _assert_invoice_account(db, invoice_id, user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM invoice_payments WHERE id = %s AND invoice_id = %s RETURNING id",
            (payment_id, invoice_id),
        )
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Payment not found")

    _update_invoice_payment_state(db, invoice_id)
    db.commit()


@router.post("/invoices/{invoice_id}/send", response_model=Invoice)
def send_invoice(
    invoice_id: int,
    body: SendInvoiceRequest,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    """Deliver an invoice summary to the client by email and/or SMS."""
    _assert_invoice_account(db, invoice_id, current_user["account_id"])
    inv = _load_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv["status"] == "void":
        raise HTTPException(status_code=400, detail="Cannot send a voided invoice")

    channels = [c for c in body.channels if c in ("email", "sms")]
    if not channels:
        raise HTTPException(status_code=400, detail="No valid channels (email, sms)")

    business_name = current_user.get("username") or "Axon"
    amount_due = float(inv["balance_due"])
    errors: list[str] = []
    sent: list[str] = []

    if "email" in channels:
        if not inv.get("client_email"):
            errors.append("No client email on file")
        else:
            try:
                send_invoice_email(
                    to_email=inv["client_email"], business_name=business_name,
                    invoice_number=inv["invoice_number"], amount_due=amount_due,
                )
                sent.append("email")
            except Exception as e:
                errors.append(f"Email: {e}")

    if "sms" in channels:
        if not inv.get("client_phone"):
            errors.append("No client phone on file")
        else:
            try:
                send_invoice_sms(
                    to_phone=inv["client_phone"], business_name=business_name,
                    invoice_number=inv["invoice_number"], amount_due=amount_due,
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
