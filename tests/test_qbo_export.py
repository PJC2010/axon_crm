"""Tests for the QuickBooks Online export shaping (api/qbo_export.py) — pure,
no DB. Row-per-line-item grouping by InvoiceNo, tax reconciliation line, and
the 3-column bank format for expenses."""
from datetime import date

from api.qbo_export import (
    QBO_EXPENSE_COLS, QBO_INVOICE_COLS, expense_rows, invoice_rows, qbo_date,
)


def _invoice(**overrides):
    inv = {
        "id": 7,
        "invoice_number": "INV-2026-0042",
        "client_name": "Danny Alvarez",
        "client_email": "danny@example.com",
        "client_address": "18 Spring Cypress Rd",
        "issue_date": date(2026, 7, 1),
        "due_date": date(2026, 7, 15),
        "notes": "Net 14\nthanks!",
        "subtotal": 5000,
        "tax_rate": 8.25,
        "tax_amount": 412.50,
        "total": 5412.50,
        "items": [
            {"description": "Pressure wash driveway", "quantity": 1, "unit_price": 3800},
            {"description": "Fence section repair", "quantity": 3, "unit_price": 400},
        ],
    }
    inv.update(overrides)
    return inv


def test_one_row_per_line_item_plus_tax_line():
    rows = invoice_rows([_invoice()])
    assert len(rows) == 3  # two items + sales-tax reconciliation line
    assert all(r["InvoiceNo"] == "INV-2026-0042" for r in rows)
    assert rows[0]["ItemAmount"] == "3800.00"
    assert rows[1]["ItemQuantity"] == "3"
    assert rows[1]["ItemAmount"] == "1200.00"
    assert rows[2]["ItemDescription"].startswith("Sales tax")
    assert rows[2]["ItemAmount"] == "412.50"
    # Line amounts sum to the invoice total, so the imported invoice reconciles.
    assert sum(float(r["ItemAmount"]) for r in rows) == 5412.50
    # Newlines in memos would break the CSV row shape.
    assert "\n" not in rows[0]["Memo"]
    # Every emitted key must be a declared column (extras get dropped silently).
    assert set(rows[0]) <= set(QBO_INVOICE_COLS)


def test_invoice_without_items_still_exports():
    rows = invoice_rows([_invoice(items=[], tax_amount=0)])
    assert len(rows) == 1
    assert rows[0]["ItemDescription"] == "Invoice total"
    assert rows[0]["ItemAmount"] == "5000.00"


def test_due_date_falls_back_to_issue_date():
    rows = invoice_rows([_invoice(due_date=None, tax_amount=0)])
    assert rows[0]["DueDate"] == "7/1/2026"


def test_qbo_date_accepts_iso_strings_and_none():
    assert qbo_date("2026-12-05") == "12/5/2026"
    assert qbo_date(None) == ""
    assert qbo_date(date(2026, 1, 31)) == "1/31/2026"


def test_expense_rows_negative_amounts_and_packed_description():
    rows = expense_rows([
        {"expense_date": date(2026, 6, 3), "vendor": "Home Depot",
         "description": "PVC + fittings", "category": "materials", "amount": 184.72},
        {"expense_date": "2026-06-04", "vendor": "", "description": "", "category": "",
         "amount": 60},
    ])
    assert rows[0] == {
        "Date": "6/3/2026",
        "Description": "Home Depot — PVC + fittings (materials)",
        "Amount": "-184.72",
    }
    assert rows[1]["Description"] == "Expense"
    assert rows[1]["Amount"] == "-60.00"
    assert set(rows[0]) == set(QBO_EXPENSE_COLS)
