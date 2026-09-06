"""Tests for api/routes/admin_usage.py — per-org usage. Fake-conn style."""
import os

import psycopg2.errors
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

from api.routes.admin_usage import (  # noqa: E402
    SORTABLE, USAGE_COLUMNS, USAGE_METRICS, admin_account_usage, admin_usage,
    usage_metric_sql,
)
from tests.fakeconn import Conn, sql_matching  # noqa: E402

ACCOUNT_COLS = ["id", "name", "plan_name", "scoring_monthly_limit"]


def _script(messages_response=None):
    return [
        ("FROM accounts a LEFT JOIN account_plans p",
         (ACCOUNT_COLS, [(1, "Zed Plumbing", "pro", None), (2, "Acme Roofing", "starter", None)])),
        ("FROM prospect_pulls", (["account_id", "rentcast_requests"], [(1, 40)])),
        ("FROM scoring_reveals", (["account_id", "scoring_reveals"], [(2, 7)])),
        ("status = 'done'", (["account_id", "runs", "skip_traces"], [(1, 3, 120)])),
        ("FROM contact_history ch",
         messages_response or (["account_id", "sms_sent", "email_sent"], [(2, 5, 1)])),
        ("FROM calls", (["account_id", "calls", "call_minutes"], [(1, 9, 31)])),
        ("FROM tracking_numbers", (["account_id", "tracking_numbers_active"], [(1, 2)])),
        ("COUNT(DISTINCT zip)", (["account_id", "territories"], [(1, 4)])),
    ]


class TestMetricSql:
    def test_every_metric_groups_by_account_and_binds_by_name(self):
        for metric in USAGE_METRICS:
            listed = usage_metric_sql(metric, scoped=False)
            scoped = usage_metric_sql(metric, scoped=True)
            assert "GROUP BY" in listed and "account_id" in listed, metric
            assert "%(id)s" not in listed and "= %(id)s" in scoped, metric
            # Named params only — nothing positional to bind out of order.
            assert "%s" not in listed.replace("%(days)s", "").replace("%%", ""), metric

    def test_columns_and_sortable_agree(self):
        assert set(SORTABLE) == {c for cols in USAGE_COLUMNS.values() for c in cols}


class TestUsageList:
    def test_merges_sorts_and_reports_degraded_metrics(self):
        conn = Conn(_script(messages_response=psycopg2.errors.QueryCanceled()))
        page = admin_usage(days=30, sort="name", page=1, page_size=50, db=conn)
        assert [r["name"] for r in page["items"]] == ["Acme Roofing", "Zed Plumbing"]
        acme, zed = page["items"]
        assert zed["rentcast_requests"] == 40 and acme["rentcast_requests"] == 0
        assert acme["scoring_reveals"] == 7 and acme["scoring_limit"] == 25
        assert zed["scoring_limit"] is None                       # pro = unlimited
        assert acme["sms_sent"] is None and zed["email_sent"] is None  # "—", never 0
        assert page["degraded"] == ["messages"]
        assert conn.rollbacks == 1                                # the cancelled statement unwound
        assert page["total"] == 2 and page["columns"] == list(SORTABLE)

    def test_sorts_by_a_metric_descending(self):
        page = admin_usage(days=30, sort="rentcast_requests", page=1, page_size=50,
                           db=Conn(_script()))
        assert [r["name"] for r in page["items"]] == ["Zed Plumbing", "Acme Roofing"]

    def test_unknown_sort_is_400(self):
        with pytest.raises(HTTPException) as exc:
            admin_usage(days=30, sort="password", page=1, page_size=50, db=Conn(_script()))
        assert exc.value.status_code == 400

    def test_window_is_bound_not_interpolated(self):
        conn = Conn(_script())
        admin_usage(days=7, sort="name", page=1, page_size=50, db=conn)
        (sql, params), = sql_matching(conn, "FROM prospect_pulls")
        assert "%(days)s" in sql and "7" not in sql.replace("77", "")
        assert params["days"] == 7 and params["id"] is None


class TestAccountUsage:
    def test_scopes_every_metric_to_the_org(self):
        conn = Conn(_script())
        out = admin_account_usage(account_id=1, days=30, db=conn)
        metric_statements = [s for s, _ in conn.executed if "GROUP BY" in s]
        assert len(metric_statements) == len(USAGE_METRICS)
        assert all("= %(id)s" in s for s in metric_statements)
        assert out["metrics"]["name"] == "Zed Plumbing" and out["metrics"]["calls"] == 9
        assert out["degraded"] == []

    def test_unknown_account_is_404(self):
        conn = Conn([("FROM accounts a LEFT JOIN account_plans p", (ACCOUNT_COLS, []))])
        with pytest.raises(HTTPException) as exc:
            admin_account_usage(account_id=404, days=30, db=conn)
        assert exc.value.status_code == 404
