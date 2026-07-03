"""
Tests for the Stripe webhook handler (api/routes/stripe_payments.py) that run
without a database: a FakeConn records every statement and serves canned rows,
so idempotency, account verification, and the payment insert path are all
exercised as pure logic.
"""
from api.routes.stripe_payments import _handle_event

SA_COLS = ["id", "account_id", "stripe_account_id",
           "charges_enabled", "payouts_enabled", "details_submitted"]

SA_ROW = {"id": 1, "account_id": 3, "stripe_account_id": "acct_1",
          "charges_enabled": True, "payouts_enabled": True, "details_submitted": True}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.executed.append((" ".join(sql.split()), params))
        self._rows, self.description = self.conn.route(" ".join(sql.split()))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, router):
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self._router = router

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def route(self, sql):
        return self._router(sql)


def build_router(*, duplicate=False, prior_status=None, sa_row=SA_ROW, invoice_exists=True):
    def route(sql):
        if sql.startswith("INSERT INTO stripe_webhook_events"):
            return ([] if duplicate else [(1,)]), None
        if sql.startswith("SELECT status FROM stripe_webhook_events"):
            return ([(prior_status,)] if prior_status else []), None
        if "FROM stripe_accounts WHERE account_id" in sql:
            desc = [(c,) for c in SA_COLS]
            if sa_row is None:
                return [], desc
            return [tuple(sa_row[c] for c in SA_COLS)], desc
        if sql.startswith("SELECT 1 FROM invoices"):
            return ([(1,)] if invoice_exists else []), None
        # _update_invoice_payment_state internals:
        if sql.startswith("SELECT total, due_date, status FROM invoices"):
            return [(123.45, None, "sent")], None
        if "SUM(amount)" in sql:
            return [(123.45,)], None
        if sql.startswith("UPDATE stripe_accounts"):
            return [(1,)], None
        return [], None
    return route


def make_event(event_type="checkout.session.completed", account="acct_1", metadata="default"):
    obj = {"metadata": ({"invoice_id": "7", "account_id": "3", "pay_token": "tok"}
                        if metadata == "default" else metadata)}
    if event_type == "checkout.session.completed":
        obj.update({"amount_total": 12345, "payment_intent": "pi_1", "payment_status": "paid"})
    elif event_type == "payment_intent.succeeded":
        obj.update({"amount_received": 12345, "id": "pi_1", "latest_charge": "ch_1"})
    elif event_type == "account.updated":
        obj = {"id": account, "charges_enabled": True, "payouts_enabled": False,
               "details_submitted": True}
    return {"id": "evt_1", "type": event_type, "account": account, "data": {"object": obj}}


def _payment_inserts(conn):
    return [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO invoice_payments")]


def test_duplicate_event_short_circuits():
    conn = FakeConn(build_router(duplicate=True, prior_status="processed"))
    assert _handle_event(conn, make_event()) == "duplicate"
    assert _payment_inserts(conn) == []


def test_errored_event_is_retried():
    # A previous delivery failed mid-processing; the redelivery reprocesses it.
    conn = FakeConn(build_router(duplicate=True, prior_status="error"))
    assert _handle_event(conn, make_event()) == "processed"
    assert len(_payment_inserts(conn)) == 1


def test_mismatched_connected_account_is_rejected():
    # Metadata claims tenant 3, but the event arrived on an account that isn't
    # the one on file for tenant 3 → forged metadata must not record a payment.
    conn = FakeConn(build_router())
    assert _handle_event(conn, make_event(account="acct_evil")) == "error"
    assert _payment_inserts(conn) == []
    assert any("SET status" in s and p and p[0] == "error" for s, p in conn.executed)


def test_checkout_completed_records_payment_and_updates_state():
    conn = FakeConn(build_router())
    assert _handle_event(conn, make_event()) == "processed"

    (sql, params), = _payment_inserts(conn)
    assert "'stripe'" in sql
    # Dedupe across checkout.session.completed / payment_intent.succeeded rides
    # the partial unique index on the PaymentIntent id.
    assert "ON CONFLICT (stripe_payment_intent_id)" in sql
    assert 123.45 in params        # amount_total (cents) / 100
    assert "pi_1" in params
    # The shared payment-state recompute ran.
    assert any(s.startswith("UPDATE invoices SET amount_paid") for s, _ in conn.executed)


def test_payment_intent_succeeded_records_same_payment():
    conn = FakeConn(build_router())
    assert _handle_event(conn, make_event("payment_intent.succeeded")) == "processed"
    (sql, params), = _payment_inserts(conn)
    assert "pi_1" in params and "ch_1" in params


def test_event_without_our_metadata_is_ignored():
    conn = FakeConn(build_router())
    assert _handle_event(conn, make_event(metadata={})) == "ignored"
    assert _payment_inserts(conn) == []


def test_unknown_event_type_is_ignored():
    conn = FakeConn(build_router())
    assert _handle_event(conn, make_event("customer.created")) == "ignored"


def test_account_updated_refreshes_onboarding_flags():
    conn = FakeConn(build_router())
    assert _handle_event(conn, make_event("account.updated")) == "processed"
    updates = [(s, p) for s, p in conn.executed if s.startswith("UPDATE stripe_accounts")]
    assert len(updates) == 1
    assert updates[0][1][:3] == (True, False, True)
