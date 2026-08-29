"""Dashboard reads degrade instead of 500ing (api/deps.py::soft_query).

On 2026-08-29 /api/pipeline/analytics, /api/pipeline/alerts and
/api/property-data/non-residential each returned an unhandled 500 with a stack
trace when their scan hit DB_STATEMENT_TIMEOUT_MS. Nothing in api/ caught
QueryCanceled and no exception handler was registered, so a slow database cost
the operator the whole page rather than one number.

Three properties are pinned here, and each of them was a real bug on that day:

  * a cancelled statement leaves the transaction ABORTED, so without a rollback
    the FIRST timeout takes down the four queries behind it too;
  * the cap must be transaction-local, because these connections are pooled and
    a session-level SET would follow them into unrelated later requests;
  * only QueryCanceled degrades. A syntax error or a dropped connection is not
    a slow panel and must still surface.
"""
import psycopg2
import pytest

from api import deps


class _Cur:
    def __init__(self, owner, raises=None, result="ok"):
        self.owner, self.raises, self.result = owner, raises, result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.owner.statements.append((" ".join(str(sql).split()), params))
        if self.raises is not None and "set_config" not in str(sql):
            raise self.raises


class _Conn:
    """Records statements and rollbacks across every cursor it hands out."""

    def __init__(self, raises=None):
        self.statements = []
        self.rollbacks = 0
        self.raises = raises
        self.aborted = False

    def cursor(self):
        return _Cur(self, raises=self.raises)

    def rollback(self):
        self.rollbacks += 1
        self.aborted = False


def test_happy_path_returns_the_value_and_does_not_flag_degraded():
    db = _Conn()
    value, timed_out = deps.soft_query(db, lambda cur: 42, fallback=None)
    assert (value, timed_out) == (42, False)
    assert db.rollbacks == 0


def test_the_cap_is_transaction_local_and_bound():
    db = _Conn()
    deps.soft_query(db, lambda cur: None, fallback=None, timeout_ms=1234)
    sql, params = db.statements[0]
    assert "set_config" in sql and "statement_timeout" in sql
    # is_local => true. A session-level SET would leak onto the pooled
    # connection and silently cap unrelated later requests.
    assert "true" in sql.lower()
    assert params == ("1234",)
    # Bound, not interpolated.
    assert "1234" not in sql


def test_default_comes_from_config_not_the_global_backstop():
    from config import DASHBOARD_STATEMENT_TIMEOUT_MS, DB_STATEMENT_TIMEOUT_MS
    db = _Conn()
    deps.soft_query(db, lambda cur: None, fallback=None)
    assert db.statements[0][1] == (str(DASHBOARD_STATEMENT_TIMEOUT_MS),)
    assert DASHBOARD_STATEMENT_TIMEOUT_MS < DB_STATEMENT_TIMEOUT_MS, \
        "a panel budget that is not tighter than the global cap does nothing"


def test_zero_timeout_skips_the_cap_entirely():
    db = _Conn()
    deps.soft_query(db, lambda cur: 1, fallback=None, timeout_ms=0)
    assert db.statements == []


def test_query_canceled_returns_the_fallback_and_rolls_back():
    db = _Conn(raises=psycopg2.errors.QueryCanceled("canceling statement due to statement timeout"))
    sentinel = {"degraded": True}
    value, timed_out = deps.soft_query(
        db, lambda cur: cur.execute("SELECT slow()"), fallback=sentinel)
    assert timed_out is True
    assert value is sentinel
    # The rollback is the part that lets the caller keep going.
    assert db.rollbacks == 1


def test_a_later_read_still_works_after_one_times_out():
    """The regression that made a single slow panel a whole-endpoint 500."""
    class _Flaky(_Conn):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def cursor(self):
            self.calls += 1
            first = self.calls == 1
            return _Cur(self, raises=psycopg2.errors.QueryCanceled() if first else None)

    db = _Flaky()
    first, t1 = deps.soft_query(db, lambda cur: cur.execute("SELECT slow()"), fallback="FALLBACK")
    second, t2 = deps.soft_query(db, lambda cur: "real answer", fallback=None)
    assert (first, t1) == ("FALLBACK", True)
    assert (second, t2) == ("real answer", False)


