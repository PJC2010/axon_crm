"""
GET /api/bookkeeping/pnl         — monthly P&L: revenue (paid invoices) vs. expenses
"""
from fastapi import APIRouter, Depends, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user

router = APIRouter()


@router.get("/bookkeeping/pnl")
def profit_and_loss(
    year: int = Query(..., description="Year to report"),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    acct = user["account_id"]
    with db.cursor() as cur:
        # Revenue: payments received grouped by month
        cur.execute(
            """
            SELECT
                EXTRACT(MONTH FROM payment_date)::INT AS month,
                COALESCE(SUM(p.amount), 0) AS revenue
            FROM invoice_payments p
            JOIN invoices i ON i.id = p.invoice_id
            WHERE EXTRACT(YEAR FROM p.payment_date) = %s
              AND i.status != 'void'
              AND i.account_id = %s
            GROUP BY month
            ORDER BY month
            """,
            (year, acct),
        )
        rev_rows = {r["month"]: float(r["revenue"]) for r in dict_fetchall(cur)}

        # Expenses: by month
        cur.execute(
            """
            SELECT
                EXTRACT(MONTH FROM expense_date)::INT AS month,
                COALESCE(SUM(amount), 0) AS expenses
            FROM expenses
            WHERE EXTRACT(YEAR FROM expense_date) = %s
              AND account_id = %s
            GROUP BY month
            ORDER BY month
            """,
            (year, acct),
        )
        exp_rows = {r["month"]: float(r["expenses"]) for r in dict_fetchall(cur)}

    months = sorted(set(list(rev_rows.keys()) + list(exp_rows.keys())))
    result = []
    for m in months:
        revenue = rev_rows.get(m, 0.0)
        expenses = exp_rows.get(m, 0.0)
        result.append({
            "year": year,
            "month": m,
            "revenue": revenue,
            "expenses": expenses,
            "net": round(revenue - expenses, 2),
        })

    # Summary totals
    total_revenue = sum(r["revenue"] for r in result)
    total_expenses = sum(r["expenses"] for r in result)

    return {
        "year": year,
        "months": result,
        "total_revenue": round(total_revenue, 2),
        "total_expenses": round(total_expenses, 2),
        "net_profit": round(total_revenue - total_expenses, 2),
    }
