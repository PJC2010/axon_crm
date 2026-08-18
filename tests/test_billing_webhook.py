"""
Tests for the platform billing webhook handler (api/routes/billing.py) — the
path that turns Stripe subscription events into account_plans entitlements.
Same FakeConn style as tests/test_stripe_webhook.py: no database, every SQL
statement recorded, canned rows served by a router function.
"""
from api.routes.billing import _handle_event


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.executed.append((" ".join(sql.split()), params))
        self._rows = self.conn.route(" ".join(sql.split()))

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


def build_router(*, duplicate=False, prior_status=None, customer_known=True):
    def route(sql):
        if sql.startswith("INSERT INTO stripe_webhook_events"):
            return [] if duplicate else [(1,)]
        if sql.startswith("SELECT status FROM stripe_webhook_events"):
            return [(prior_status,)] if prior_status else []
        if sql.startswith("SELECT account_id FROM account_billing"):
            return [(3,)] if customer_known else []
        return []
    return route


def _billing_upserts(conn):
    return [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO account_billing")]


def _plan_upserts(conn):
    return [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO account_plans")]


def make_subscription_event(*, event_type="customer.subscription.updated",
                            status="active", price_id="price_p", metadata=None):
    return {
        "id": "evt_b1",
        "type": event_type,
        "data": {"object": {
            "id": "sub_1",
            "customer": "cus_1",
            "status": status,
            "cancel_at_period_end": False,
            "current_period_end": 1_900_000_000,
            "items": {"data": [{"price": {"id": price_id}}]},
            "metadata": metadata if metadata is not None else {"account_id": "3", "plan": "pro"},
        }},
    }


def _patch_prices(monkeypatch):
    import api.billing as b
    monkeypatch.setattr(b, "STRIPE_PRICE_STARTER", "price_s", raising=False)
    monkeypatch.setattr(b, "STRIPE_PRICE_GROWTH", "price_g", raising=False)
    monkeypatch.setattr(b, "STRIPE_PRICE_PRO", "price_p", raising=False)


def test_unresolvable_checkout_session_is_ignored_not_errored():
    # A session this deployment didn't create (shared Stripe account, Payment
    # Link, renamed plan) must not 500 forever on redelivery.
    conn = FakeConn(build_router(customer_known=False))
    event = {"id": "evt_b1", "type": "checkout.session.completed",
             "data": {"object": {"id": "cs_x", "mode": "subscription",
                                 "customer": "cus_unknown", "metadata": {}}}}
    assert _handle_event(conn, event) == "ignored"
    assert _billing_upserts(conn) == []
    assert conn.rollbacks == 0


def test_active_subscription_applies_plan(monkeypatch):
    _patch_prices(monkeypatch)
    conn = FakeConn(build_router())
    assert _handle_event(conn, make_subscription_event()) == "processed"
    (sql, params), = _billing_upserts(conn)
    assert "plan_name" in sql
    assert (plan_sql for plan_sql, _ in _plan_upserts(conn)), "entitlements applied"
    assert len(_plan_upserts(conn)) == 1


def test_unresolvable_price_does_not_null_plan_name(monkeypatch):
    # STRIPE_PRICE_* rotated in Stripe: plan resolves to None. The stored
    # plan_name must survive (no NULL overwrite) and entitlements must not
    # change — only a warning is logged.
    _patch_prices(monkeypatch)
    conn = FakeConn(build_router())
    event = make_subscription_event(price_id="price_rotated", metadata={"account_id": "3"})
    assert _handle_event(conn, event) == "processed"
    (sql, params), = _billing_upserts(conn)
    assert "plan_name" not in sql
    assert _plan_upserts(conn) == []


def test_deleted_subscription_downgrades_to_starter(monkeypatch):
    _patch_prices(monkeypatch)
    conn = FakeConn(build_router())
    event = make_subscription_event(event_type="customer.subscription.deleted",
                                    status="canceled")
    assert _handle_event(conn, event) == "processed"
    (sql, params), = _plan_upserts(conn)
    assert "starter" in params


def test_subscription_for_unknown_customer_is_ignored():
    conn = FakeConn(build_router(customer_known=False))
    event = make_subscription_event(metadata={})
    assert _handle_event(conn, event) == "ignored"
    assert _billing_upserts(conn) == []
