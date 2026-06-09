"""
GET /api/export — download filtered leads as CSV
Same query params as GET /api/leads (zip, grade, vertical, status, sort).
"""
import csv
import io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user
from api.routes.leads import SORT_MAP, _build_filters

router = APIRouter()

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

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)

    filename = f"leads_{zip or 'all'}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
