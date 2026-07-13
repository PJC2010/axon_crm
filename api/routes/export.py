"""
GET /api/export               — download filtered leads as CSV
GET /api/export/qbo/invoices  — invoices in QuickBooks Online import format
GET /api/export/qbo/expenses  — expenses in QBO bank-transaction import format

The leads export takes the same query params as GET /api/leads (zip, grade,
vertical, status, sort). The QBO exports take optional start/end (ISO dates).
All are reachable via the `?token=` query param for `<a download>` links.
"""
import csv
import io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user
from api.qbo_export import QBO_EXPENSE_COLS, QBO_INVOICE_COLS, expense_rows, invoice_rows
from api.routes.leads import SORT_MAP, _build_filters

router = APIRouter()


def _csv_response(rows: list[dict], columns: list[str], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

EXPORT_COLS = [
    "id", "address", "city", "state", "zip",
    "year_built", "square_footage", "garage_spaces",
    "estimated_value", "estimated_equity",
    "last_sale_date", "last_sale_price",
    "owner_name", "zip_median_income", "permit_count_24mo",
    "lead_score", "score_grade", "vertical", "status",
]


@router.get("/export")
def export_leads(
    zip: str | None = Query(None),
    grade: str | None = Query(None),
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("score"),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    order = SORT_MAP.get(sort, SORT_MAP["score"])
    conditions, params = _build_filters(user["account_id"], zip=zip, grade=grade, vertical=vertical, status=status)
    where = f"WHERE {' AND '.join(conditions)}"

    with db.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(EXPORT_COLS)} FROM properties {where} ORDER BY {order}",
            params,
        )
        rows = dict_fetchall(cur)

    return _csv_response(rows, EXPORT_COLS, f"leads_{zip or 'all'}.csv")


# ── QuickBooks Online exports (audit P1: the bookkeeper's escape hatch) ───────

def _date_window(start: str | None, end: str | None, column: str) -> tuple[str, list]:
    clauses, params = [], []
    if start:
        clauses.append(f"AND {column} >= %s"); params.append(start)
    if end:
        clauses.append(f"AND {column} <= %s"); params.append(end)
    return " ".join(clauses), params


@router.get("/export/qbo/invoices")
def export_qbo_invoices(
    start: str | None = Query(None, description="Earliest issue_date (YYYY-MM-DD)"),
    end: str | None = Query(None, description="Latest issue_date (YYYY-MM-DD)"),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Invoices + line items shaped for QBO's invoice importer. Drafts and
    voided invoices stay out of the books."""
    window, params = _date_window(start, end, "issue_date")
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM invoices WHERE account_id = %s "
            f"AND status NOT IN ('draft', 'void') {window} ORDER BY issue_date, id",
            [user["account_id"], *params],
        )
        invoices = dict_fetchall(cur)
        if invoices:
            cur.execute(
                "SELECT * FROM invoice_line_items WHERE invoice_id = ANY(%s) "
                "ORDER BY invoice_id, sort_order",
                ([inv["id"] for inv in invoices],),
            )
            items = dict_fetchall(cur)
            by_invoice: dict[int, list] = {}
            for item in items:
                by_invoice.setdefault(item["invoice_id"], []).append(item)
            for inv in invoices:
                inv["items"] = by_invoice.get(inv["id"], [])

    return _csv_response(invoice_rows(invoices), QBO_INVOICE_COLS, "qbo_invoices.csv")


@router.get("/export/qbo/expenses")
def export_qbo_expenses(
    start: str | None = Query(None, description="Earliest expense_date (YYYY-MM-DD)"),
    end: str | None = Query(None, description="Latest expense_date (YYYY-MM-DD)"),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Expenses shaped for QBO's 3-column bank-transaction importer."""
    window, params = _date_window(start, end, "expense_date")
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM expenses WHERE account_id = %s "
            f"{window} ORDER BY expense_date, id",
            [user["account_id"], *params],
        )
        expenses = dict_fetchall(cur)
    return _csv_response(expense_rows(expenses), QBO_EXPENSE_COLS, "qbo_expenses.csv")
