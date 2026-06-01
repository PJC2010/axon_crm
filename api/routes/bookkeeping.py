"""
GET /api/bookkeeping/pnl         — monthly P&L: revenue (paid invoices) vs. expenses
GET /api/bookkeeping/job-costing — per-property: revenue, paid, expenses, profit, margin
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user

router = APIRouter()


@router.get("/bookkeeping/pnl")
def profit_and_loss(
    year: int = Query(..., description="Year to report"),
    _: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
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
            GROUP BY month
            ORDER BY month
            """,
            (year,),
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
            GROUP BY month
            ORDER BY month
            """,
            (year,),
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


@router.get("/bookkeeping/job-costing")
def job_costing(
    year: Optional[int] = Query(None),
    _: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    year_inv_cond = "AND EXTRACT(YEAR FROM i.issue_date) = %s" if year else ""
    year_exp_cond = "AND EXTRACT(YEAR FROM e.expense_date) = %s" if year else ""
    params = [year] if year else []

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                p.id          AS property_id,
                p.address,
                COALESCE(inv.total_invoiced, 0)  AS revenue,
                COALESCE(inv.total_paid, 0)       AS amount_paid,
                COALESCE(exp.total_expenses, 0)   AS expenses
            FROM properties p
            LEFT JOIN (
                SELECT property_id,
                       SUM(total) AS total_invoiced,
                       SUM(amount_paid) AS total_paid
                FROM invoices
                WHERE property_id IS NOT NULL AND status != 'void'
                {year_inv_cond}
                GROUP BY property_id
            ) inv ON inv.property_id = p.id
            LEFT JOIN (
                SELECT property_id,
                       SUM(amount) AS total_expenses
                FROM expenses
                WHERE property_id IS NOT NULL
                {year_exp_cond}
                GROUP BY property_id
            ) exp ON exp.property_id = p.id
            WHERE inv.property_id IS NOT NULL OR exp.property_id IS NOT NULL
            ORDER BY (COALESCE(inv.total_paid, 0) - COALESCE(exp.total_expenses, 0)) DESC
            """,
            params + params,
        )
        rows = dict_fetchall(cur)

    result = []
    for r in rows:
        revenue = float(r["revenue"])
        amount_paid = float(r["amount_paid"])
        expenses = float(r["expenses"])
        profit = round(amount_paid - expenses, 2)
        margin = round((profit / amount_paid * 100), 1) if amount_paid > 0 else 0.0
        result.append({
            "property_id": r["property_id"],
            "address": r["address"],
            "revenue": revenue,
            "amount_paid": amount_paid,
            "expenses": expenses,
            "profit": profit,
            "margin_pct": margin,
        })

    return result
