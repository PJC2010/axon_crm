"""Tests for invoice PDF rendering (api/invoice_pdf.py). No DB or network needed."""
import datetime

import pytest

from api.invoice_pdf import build_invoice_pdf, _s


def _sample(**overrides) -> dict:
    inv = {
        "invoice_number": "INV-2026-0042",
        "client_name": "Maria Gonzalez",
        "client_address": "123 Oak St, Houston, TX 77002",
        "client_phone": "(713) 555-0199",
        "client_email": "maria@example.com",
        "status": "partial",
        "issue_date": datetime.date(2026, 6, 1),
        "due_date": datetime.date(2026, 7, 1),
        "subtotal": 2400.0,
        "tax_rate": 8.25,
        "tax_amount": 198.0,
        "total": 2598.0,
        "amount_paid": 1000.0,
        "balance_due": 1598.0,
        "notes": "Payment due within 30 days.",
        "line_items": [
            {"description": "Roof tear-off", "quantity": 1, "unit_price": 800.0, "amount": 800.0},
            {"description": "Shingles", "quantity": 30, "unit_price": 45.0, "amount": 1350.0},
        ],
    }
    inv.update(overrides)
    return inv


def test_build_invoice_pdf_returns_pdf_bytes():
    pdf = build_invoice_pdf(_sample(), "Axon Roofing")
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_handles_missing_optional_fields():
    inv = _sample(
        due_date=None, client_address=None, client_phone=None,
        client_email=None, notes=None, amount_paid=0.0, balance_due=2598.0,
        tax_rate=0.0, tax_amount=0.0,
    )
    pdf = build_invoice_pdf(inv, "Axon")
    assert pdf.startswith(b"%PDF-")


def test_string_dates_are_accepted():
    inv = _sample(issue_date="2026-06-01", due_date="2026-07-01")
    pdf = build_invoice_pdf(inv, "Axon")
    assert pdf.startswith(b"%PDF-")


def test_blank_business_name_falls_back():
    pdf = build_invoice_pdf(_sample(), "   ")
    assert pdf.startswith(b"%PDF-")


def test_unicode_in_user_text_does_not_crash():
    # Smart quotes, em-dash, and an emoji in customer-entered fields must render.
    inv = _sample(
        client_name="José “JJ” O’Brien — Café",
        notes="Net-30 — thanks! 🙂",
        line_items=[{"description": "Tile — 12”×12”", "quantity": 5, "unit_price": 10.0, "amount": 50.0}],
    )
    pdf = build_invoice_pdf(inv, "Açaí Builders — LLC")
    assert pdf.startswith(b"%PDF-")


@pytest.mark.parametrize("status", ["draft", "sent", "partial", "paid", "overdue", "void", "weird"])
def test_all_statuses_render(status):
    pdf = build_invoice_pdf(_sample(status=status), "Axon")
    assert pdf.startswith(b"%PDF-")


def test_sanitizer_maps_punctuation_to_latin1():
    out = _s("“quote” — bullet • ellipsis…")
    assert out == '"quote" - bullet - ellipsis...'
    # Anything truly outside latin-1 degrades to "?" rather than raising.
    assert _s("🙂") == "?"
    assert _s(None) == ""
