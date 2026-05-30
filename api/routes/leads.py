"""
GET  /api/leads           — paginated, filtered lead list
GET  /api/leads/{id}      — single lead detail
PATCH /api/leads/{id}/status — update lead status
GET  /api/zips            — distinct ZIP codes in DB
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone
from api.models import Lead, LeadPage, StatusUpdate

router = APIRouter()

SORT_MAP = {
    "score":      "lead_score DESC NULLS LAST",
    "sale_date":  "last_sale_date DESC NULLS LAST",
    "address":    "address ASC",
    "grade":      "score_grade ASC",
}


@router.get("/leads", response_model=LeadPage)
def list_leads(
    zip: str | None = Query(None),
    grade: str | None = Query(None),
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("score"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: PGConn = Depends(get_db),
):
    order = SORT_MAP.get(sort, SORT_MAP["score"])
    conditions, params = _build_filters(zip=zip, grade=grade, vertical=vertical, status=status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM properties {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT * FROM properties {where} ORDER BY {order} LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    return LeadPage(total=total, page=page, page_size=page_size,
                    results=[Lead(**r) for r in rows])


@router.get("/leads/{lead_id}", response_model=Lead)
def get_lead(lead_id: int, db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM properties WHERE id = %s", (lead_id,))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Lead(**row)


@router.patch("/leads/{lead_id}/status", response_model=Lead)
def update_status(lead_id: int, body: StatusUpdate, db: PGConn = Depends(get_db)):
    body.validate_status()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE properties SET status = %s WHERE id = %s RETURNING *",
            (body.status, lead_id),
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Lead(**row)


@router.get("/zips")
def list_zips(db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT zip FROM properties WHERE zip IS NOT NULL ORDER BY zip")
        return [r[0] for r in cur.fetchall()]


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_filters(**kwargs) -> tuple[list[str], list]:
    conditions, params = [], []
    mapping = {
        "zip":      "zip = %s",
        "grade":    "score_grade = %s",
        "vertical": "vertical = %s",
        "status":   "status = %s",
    }
    for key, sql in mapping.items():
        val = kwargs.get(key)
        if val:
            conditions.append(sql)
            params.append(val)
    return conditions, params
