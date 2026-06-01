"""
GET  /api/pipeline                       — leads grouped by stage
GET  /api/pipeline/stats                 — count + total value per stage
PATCH /api/leads/{id}/job-value          — set estimated_job_value
GET  /api/pipeline-schedules             — list schedules
POST /api/pipeline-schedules             — create schedule (owner only)
PATCH /api/pipeline-schedules/{id}       — update/toggle schedule (owner only)
DELETE /api/pipeline-schedules/{id}      — delete schedule (owner only)
POST /api/pipeline/run                   — trigger manual run (owner only)
GET  /api/pipeline/runs                  — recent runs
GET  /api/pipeline/runs/{id}             — single run detail
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner

router = APIRouter()

PIPELINE_STAGES = ["new", "contacted", "qualified", "quote_sent", "won", "lost", "not_interested"]

CARD_COLS = "id, address, owner_name, lead_score, score_grade, estimated_job_value, status, vertical, zip"


# ── Pydantic models ───────────────────────────────────────────────────────────

class JobValueUpdate(BaseModel):
    estimated_job_value: int


class ScheduleCreate(BaseModel):
    zip: str
    vertical: Optional[str] = None
    day_of_week: str = "monday"
    hour: int = 6


class ScheduleUpdate(BaseModel):
    is_active: Optional[bool] = None
    day_of_week: Optional[str] = None
    hour: Optional[int] = None


class RunCreate(BaseModel):
    zip: str
    vertical: Optional[str] = None


# ── Pipeline / Kanban ─────────────────────────────────────────────────────────

@router.get("/pipeline")
def get_pipeline(
    vertical: str | None = Query(None),
    zip: str | None = Query(None),
    _: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    conditions, params = [], []
    if vertical:
        conditions.append("vertical = %s"); params.append(vertical)
    if zip:
        conditions.append("zip = %s"); params.append(zip)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db.cursor() as cur:
        cur.execute(
            f"SELECT {CARD_COLS} FROM properties {where} ORDER BY lead_score DESC NULLS LAST",
            params,
        )
        rows = dict_fetchall(cur)

    grouped: dict[str, list] = {s: [] for s in PIPELINE_STAGES}
    for row in rows:
        stage = row["status"] if row["status"] in grouped else "new"
        grouped[stage].append(row)
    return grouped


@router.get("/pipeline/stats")
def pipeline_stats(_: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) AS count, COALESCE(SUM(estimated_job_value), 0) AS total_value "
            "FROM properties GROUP BY status"
        )
        rows = dict_fetchall(cur)
    return {r["status"]: {"count": r["count"], "total_value": r["total_value"]} for r in rows}


@router.patch("/leads/{lead_id}/job-value")
def update_job_value(lead_id: int, body: JobValueUpdate, _: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET estimated_job_value = %s WHERE id = %s RETURNING {CARD_COLS}",
            (body.estimated_job_value, lead_id),
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return row


# ── Schedules ─────────────────────────────────────────────────────────────────

@router.get("/pipeline-schedules")
def list_schedules(_: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM pipeline_schedules ORDER BY id")
        return dict_fetchall(cur)


@router.post("/pipeline-schedules", status_code=201)
def create_schedule(body: ScheduleCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    from api.scheduler import add_schedule_job
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_schedules (zip, vertical, day_of_week, hour, created_by) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (body.zip, body.vertical, body.day_of_week, body.hour, current_user["id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    add_schedule_job(row)
    return row


@router.patch("/pipeline-schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    _: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    from api.scheduler import remove_schedule_job, add_schedule_job
    sets, params = [], []
    if body.is_active is not None:
        sets.append("is_active = %s"); params.append(body.is_active)
    if body.day_of_week is not None:
        sets.append("day_of_week = %s"); params.append(body.day_of_week)
    if body.hour is not None:
        sets.append("hour = %s"); params.append(body.hour)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.append(schedule_id)
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE pipeline_schedules SET {', '.join(sets)} WHERE id = %s RETURNING *",
            params,
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Schedule not found")
    remove_schedule_job(schedule_id)
    if row["is_active"]:
        add_schedule_job(row)
    return row


@router.delete("/pipeline-schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, _: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    from api.scheduler import remove_schedule_job
    remove_schedule_job(schedule_id)
    with db.cursor() as cur:
        cur.execute("DELETE FROM pipeline_schedules WHERE id = %s RETURNING id", (schedule_id,))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")


# ── Manual runs ───────────────────────────────────────────────────────────────

@router.post("/pipeline/run", status_code=201)
def trigger_run(body: RunCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    from api.scheduler import enqueue_run
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (zip, vertical, triggered_by) VALUES (%s, %s, 'manual') RETURNING *",
            (body.zip, body.vertical),
        )
        run = dict_fetchone(cur)
        db.commit()
    enqueue_run(run["id"], body.zip, body.vertical)
    return run


@router.get("/pipeline/runs")
def list_runs(limit: int = Query(20, ge=1, le=100), _: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM pipeline_runs ORDER BY created_at DESC LIMIT %s", (limit,))
        return dict_fetchall(cur)


@router.get("/pipeline/runs/{run_id}")
def get_run(run_id: int, _: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM pipeline_runs WHERE id = %s", (run_id,))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row
