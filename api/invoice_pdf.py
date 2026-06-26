"""Professional invoice PDF rendering.

Renders an invoice dict (as produced by ``api.invoice_logic._load_invoice``) into
a print-ready PDF using fpdf2 — a pure-Python library with no system
dependencies, so it builds cleanly on Render. The bytes it returns are streamed
for download (GET /api/invoices/{id}/pdf), attached to the delivery email, and
served at the public link a delivery SMS points to.

Layout is a single self-contained template: business header, bill-to / invoice
meta columns, a line-items table, a totals panel, optional notes, and a footer.
Only the built-in Helvetica core font is used so no font files need to ship.
"""
from __future__ import annotations

import datetime

from fpdf import FPDF

# Brand palette — the ocean/teal the app and quote emails already use.
INK = (26, 26, 26)
MUTED = (120, 120, 120)
ACCENT = (26, 90, 117)        # #1a5a75
LINE = (224, 224, 224)
PANEL = (245, 247, 248)

# Status pill colors (fill, text) keyed by invoice status.
STATUS_COLORS = {
    "draft":   ((237, 237, 237), (90, 90, 90)),
    "sent":    ((222, 236, 242), (26, 90, 117)),
    "partial": ((247, 240, 222), (150, 110, 30)),
    "paid":    ((226, 240, 230), (40, 120, 70)),
    "overdue": ((247, 226, 226), (180, 60, 60)),
    "void":    ((237, 237, 237), (150, 150, 150)),
}


# The built-in Helvetica core font only covers latin-1. Map the punctuation
# that realistically shows up (smart quotes, dashes, bullets) and drop anything
# else to a "?" so user-entered notes/descriptions can never crash rendering.
_UNICODE_MAP = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "•": "-", "…": "...", " ": " ",
}


def _s(text) -> str:
    if text is None:
        return ""
    text = str(text)
    for bad, good in _UNICODE_MAP.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def _money(n) -> str:
    return f"${float(n or 0):,.2f}"


def _fmt_date(d) -> str:
    if d is None:
        return "-"
    if isinstance(d, str):
        try:
            d = datetime.date.fromisoformat(d[:10])
        except ValueError:
            return d
    return d.strftime("%b %d, %Y")


class _InvoicePDF(FPDF):
    """FPDF subclass that paints a consistent footer on every page."""

    business_name = "Axon"

    def footer(self):
        self.set_y(-16)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-13)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _s(f"Thank you for your business - {self.business_name}"), align="C")


