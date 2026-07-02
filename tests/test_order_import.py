"""Tests for the retail orders import (Phase 8): pure column detection /
normalization for Square/Shopify/generic exports, and the commit route's
customer-upsert + order-dedup orchestration. Fake-conn, no live DB."""
import pytest

from api import order_import_logic as oil
from api.routes import order_imports as oi


# ── Pure detection & normalization ──────────────────────────────────────────────

class TestDetectMapping:
    def test_shopify_name_is_order_number_not_contact(self):
        m = oil.detect_order_mapping(["Name", "Email", "Total", "Created at", "Billing Name"])
        assert m["Name"] == "order_number"           # Shopify order name wins over generic "name"
        assert m["Email"] == "contact_email"
        assert m["Total"] == "total"
        assert m["Created at"] == "order_date"
        assert m["Billing Name"] == "contact_name"

    def test_square_headers(self):
        m = oil.detect_order_mapping(["Date", "Gross Sales", "Customer Name", "Customer Email", "Transaction ID"])
        assert m["Date"] == "order_date"
        assert m["Gross Sales"] == "total"
        assert m["Customer Email"] == "contact_email"
        assert m["Transaction ID"] == "order_number"

    def test_generic_headers(self):
        m = oil.detect_order_mapping(["Order Number", "Order Date", "Customer Email", "Amount", "Channel"])
        assert m["Order Number"] == "order_number"
        assert m["Amount"] == "total"
        assert m["Channel"] == "channel"

    def test_unknown_headers_dropped(self):
        assert "Notes" not in oil.detect_order_mapping(["Notes", "Total", "Email"])


class TestParsers:
    @pytest.mark.parametrize("raw,expected", [
        ("$1,234.56", 1234.56), ("1234.56", 1234.56), ("(12.00)", -12.0),
        ("", None), ("free", None), ("0", 0.0),
    ])
    def test_money(self, raw, expected):
        assert oil._parse_money(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("2026-07-02T14:30:00-05:00", "2026-07-02"),
        ("2026-07-02", "2026-07-02"),
        ("07/02/2026", "2026-07-02"),
        ("Jul 2, 2026", "2026-07-02"),
        ("not a date", None),
        ("", None),
    ])
    def test_date(self, raw, expected):
        assert oil._parse_date(raw) == expected


class TestNormalize:
    def test_splits_order_and_customer(self):
        mapping = {"Name": "order_number", "Email": "contact_email", "Total": "total",
                   "Created at": "order_date", "Financial Status": "status", "Billing Name": "contact_name"}
        raw = {"Name": "#1001", "Email": "JANE@X.com", "Total": "$84.50",
               "Created at": "2026-07-02 14:30", "Financial Status": "paid", "Billing Name": "Jane Doe"}
        n = oil.normalize_order_row(raw, mapping)
        assert n["order"] == {"order_number": "#1001", "total": 84.5,
                              "order_date": "2026-07-02", "status": "completed"}
        assert n["customer"] == {"contact_email": "jane@x.com", "contact_name": "Jane Doe"}

    def test_status_maps_refund(self):
        n = oil.normalize_order_row({"S": "Refunded", "T": "10", "E": "a@b.com"},
                                    {"S": "status", "T": "total", "E": "contact_email"})
        assert n["order"]["status"] == "refunded"

    def test_usable_requires_total_and_email(self):
        ok = oil.normalize_order_row({"T": "10", "E": "a@b.com"}, {"T": "total", "E": "contact_email"})
        assert oil.order_row_is_usable(ok)
        no_email = oil.normalize_order_row({"T": "10", "N": "Jane"}, {"T": "total", "N": "contact_name"})
        assert not oil.order_row_is_usable(no_email)
        no_total = oil.normalize_order_row({"E": "a@b.com"}, {"E": "contact_email"})
        assert not oil.order_row_is_usable(no_total)


# ── Commit orchestration ────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    def fetchone(self):
        return self._current[0] if self._current else None


class _Conn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []


class TestImportOne:
    def _norm(self, **over):
        base = {"customer": {"contact_email": "jane@x.com", "contact_name": "Jane Doe"},
                "order": {"order_number": "1001", "total": 84.5, "order_date": "2026-07-02",
                          "item_count": 3, "status": "completed"}}
        base.update(over)
        return base

    def test_upserts_customer_then_order(self):
        conn = _Conn([[(42,)], [(True,)]])   # customer RETURNING id, order RETURNING inserted
        cur = _Cursor(conn)
        inserted = oi._import_one(cur, 3, self._norm(), None, 9)
        assert inserted is True

        cust_sql, cust_params = conn.executed[0]
        assert "INSERT INTO properties" in cust_sql
        assert "ON CONFLICT (account_id, lower(contact_email))" in cust_sql
        assert cust_params[0] == 3 and cust_params[1] == "jane@x.com"

        order_sql, order_params = conn.executed[1]
        assert "INSERT INTO orders" in order_sql
        assert "ON CONFLICT (account_id, order_number)" in order_sql
        assert 42 in order_params            # linked to the customer record id
        assert 84.5 in order_params

    def test_reimport_updates_existing_order(self):
        conn = _Conn([[(42,)], [(False,)]])  # order already existed → xmax != 0
        assert oi._import_one(_Cursor(conn), 3, self._norm(), None, 9) is False

    def test_order_without_number_always_inserts(self):
        norm = self._norm()
        del norm["order"]["order_number"]
        conn = _Conn([[(42,)]])              # only the customer upsert returns
        cur = _Cursor(conn)
        assert oi._import_one(cur, 3, norm, "online", 9) is True
        order_sql, order_params = conn.executed[1]
        assert "ON CONFLICT" not in order_sql
        assert "online" in order_params      # default_channel applied
