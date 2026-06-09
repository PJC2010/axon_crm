"""
GET    /api/expenses          — list (filters: year, month, category, deductible, page, page_size)
POST   /api/expenses          — create
GET    /api/expenses/summary  — totals by category + tax summary
GET    /api/expenses/export   — CSV download
GET    /api/expenses/{id}     — single
PATCH  /api/expenses/{id}     — update
DELETE /api/expenses/{id}     — delete (owner only)
"""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner
from api.models import Expense, ExpenseCreate, ExpenseUpdate, ExpenseSummary, EXPENSE_CATEGORIES, PAYMENT_METHODS

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_where(account_id: int, year: Optional[int], month: Optional[int], category: Optional[str],
                 deductible: Optional[bool]) -> tuple[list[str], list]:
    conditions, params = ["account_id = %s"], [account_id]
    if year:
        conditions.append("EXTRACT(YEAR FROM expense_date) = %s")
        params.append(year)
    if month:
        conditions.append("EXTRACT(MONTH FROM expense_date) = %s")
        params.append(month)
    if category:
        conditions.append("category = %s")
        params.append(category)
    if deductible is not None:
        conditions.append("is_tax_deductible = %s")
        params.append(deductible)
    where = "WHERE " + " AND ".join(conditions)
    return where, params


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/expenses/summary", response_model=ExpenseSummary)
def expense_summary(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    where, params = _build_where(user["account_id"], year, month, None, None)
    with db.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count FROM expenses {where}",
            params,
        )
        row = dict_fetchone(cur)
        total = float(row["total"])
        count = int(row["count"])

        cur.execute(
            f"SELECT category, COALESCE(SUM(amount), 0) AS subtotal FROM expenses {where} GROUP BY category",
            params,
        )
        by_cat = {r["category"]: float(r["subtotal"]) for r in dict_fetchall(cur)}

        deduct_where, deduct_params = _build_where(user["account_id"], year, month, None, True)
        cur.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS deductible FROM expenses {deduct_where}",
            deduct_params,
        )
        deductible_total = float(dict_fetchone(cur)["deductible"])

    return ExpenseSummary(
        total=total,
        by_category=by_cat,
        tax_deductible_total=deductible_total,
        count=count,
    )


@router.get("/expenses/export")
def export_expenses(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    deductible: Optional[bool] = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    where, params = _build_where(user["account_id"], year, month, category, deductible)
    with db.cursor() as cur:
        cur.execute(
            f"SELECT expense_date, vendor, category, amount, payment_method, is_tax_deductible, description "
            f"FROM expenses {where} ORDER BY expense_date DESC",
            params,
        )
        rows = dict_fetchall(cur)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["expense_date", "vendor", "category", "amount", "payment_method", "is_tax_deductible", "description"])
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "expense_date": row["expense_date"],
            "vendor": row["vendor"],
            "category": row["category"],
            "amount": f"{float(row['amount']):.2f}",
            "payment_method": row["payment_method"],
            "is_tax_deductible": "Yes" if row["is_tax_deductible"] else "No",
            "description": row["description"] or "",
        })

    output.seek(0)
    filename = f"expenses_{year or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/expenses", response_model=dict)
def list_expenses(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    deductible: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    where, params = _build_where(user["account_id"], year, month, category, deductible)
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM expenses {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT * FROM expenses {where} ORDER BY expense_date DESC, id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        items = [Expense(**r) for r in dict_fetchall(cur)]

    return {"items": [i.model_dump() for i in items], "total": total, "page": page, "page_size": page_size}


@router.post("/expenses", response_model=Expense, status_code=201)
def create_expense(
    body: ExpenseCreate,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    if body.category not in EXPENSE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {EXPENSE_CATEGORIES}")
    if body.payment_method not in PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail=f"payment_method must be one of {PAYMENT_METHODS}")

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO expenses (amount, category, vendor, description, expense_date, payment_method, "
            "is_tax_deductible, property_id, created_by, account_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (body.amount, body.category, body.vendor, body.description, body.expense_date,
             body.payment_method, body.is_tax_deductible, body.property_id, current_user["id"],
             current_user["account_id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    return Expense(**row)


@router.get("/expenses/{expense_id}", response_model=Expense)
def get_expense(expense_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM expenses WHERE id = %s AND account_id = %s", (expense_id, user["account_id"]))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    return Expense(**row)


@router.patch("/expenses/{expense_id}", response_model=Expense)
def update_expense(
    expense_id: int,
    body: ExpenseUpdate,
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    sets, params = ["updated_at = NOW()"], []

    if body.amount is not None:
        sets.append("amount = %s"); params.append(body.amount)
    if body.category is not None:
        if body.category not in EXPENSE_CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category")
        sets.append("category = %s"); params.append(body.category)
    if body.vendor is not None:
        sets.append("vendor = %s"); params.append(body.vendor)
    if body.description is not None:
        sets.append("description = %s"); params.append(body.description)
    if body.expense_date is not None:
        sets.append("expense_date = %s"); params.append(body.expense_date)
    if body.payment_method is not None:
        if body.payment_method not in PAYMENT_METHODS:
            raise HTTPException(status_code=400, detail="Invalid payment_method")
        sets.append("payment_method = %s"); params.append(body.payment_method)
    if body.is_tax_deductible is not None:
        sets.append("is_tax_deductible = %s"); params.append(body.is_tax_deductible)
    if body.property_id is not None:
        sets.append("property_id = %s"); params.append(body.property_id)

    params.extend([expense_id, user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE expenses SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *", params
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    return Expense(**row)


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM expenses WHERE id = %s AND account_id = %s RETURNING id", (expense_id, user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Expense not found")
