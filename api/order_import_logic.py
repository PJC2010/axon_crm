"""
Pure (no-DB) helpers for the retail orders import (Phase 8 — integrations).

Detects the columns of Square / Shopify order exports (and generic spreadsheets)
and normalizes each row into an order + the customer it belongs to. Kept free of
DB/FastAPI concerns so it's unit-testable like import_logic.py; the route in
api/routes/order_imports.py wires it into UploadFile parsing, the customer
upsert, and the orders insert.
"""
from __future__ import annotations

import re
from datetime import date, datetime

# Order fields an imported row may populate (orders table columns).
ORDER_FIELDS = ["order_number", "order_date", "total", "item_count", "channel", "status"]
# Customer identity used to find/create the linked record (properties columns).
CUSTOMER_FIELDS = ["contact_name", "contact_email", "contact_phone"]


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


# Shopify orders export headers.
SHOPIFY_ALIASES = {
    "name": "order_number",              # Shopify order name, e.g. "#1001"
    "email": "contact_email",
    "created at": "order_date",
    "total": "total",
    "financial status": "status",
    "billing name": "contact_name",
    "phone": "contact_phone",
    "lineitem quantity": "item_count",
}

# Square transactions/items export headers.
SQUARE_ALIASES = {
    "date": "order_date",
    "gross sales": "total",
    "net total": "total",
    "customer name": "contact_name",
    "customer email": "contact_email",
    "customer phone": "contact_phone",
    "transaction id": "order_number",
    "payment id": "order_number",
    "transaction status": "status",
    "item name": "__item__",
    "qty": "item_count",
    "quantity": "item_count",
}

# Generic spreadsheet headers.
GENERIC_ALIASES = {
    "order": "order_number",
    "order number": "order_number",
    "order id": "order_number",
    "order date": "order_date",
    "date": "order_date",
    "total": "total",
    "amount": "total",
    "order total": "total",
    "grand total": "total",
    "items": "item_count",
    "item count": "item_count",
    "quantity": "item_count",
    "channel": "channel",
    "source": "channel",
    "status": "status",
    "customer": "contact_name",
    "customer name": "contact_name",
    "name": "contact_name",
    "email": "contact_email",
    "customer email": "contact_email",
    "phone": "contact_phone",
    "customer phone": "contact_phone",
}


def detect_order_mapping(headers: list[str]) -> dict[str, str]:
    """Best-effort map of CSV header -> order/customer field.

    Shopify and Square aliases take precedence (more specific) over generic ones.
    A header like Shopify "Name" (the order number) must win over the generic
    "name"->contact_name, so vendor tables are checked first.
    """
    mapping: dict[str, str] = {}
    for header in headers:
        if header is None:
            continue
        k = _key(header)
        target = SHOPIFY_ALIASES.get(k) or SQUARE_ALIASES.get(k) or GENERIC_ALIASES.get(k)
        if target:
            mapping[header] = target
    return mapping


def _parse_money(value: str) -> float | None:
    """Parse a currency string ("$1,234.56", "1234.56", "(12.00)") to a float."""
    s = (value or "").strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return None
    try:
        amount = float(s)
    except ValueError:
        return None
    return -amount if negative and amount > 0 else amount


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value or "")
    return int(digits) if digits else None


def _parse_date(value: str) -> str | None:
    """Return an ISO date string from common export formats, else None."""
    s = (value or "").strip()
    if not s:
        return None
    # ISO timestamps ("2026-07-02T14:30:00-05:00") — take the leading date part.
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Month-name formats keep their spaces; slash/dash numeric formats take the
    # first whitespace-delimited token (drops any trailing time).
    token = s.split(" ")[0]
    for candidate, fmt in (
        (s, "%b %d, %Y"), (s, "%B %d, %Y"),
        (token, "%m/%d/%Y"), (token, "%m/%d/%y"),
        (token, "%Y/%m/%d"), (token, "%d/%m/%Y"),
    ):
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# Statuses that map to a completed sale vs. a refund/void (orders.status values).
_STATUS_MAP = {
    "paid": "completed", "completed": "completed", "complete": "completed",
    "fulfilled": "completed", "captured": "completed",
    "refunded": "refunded", "partially refunded": "refunded",
    "voided": "cancelled", "cancelled": "cancelled", "canceled": "cancelled",
    "pending": "pending", "authorized": "pending", "unpaid": "pending",
}


def normalize_order_row(raw: dict, mapping: dict[str, str]) -> dict:
    """Apply the mapping to one row and clean values into {order, customer}.

    Returns a dict with an ``order`` sub-dict (orders columns) and a ``customer``
    sub-dict (properties identity columns). Empty values are dropped.
    """
    order: dict = {}
    customer: dict = {}

    for header, target in mapping.items():
        val = (raw.get(header) or "").strip()
        if not val:
            continue
        if target == "total":
            amount = _parse_money(val)
            if amount is not None:
                order["total"] = amount
        elif target == "item_count":
            n = _parse_int(val)
            if n is not None:
                order["item_count"] = n
        elif target == "order_date":
            iso = _parse_date(val)
            if iso:
                order["order_date"] = iso
        elif target == "status":
            order["status"] = _STATUS_MAP.get(val.lower().strip(), "completed")
        elif target in ORDER_FIELDS and target not in order:
            order[target] = val
        elif target in CUSTOMER_FIELDS and target not in customer:
            customer[target] = val

    if "contact_email" in customer:
        customer["contact_email"] = customer["contact_email"].lower()

    return {"order": order, "customer": customer}


def order_row_is_usable(normalized: dict) -> bool:
    """Importable when the row is a real sale (has a total) attributable to a
    customer we can dedup on (an email). Rows without either are skipped."""
    order, customer = normalized["order"], normalized["customer"]
    return order.get("total") is not None and bool(customer.get("contact_email"))
