"""Shared invoice payment-state logic.

Extracted from api/routes/invoices.py so non-router code (e.g. the Stripe
webhook handler) can recalculate invoice payment state without importing a
router module. The manual-payment routes and the Stripe webhook both funnel
through `_update_invoice_payment_state` after inserting an invoice_payments row.
"""
import datetime

from psycopg2.extensions import connection as PGConn

from api.deps import dict_fetchall, dict_fetchone


def _calc_totals(line_items: list, tax_rate: float) -> tuple[float, float, float]:
    subtotal = sum(item["quantity"] * item["unit_price"] for item in line_items)
    tax_amount = round(subtotal * tax_rate / 100, 2)
    total = round(subtotal + tax_amount, 2)
    return round(subtotal, 2), tax_amount, total


def _recalc_paid(db: PGConn, invoice_id: int) -> float:
    with db.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM invoice_payments WHERE invoice_id = %s",
            (invoice_id,),
        )
        return float(cur.fetchone()[0])


def _update_invoice_payment_state(db: PGConn, invoice_id: int):
    """Recalculate amount_paid and status after any payment change."""
    with db.cursor() as cur:
        cur.execute("SELECT total, due_date, status FROM invoices WHERE id = %s", (invoice_id,))
        row = cur.fetchone()
        if not row:
            return
        total, due_date, current_status = float(row[0]), row[1], row[2]

    amount_paid = _recalc_paid(db, invoice_id)

    if current_status == "void":
        new_status = "void"
    elif amount_paid >= total:
        new_status = "paid"
    elif amount_paid > 0:
        if due_date and due_date < datetime.date.today():
            new_status = "overdue"
        else:
            new_status = "partial"
    else:
        if due_date and due_date < datetime.date.today() and current_status in ("sent", "partial", "overdue"):
            new_status = "overdue"
        else:
            new_status = current_status if current_status in ("draft", "sent", "overdue") else "sent"

    with db.cursor() as cur:
        cur.execute(
            "UPDATE invoices SET amount_paid = %s, status = %s, updated_at = NOW() WHERE id = %s",
            (amount_paid, new_status, invoice_id),
        )


def _load_invoice(db: PGConn, invoice_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
        inv = dict_fetchone(cur)
        if not inv:
            return None
        cur.execute(
            "SELECT * FROM invoice_line_items WHERE invoice_id = %s ORDER BY sort_order, id",
            (invoice_id,),
        )
        inv["line_items"] = dict_fetchall(cur)
        cur.execute(
            "SELECT * FROM invoice_payments WHERE invoice_id = %s ORDER BY payment_date, id",
            (invoice_id,),
        )
        inv["payments"] = dict_fetchall(cur)
        # computed
        inv["balance_due"] = float(inv["total"]) - float(inv["amount_paid"])
        # enrich line items with amount
        for li in inv["line_items"]:
            li["amount"] = float(li["quantity"]) * float(li["unit_price"])
    return inv