def build_invoice_pdf(invoice: dict, business_name: str) -> bytes:
    """Render ``invoice`` to PDF bytes. ``invoice`` is a loaded invoice dict
    (line_items each carry ``amount``; ``balance_due`` is precomputed)."""
    business_name = (business_name or "Axon").strip() or "Axon"

    pdf = _InvoicePDF(orientation="P", unit="mm", format="Letter")
    pdf.business_name = business_name
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    content_w = pdf.w - pdf.l_margin - pdf.r_margin

    # ── Header: business name (left) + INVOICE block (right) ──────────────────
    top = pdf.get_y()
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*INK)
    pdf.cell(content_w * 0.55, 9, _s(business_name)[:40])

    pdf.set_xy(pdf.l_margin + content_w * 0.55, top)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(*ACCENT)
    pdf.cell(content_w * 0.45, 9, "INVOICE", align="R")

    pdf.set_xy(pdf.l_margin + content_w * 0.55, top + 10)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(content_w * 0.45, 5, _s(invoice["invoice_number"]), align="R")

    pdf.ln(16)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    # ── Bill-to (left) + meta (right) ─────────────────────────────────────────
    block_top = pdf.get_y()
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(content_w * 0.6, 5, "BILL TO")

    pdf.set_xy(pdf.l_margin, block_top + 5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(content_w * 0.6, 6, _s(invoice["client_name"])[:50])

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    detail_lines = [
        invoice.get("client_address"),
        invoice.get("client_phone"),
        invoice.get("client_email"),
    ]
    y = block_top + 11
    for line in detail_lines:
        if not line:
            continue
        pdf.set_xy(pdf.l_margin, y)
        pdf.cell(content_w * 0.6, 5, _s(line)[:60])
        y += 5

    # Meta column (right): issue / due dates + status pill.
    meta_x = pdf.l_margin + content_w * 0.6
    meta_w = content_w * 0.4
    rows = [("Issue Date", _fmt_date(invoice["issue_date"])),
            ("Due Date", _fmt_date(invoice.get("due_date")))]
    my = block_top
    for label, value in rows:
        pdf.set_xy(meta_x, my)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(meta_w * 0.5, 5, label)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        pdf.cell(meta_w * 0.5, 5, value, align="R")
        my += 6

    # Status pill.
    status = (invoice.get("status") or "draft").lower()
    fill, text = STATUS_COLORS.get(status, STATUS_COLORS["draft"])
    label = status.upper()
    pdf.set_font("Helvetica", "B", 8)
    pill_w = pdf.get_string_width(label) + 8
    pdf.set_xy(meta_x + meta_w - pill_w, my + 1)
    pdf.set_fill_color(*fill)
    pdf.set_text_color(*text)
    pdf.cell(pill_w, 6, label, align="C", fill=True)

    pdf.set_y(max(y, my) + 8)

    # ── Line-items table ──────────────────────────────────────────────────────
    desc_w = content_w * 0.52
    qty_w = content_w * 0.12
    price_w = content_w * 0.18
    amt_w = content_w * 0.18

    pdf.set_fill_color(*ACCENT)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(desc_w, 8, "  Description", fill=True)
    pdf.cell(qty_w, 8, "Qty", align="C", fill=True)
    pdf.cell(price_w, 8, "Unit Price", align="R", fill=True)
    pdf.cell(amt_w, 8, "Amount  ", align="R", fill=True)
    pdf.ln(8)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*INK)
    for i, li in enumerate(invoice.get("line_items", [])):
        qty = float(li.get("quantity", 0) or 0)
        unit = float(li.get("unit_price", 0) or 0)
        amount = float(li.get("amount", qty * unit))
        if i % 2:
            pdf.set_fill_color(*PANEL)
            fill = True
        else:
            fill = False
        row_h = 7
        start_x, start_y = pdf.get_x(), pdf.get_y()
        # Description may wrap; render it first to learn the row height.
        pdf.multi_cell(desc_w, row_h, "  " + _s(li.get("description", ""))[:120],
                       fill=fill, border=0)
        row_h = max(row_h, pdf.get_y() - start_y)
        pdf.set_xy(start_x + desc_w, start_y)
        pdf.cell(qty_w, row_h, f"{qty:g}", align="C", fill=fill)
        pdf.cell(price_w, row_h, _money(unit), align="R", fill=fill)
        pdf.cell(amt_w, row_h, _money(amount) + "  ", align="R", fill=fill)
        pdf.ln(row_h)

    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)

    # ── Totals panel (right-aligned) ──────────────────────────────────────────
    paid = float(invoice.get("amount_paid", 0) or 0)
    balance = float(invoice.get("balance_due", float(invoice["total"]) - paid))
    totals = [("Subtotal", _money(invoice["subtotal"]), False)]
    if float(invoice.get("tax_rate", 0) or 0) > 0:
        totals.append((f"Tax ({float(invoice['tax_rate']):g}%)", _money(invoice["tax_amount"]), False))
    totals.append(("Total", _money(invoice["total"]), True))
    if paid > 0:
        totals.append(("Paid", "-" + _money(paid), False))
        totals.append(("Balance Due", _money(balance), True))

    panel_w = content_w * 0.42
    panel_x = pdf.w - pdf.r_margin - panel_w
    for label, value, strong in totals:
        pdf.set_x(panel_x)
        if strong:
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*INK)
            pdf.set_draw_color(*LINE)
            pdf.line(panel_x, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(1.5)
            pdf.set_x(panel_x)
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*MUTED)
        pdf.cell(panel_w * 0.55, 7, label)
        pdf.cell(panel_w * 0.45, 7, value, align="R")
        pdf.ln(7)

    # ── Notes ─────────────────────────────────────────────────────────────────
    if invoice.get("notes"):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(content_w, 5, "NOTES")
        pdf.ln(5)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*INK)
        pdf.multi_cell(content_w, 5, _s(invoice["notes"]))

    out = pdf.output()
    return bytes(out)
