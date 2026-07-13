"""QuickBooks Online import-format rows for invoices and expenses.

Pure and DB-free (same testability split as api/invoice_logic.py): the export
routes fetch rows and hand plain dicts here; this module only shapes them into
what QBO's CSV importers expect. See tests/test_qbo_export.py.

Prospective-user audit P1: a switcher's bookkeeper vetoes any tool that traps
financial data — one-way CSV export in QBO's own import formats is the
table-stakes escape hatch (API sync can come later).

Formats targeted:
  * Invoices — QBO's "Import invoices" CSV: one row per line item, rows sharing
    an InvoiceNo become one invoice. Required columns: InvoiceNo, Customer,
    InvoiceDate, DueDate, ItemAmount.
  * Expenses — QBO's 3-column bank/credit-card transaction CSV (Date,
    Description, Amount) with money-out as negative amounts. Bank format has no
    category column, so the category rides in the description.
"""
from datetime import date, datetime

QBO_INVOICE_COLS = [
    "InvoiceNo", "Customer", "InvoiceDate", "DueDate", "Email", "BillingAddress",
    "Memo", "ItemDescription", "ItemQuantity", "ItemRate", "ItemAmount",
]

QBO_EXPENSE_COLS = ["Date", "Description", "Amount"]


def qbo_date(value) -> str:
    """QBO's default expected date shape: M/D/YYYY (no leading zeros needed,
    but they're accepted). Accepts date/datetime or ISO strings; empty for None."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, (date, datetime)):
        return f"{value.month}/{value.day}/{value.year}"
    return str(value)


def _money(value) -> str:
    if value is None:
        return ""
    return f"{float(value):.2f}"


def invoice_rows(invoices: list[dict]) -> list[dict]:
    """Flatten invoices (each carrying an ``items`` list) into QBO import rows.

    One row per line item; invoice-level fields repeat on every row (QBO groups
    by InvoiceNo). When the invoice carries sales tax, a final "Sales tax" line
    is appended so the imported invoice's total reconciles with Axon's — QBO's
    CSV importer has no reliable tax-rate column across regions.

    An invoice with no line items still exports as a single row carrying its
    total, so nothing silently disappears from the books.
    """
    rows: list[dict] = []
    for inv in invoices:
        base = {
            "InvoiceNo": inv.get("invoice_number") or str(inv.get("id", "")),
            "Customer": inv.get("client_name") or "Unknown customer",
            "InvoiceDate": qbo_date(inv.get("issue_date")),
            "DueDate": qbo_date(inv.get("due_date") or inv.get("issue_date")),
            "Email": inv.get("client_email") or "",
            "BillingAddress": inv.get("client_address") or "",
            "Memo": (inv.get("notes") or "").replace("\n", " ").strip(),
        }
        items = inv.get("items") or []
        for item in items:
            qty = float(item.get("quantity") or 1)
            rate = float(item.get("unit_price") or 0)
            rows.append({
                **base,
                "ItemDescription": item.get("description") or "Service",
                "ItemQuantity": f"{qty:g}",
                "ItemRate": _money(rate),
                "ItemAmount": _money(qty * rate),
            })
        if not items:
            rows.append({
                **base,
                "ItemDescription": "Invoice total",
                "ItemQuantity": "1",
                "ItemRate": _money(inv.get("subtotal") or inv.get("total")),
                "ItemAmount": _money(inv.get("subtotal") or inv.get("total")),
            })
        tax = float(inv.get("tax_amount") or 0)
        if tax > 0:
            rows.append({
                **base,
                "ItemDescription": f"Sales tax ({float(inv.get('tax_rate') or 0):g}%)",
                "ItemQuantity": "1",
                "ItemRate": _money(tax),
                "ItemAmount": _money(tax),
            })
    return rows


def expense_rows(expenses: list[dict]) -> list[dict]:
    """Shape expenses into QBO's 3-column bank-transaction CSV.

    Amounts are negative (money out). Description packs vendor + memo +
    category so the bookkeeper can categorize on QBO's side in one pass.
    """
    rows: list[dict] = []
    for exp in expenses:
        vendor = (exp.get("vendor") or "").strip()
        desc = (exp.get("description") or "").strip()
        category = (exp.get("category") or "").strip()
        parts = [p for p in (vendor, desc) if p]
        label = " — ".join(parts) if parts else "Expense"
        if category:
            label += f" ({category})"
        amount = float(exp.get("amount") or 0)
        rows.append({
            "Date": qbo_date(exp.get("expense_date")),
            "Description": label,
            "Amount": f"{-abs(amount):.2f}",
        })
    return rows
