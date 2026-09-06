"""Per-org usage — what each tenant costs the platform. Deliberately CROSS-TENANT.

The same reviewed exemption from the account_id-scoping rule as
api/routes/admin.py (CLAUDE.md): this router serves the platform operator, is
included in api/main.py with the router-wide require_platform_admin guard, and
tests/test_router_gating.py asserts that guard for every router serving /admin.
No endpoint here may declare a query param named ``token``.

GET /admin/usage                 — every org's cost drivers over a window, sorted
GET /admin/accounts/{id}/usage   — one org's cost drivers over a window

Every metric is one GROUP BY account_id read under api/deps.py::soft_query, so
a slow one (contact_history has no created_at index) costs its own column and
nothing else; the response's ``degraded`` list names what was cut off and the
client renders those as "—", never 0. Sorting and paging happen in Python over
one row per org — fine to a few thousand orgs, which is this product's horizon.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn

from api.admin_logic import clamp_page, merge_usage, paginate_rows, sort_usage
from api.deps import dict_fetchall, get_db, soft_query
from api.entitlements import PLAN_SCORING_LIMITS
from api.territory import RUN_ZIP_SQL

log = logging.getLogger(__name__)
router = APIRouter()

# Rolling window, bound by name: every template shares it, and psycopg2 ignores
# named params a statement does not use, so one dict serves them all.
_WINDOW = "NOW() - make_interval(days => %(days)s)"

# metric -> (SQL template, account column, value columns). ``{scope}`` becomes
# "AND <account column> = %(id)s" for the per-org endpoint and "" for the list.
# Nothing the client sends is ever interpolated — days and id are bound.
USAGE_METRICS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "rentcast_requests": (
        "SELECT account_id, COALESCE(SUM(api_requests), 0)::bigint AS rentcast_requests "
        f"FROM prospect_pulls WHERE pulled_at > {_WINDOW} {{scope}} GROUP BY account_id",
        "account_id", ("rentcast_requests",)),
    # The reveal ledger is monthly by construction (scoring_quota), so this one
    # reads the current calendar month rather than the window.
    "scoring_reveals": (
        "SELECT account_id, COUNT(*)::bigint AS scoring_reveals FROM scoring_reveals "
        "WHERE month = date_trunc('month', CURRENT_DATE)::date {scope} GROUP BY account_id",
        "account_id", ("scoring_reveals",)),
    "runs": (
        "SELECT account_id, COUNT(*)::bigint AS runs, "
        "COALESCE(SUM(COALESCE((result_json->'summary'->>'skip_traces_used')::int, 0)), 0)"
        "::bigint AS skip_traces "
        f"FROM pipeline_runs WHERE created_at > {_WINDOW} AND status = 'done' {{scope}} "
        "GROUP BY account_id",
        "account_id", ("runs", "skip_traces")),
    "messages": (
        "SELECT p.account_id, "
        "COUNT(*) FILTER (WHERE ch.channel = 'sms')::bigint AS sms_sent, "
        "COUNT(*) FILTER (WHERE ch.channel = 'email')::bigint AS email_sent "
        "FROM contact_history ch JOIN properties p ON p.id = ch.property_id "
        f"WHERE ch.direction = 'outbound' AND ch.created_at > {_WINDOW} {{scope}} "
        "GROUP BY p.account_id",
        "p.account_id", ("sms_sent", "email_sent")),
    "calls": (
        "SELECT account_id, COUNT(*)::bigint AS calls, "
        "(COALESCE(SUM(duration_seconds), 0) / 60)::bigint AS call_minutes "
        f"FROM calls WHERE started_at > {_WINDOW} {{scope}} GROUP BY account_id",
        "account_id", ("calls", "call_minutes")),
    # Each active row is a recurring Twilio charge, whatever the window.
    "tracking_numbers": (
        "SELECT account_id, COUNT(*)::bigint AS tracking_numbers_active "
        "FROM tracking_numbers WHERE status = 'active' {scope} GROUP BY account_id",
        "account_id", ("tracking_numbers_active",)),
    "territories": (
        "SELECT account_id, COUNT(DISTINCT zip)::bigint AS territories FROM pipeline_runs "
        f"WHERE created_at > {_WINDOW} AND {RUN_ZIP_SQL} {{scope}} GROUP BY account_id",
        "account_id", ("territories",)),
}

USAGE_COLUMNS: dict[str, tuple[str, ...]] = {
    name: cols for name, (_, _, cols) in USAGE_METRICS.items()
}
SORTABLE: tuple[str, ...] = tuple(col for cols in USAGE_COLUMNS.values() for col in cols)


def usage_metric_sql(metric: str, scoped: bool) -> str:
    template, account_col, _ = USAGE_METRICS[metric]
    return template.format(scope=f"AND {account_col} = %(id)s" if scoped else "")


def _collect(db: PGConn, days: int, account_id: int | None) -> tuple[dict, list[str]]:
    """Run every metric under its own soft_query; None where one was cut off."""
    degraded: list[str] = []
    params = {"days": days, "id": account_id}
    rows_by_metric: dict = {}
    for metric in USAGE_METRICS:
        sql = usage_metric_sql(metric, scoped=account_id is not None)

        def _read(cur, sql=sql):
            cur.execute(sql, params)
            return dict_fetchall(cur)

        value, timed_out = soft_query(db, _read, None)
        if timed_out:
            degraded.append(metric)
        rows_by_metric[metric] = value
    return rows_by_metric, degraded


_ACCOUNTS_SQL = (
    "SELECT a.id, a.name, p.plan_name, p.scoring_monthly_limit "
    "FROM accounts a LEFT JOIN account_plans p ON p.account_id = a.id"
)


@router.get("/admin/usage")
def admin_usage(
    days: int = Query(30, ge=1, le=365),
    sort: str = Query("name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    page, page_size = clamp_page(page, page_size)
    if sort != "name" and sort not in SORTABLE:
        raise HTTPException(
            status_code=400,
            detail=f"sort must be one of: name, {', '.join(SORTABLE)}.",
        )
    with db.cursor() as cur:
        cur.execute(f"{_ACCOUNTS_SQL} ORDER BY a.id")
        accounts = dict_fetchall(cur)
    rows_by_metric, degraded = _collect(db, days, None)
    rows = merge_usage(accounts, rows_by_metric, USAGE_COLUMNS, PLAN_SCORING_LIMITS)
    rows = sort_usage(rows, sort, SORTABLE)
    return {
        "days": days,
        "items": paginate_rows(rows, page, page_size),
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "columns": list(SORTABLE),
        "degraded": degraded,
    }


@router.get("/admin/accounts/{account_id}/usage")
def admin_account_usage(
    account_id: int,
    days: int = Query(30, ge=1, le=365),
    db: PGConn = Depends(get_db),
):
    with db.cursor() as cur:
        cur.execute(f"{_ACCOUNTS_SQL} WHERE a.id = %s", (account_id,))
        accounts = dict_fetchall(cur)
    if not accounts:
        raise HTTPException(status_code=404, detail="Account not found")
    rows_by_metric, degraded = _collect(db, days, account_id)
    row = merge_usage(accounts, rows_by_metric, USAGE_COLUMNS, PLAN_SCORING_LIMITS)[0]
    return {"days": days, "metrics": row, "degraded": degraded}