@pytest.mark.parametrize("exc", [
    psycopg2.errors.SyntaxError("boom"),
    psycopg2.OperationalError("server closed the connection"),
    ValueError("a bug in the handler itself"),
])
def test_other_failures_are_not_swallowed(exc):
    """Degrading on anything other than a cancel would hide real breakage
    behind an empty panel."""
    db = _Conn(raises=exc)
    with pytest.raises(type(exc)):
        deps.soft_query(db, lambda cur: cur.execute("SELECT 1"), fallback="never")
    assert db.rollbacks == 0


# ── The endpoints actually use it ────────────────────────────────────────────

def test_analytics_reports_which_panels_degraded():
    import inspect
    from api.routes.pipeline import pipeline_analytics
    src = inspect.getsource(pipeline_analytics)
    assert "soft_query" in src
    assert '"degraded": degraded' in src
    # One budget per panel, not one for the endpoint: the win-rate count timing
    # out must not cost the funnel too.
    for panel in ("win_rate", "avg_cycle_time", "leads_won", "funnel",
                  "avg_days_per_stage"):
        assert f'_q("{panel}"' in src, f"{panel} is not individually degradable"


def test_alerts_reports_which_buckets_degraded():
    import inspect
    from api.routes.pipeline import pipeline_alerts
    src = inspect.getsource(pipeline_alerts)
    assert "soft_query" in src
    assert '"degraded": degraded' in src
    for bucket in ("stuck_deals", "overdue_followups", "cooling_leads"):
        assert f'_q("{bucket}"' in src, f"{bucket} is not individually degradable"


def test_non_residential_route_falls_back_to_an_empty_report():
    import inspect
    from api.routes.data_quality import property_data_non_residential
    src = inspect.getsource(property_data_non_residential)
    assert "soft_query" in src and "empty_report" in src


def test_empty_report_matches_the_real_report_shape():
    """A degraded payload the client cannot parse is still a broken panel."""
    from pipeline.property_audit import empty_report
    from pipeline.residential import ALL_REASONS
    r = empty_report(account_id=1, zip_code="77396")
    for key in ("properties", "unclassified", "rule_stale", "flagged",
                "excludable", "by_reason", "samples", "by_zip",
                "spend_at_risk", "protected", "already_archived", "scope"):
        assert key in r, f"degraded report is missing {key}"
    assert r["degraded"] is True
    assert set(r["by_reason"]) == set(ALL_REASONS)
    assert r["scope"] == {"zip": "77396"}


def test_the_cap_is_handed_back_after_a_successful_read():
    """SET LOCAL lasts the whole transaction, and the endpoints run more than
    their degradable reads on it — /api/pipeline/alerts then runs the scoring
    quota masker, which must never fail open and is deliberately not wrapped.
    Leaving the 5s panel budget in force would put it under a cap it was not
    designed for."""
    from config import DB_STATEMENT_TIMEOUT_MS
    db = _Conn()
    deps.soft_query(db, lambda cur: "value", fallback=None, timeout_ms=5000)
    caps = [p for sql, p in db.statements if "set_config" in sql]
    assert caps == [("5000",), (str(DB_STATEMENT_TIMEOUT_MS),)], caps


def test_the_reset_is_not_attempted_on_an_aborted_transaction():
    """A `finally` here would issue SQL on an ABORTED transaction and raise
    InFailedSqlTransaction over the top of the QueryCanceled we need to catch —
    turning the degraded panel back into the 500 this function prevents."""
    class _Aborting(_Conn):
        def cursor(self):
            conn = self

            class _C(_Cur):
                def execute(self, sql, params=None):
                    conn.statements.append((" ".join(str(sql).split()), params))
                    if conn.aborted:
                        raise psycopg2.errors.InFailedSqlTransaction(
                            "current transaction is aborted")
                    if "set_config" not in str(sql):
                        conn.aborted = True
                        raise psycopg2.errors.QueryCanceled()
            return _C(conn)

    db = _Aborting()
    value, timed_out = deps.soft_query(
        db, lambda cur: cur.execute("SELECT slow()"), fallback="FALLBACK")
    assert (value, timed_out) == ("FALLBACK", True)
    assert db.rollbacks == 1
