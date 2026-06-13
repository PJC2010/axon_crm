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

CARD_COLS = "id, address, owner_name, contact_name, contact_phone, lead_score, score_grade, estimated_job_value, status, vertical, zip"


# ── Pydantic models ───────────────────────────────────────────────────────────

class StageCreate(BaseModel):
    key: str
    label: str
    color: str = "var(--color-ink-300)"
    sort_order: int = 0
    is_terminal: bool = False


class StageUpdate(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    is_terminal: Optional[bool] = None


class JobValueUpdate(BaseModel):
    estimated_job_value: int


class ScheduleCreate(BaseModel):
    zip: str
    vertical: Optional[str] = None
    day_of_week: str = "monday"
    hour: int = 6
    # Volume controls (optional): Top-N cap + radius-from-address narrowing.
    top_n: Optional[int] = None
    center_address: Optional[str] = None
    radius_mi: Optional[float] = None


class ScheduleUpdate(BaseModel):
    is_active: Optional[bool] = None
    day_of_week: Optional[str] = None
    hour: Optional[int] = None
    top_n: Optional[int] = None
    center_address: Optional[str] = None
    radius_mi: Optional[float] = None


class RunCreate(BaseModel):
    zip: str
    vertical: Optional[str] = None
    # Volume controls (optional): Top-N cap + radius-from-address narrowing.
    top_n: Optional[int] = None
    center_address: Optional[str] = None
    radius_mi: Optional[float] = None


# ── Pipeline Stages ──────────────────────────────────────────────────────

@router.get("/pipeline/stages")
def list_stages(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM pipeline_stages WHERE account_id = %s ORDER BY sort_order, id",
            (user["account_id"],),
        )
        return dict_fetchall(cur)


@router.post("/pipeline/stages", status_code=201)
def create_stage(body: StageCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_stages (key, label, color, sort_order, is_terminal, created_by, account_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (body.key, body.label, body.color, body.sort_order, body.is_terminal,
             current_user["id"], current_user["account_id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    return row


@router.patch("/pipeline/stages/{stage_id}")
def update_stage(stage_id: int, body: StageUpdate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    sets, params = [], []
    if body.label is not None:
        sets.append("label = %s"); params.append(body.label)
    if body.color is not None:
        sets.append("color = %s"); params.append(body.color)
    if body.sort_order is not None:
        sets.append("sort_order = %s"); params.append(body.sort_order)
    if body.is_terminal is not None:
        sets.append("is_terminal = %s"); params.append(body.is_terminal)
    if not sets:
        from fastapi import HTTPException as HE
        raise HE(status_code=400, detail="Nothing to update")
    params.extend([stage_id, current_user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE pipeline_stages SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
            params,
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Stage not found")
    return row


@router.delete("/pipeline/stages/{stage_id}", status_code=204)
def delete_stage(stage_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    acct = current_user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT key, is_default FROM pipeline_stages WHERE id = %s AND account_id = %s", (stage_id, acct))
        stage = dict_fetchone(cur)
        if not stage:
            raise HTTPException(status_code=404, detail="Stage not found")
        if stage["is_default"]:
            raise HTTPException(status_code=400, detail="Cannot delete the default stage")
        cur.execute("SELECT COUNT(*) FROM properties WHERE status = %s AND account_id = %s", (stage["key"], acct))
        count = cur.fetchone()[0]
        if count > 0:
            raise HTTPException(status_code=400, detail=f"Cannot delete — {count} leads are in this stage")
        cur.execute("DELETE FROM pipeline_stages WHERE id = %s AND account_id = %s", (stage_id, acct))
        db.commit()


# ── Pipeline / Kanban ─────────────────────────────────────────────────────────

@router.get("/pipeline")
def get_pipeline(
    vertical: str | None = Query(None),
    zip: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    conditions, params = ["account_id = %s"], [user["account_id"]]
    if vertical:
        conditions.append("vertical = %s"); params.append(vertical)
    if zip:
        conditions.append("zip = %s"); params.append(zip)
    where = "WHERE " + " AND ".join(conditions)

    with db.cursor() as cur:
        cur.execute(
            "SELECT key FROM pipeline_stages WHERE account_id = %s ORDER BY sort_order, id",
            (user["account_id"],),
        )
        stage_keys = [r[0] for r in cur.fetchall()] or PIPELINE_STAGES

        cur.execute(
            f"SELECT {CARD_COLS} FROM properties {where} ORDER BY lead_score DESC NULLS LAST",
            params,
        )
        rows = dict_fetchall(cur)

    grouped: dict[str, list] = {s: [] for s in stage_keys}
    for row in rows:
        stage = row["status"] if row["status"] in grouped else stage_keys[0]
        grouped[stage].append(row)
    return grouped


@router.get("/pipeline/stats")
def pipeline_stats(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) AS count, COALESCE(SUM(estimated_job_value), 0) AS total_value "
            "FROM properties WHERE account_id = %s GROUP BY status",
            (user["account_id"],),
        )
        rows = dict_fetchall(cur)
    return {r["status"]: {"count": r["count"], "total_value": r["total_value"]} for r in rows}


@router.get("/pipeline/analytics")
def pipeline_analytics(
    days: int = Query(90, ge=7, le=365),
    vertical: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    acct = user["account_id"]
    vert_filter = "AND vertical = %s" if vertical else ""
    vert_params = [vertical] if vertical else []

    with db.cursor() as cur:
        # Win rate
        cur.execute(
            f"SELECT "
            f"  COUNT(*) FILTER (WHERE status = 'won') AS won, "
            f"  COUNT(*) FILTER (WHERE status IN ('won','lost')) AS decided "
            f"FROM properties WHERE account_id = %s AND stage_moved_at >= NOW() - INTERVAL '%s days' {vert_filter}",
            [acct, days] + vert_params,
        )
        wr = dict_fetchone(cur)
        win_rate = round((wr["won"] / wr["decided"] * 100) if wr["decided"] > 0 else 0, 1)

        # Avg cycle time (created_at → stage_moved_at for won leads)
        cur.execute(
            f"SELECT AVG(EXTRACT(EPOCH FROM (stage_moved_at - created_at)) / 86400) AS avg_days "
            f"FROM properties WHERE account_id = %s AND status = 'won' AND stage_moved_at IS NOT NULL AND created_at IS NOT NULL "
            f"AND stage_moved_at >= NOW() - INTERVAL '%s days' {vert_filter}",
            [acct, days] + vert_params,
        )
        ct = dict_fetchone(cur)
        avg_cycle_time = round(ct["avg_days"], 1) if ct and ct["avg_days"] else None

        # Leads won in period
        cur.execute(
            f"SELECT COUNT(*) AS count FROM properties WHERE account_id = %s AND status = 'won' "
            f"AND stage_moved_at >= NOW() - INTERVAL '%s days' {vert_filter}",
            [acct, days] + vert_params,
        )
        leads_won = cur.fetchone()[0]

        # Funnel: count per stage from stage_transitions (scoped to this org's leads)
        acct_sub = (
            "AND property_id IN (SELECT id FROM properties WHERE account_id = %s"
            + (" AND vertical = %s)" if vertical else ")")
        )
        cur.execute(
            f"SELECT to_status, COUNT(DISTINCT property_id) AS leads "
            f"FROM stage_transitions WHERE transitioned_at >= NOW() - INTERVAL '%s days' "
            f"{acct_sub} "
            f"GROUP BY to_status",
            [days, acct] + vert_params,
        )
        funnel_rows = dict_fetchall(cur)
        funnel = {r["to_status"]: r["leads"] for r in funnel_rows}

        # Avg days per stage from transitions (scoped to this org's leads)
        cur.execute(
            f"SELECT t1.from_status AS stage, "
            f"  AVG(EXTRACT(EPOCH FROM (t1.transitioned_at - t2.transitioned_at)) / 86400) AS avg_days "
            f"FROM stage_transitions t1 "
            f"JOIN LATERAL ("
            f"  SELECT transitioned_at FROM stage_transitions t2 "
            f"  WHERE t2.property_id = t1.property_id AND t2.to_status = t1.from_status "
            f"  ORDER BY t2.transitioned_at DESC LIMIT 1"
            f") t2 ON TRUE "
            f"WHERE t1.from_status IS NOT NULL AND t1.transitioned_at >= NOW() - INTERVAL '%s days' "
            f"AND t1.property_id IN (SELECT id FROM properties WHERE account_id = %s) "
            f"GROUP BY t1.from_status",
            [days, acct],
        )
        stage_time_rows = dict_fetchall(cur)
        avg_days_per_stage = {r["stage"]: round(r["avg_days"], 1) if r["avg_days"] else None for r in stage_time_rows}

    return {
        "win_rate": win_rate,
        "avg_cycle_time": avg_cycle_time,
        "leads_won": leads_won,
        "funnel": funnel,
        "avg_days_per_stage": avg_days_per_stage,
        "period_days": days,
    }


@router.get("/pipeline/forecast")
def pipeline_forecast(
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    stage_weights = {
        "new": 0.05,
        "contacted": 0.15,
        "qualified": 0.35,
        "quote_sent": 0.60,
    }
    with db.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) AS count, COALESCE(SUM(estimated_job_value), 0) AS raw_value "
            "FROM properties WHERE account_id = %s AND status IN ('new','contacted','qualified','quote_sent') "
            "GROUP BY status",
            (user["account_id"],),
        )
        rows = dict_fetchall(cur)

    by_stage = []
    weighted_total = 0
    for row in rows:
        stage = row["status"]
        weight = stage_weights.get(stage, 0)
        weighted = round(row["raw_value"] * weight)
        weighted_total += weighted
        by_stage.append({
            "stage": stage,
            "count": row["count"],
            "raw_value": row["raw_value"],
            "weight_pct": round(weight * 100),
            "weighted_value": weighted,
        })

    return {
        "weighted_total": weighted_total,
        "by_stage": sorted(by_stage, key=lambda x: stage_weights.get(x["stage"], 0)),
    }


@router.patch("/leads/{lead_id}/job-value")
def update_job_value(lead_id: int, body: JobValueUpdate, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE properties SET estimated_job_value = %s WHERE id = %s AND account_id = %s RETURNING {CARD_COLS}",
            (body.estimated_job_value, lead_id, user["account_id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return row


# ── Schedules ─────────────────────────────────────────────────────────────────

@router.get("/pipeline-schedules")
def list_schedules(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM pipeline_schedules WHERE account_id = %s ORDER BY id",
            (user["account_id"],),
        )
        return dict_fetchall(cur)


@router.post("/pipeline-schedules", status_code=201)
def create_schedule(body: ScheduleCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    from api.scheduler import add_schedule_job
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_schedules "
            "(zip, vertical, day_of_week, hour, top_n, center_address, radius_mi, created_by, account_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (body.zip, body.vertical, body.day_of_week, body.hour,
             body.top_n, body.center_address, body.radius_mi, current_user["id"], current_user["account_id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    add_schedule_job(row)
    return row


@router.patch("/pipeline-schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    current_user: dict = Depends(require_owner),
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
    if body.top_n is not None:
        sets.append("top_n = %s"); params.append(body.top_n)
    if body.center_address is not None:
        sets.append("center_address = %s"); params.append(body.center_address)
    if body.radius_mi is not None:
        sets.append("radius_mi = %s"); params.append(body.radius_mi)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.extend([schedule_id, current_user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE pipeline_schedules SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
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
def delete_schedule(schedule_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    from api.scheduler import remove_schedule_job
    remove_schedule_job(schedule_id)
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM pipeline_schedules WHERE id = %s AND account_id = %s RETURNING id",
            (schedule_id, current_user["account_id"]),
        )
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")


# ── Manual runs ───────────────────────────────────────────────────────────────

@router.post("/pipeline/run", status_code=201)
def trigger_run(body: RunCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    from api.ratelimit import pipeline_run_limiter
    from api.scheduler import enqueue_run
    # Manual runs spend real enrichment-API dollars — throttle per account.
    pipeline_run_limiter.check(f"acct:{current_user['account_id']}")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs "
            "(zip, vertical, top_n, center_address, radius_mi, triggered_by, account_id) "
            "VALUES (%s, %s, %s, %s, %s, 'manual', %s) RETURNING *",
            (body.zip, body.vertical, body.top_n, body.center_address, body.radius_mi,
             current_user["account_id"]),
        )
        run = dict_fetchone(cur)
        db.commit()
    enqueue_run(run["id"], body.zip, body.vertical, current_user["account_id"], top_n=body.top_n,
                center_address=body.center_address, radius_mi=body.radius_mi)
    return run


@router.get("/pipeline/runs")
def list_runs(limit: int = Query(20, ge=1, le=100), user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM pipeline_runs WHERE account_id = %s ORDER BY created_at DESC LIMIT %s",
            (user["account_id"], limit),
        )
        return dict_fetchall(cur)


@router.get("/pipeline/runs/{run_id}")
def get_run(run_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM pipeline_runs WHERE id = %s AND account_id = %s", (run_id, user["account_id"]))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.post("/pipeline/rescore")
def rescore(body: RunCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    """Score (or re-score) all leads in a ZIP without re-running the full pipeline."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from pipeline.scorer import score_zip
    n = score_zip(body.zip, current_user["account_id"], vertical=body.vertical)
    return {"scored": n, "zip": body.zip, "vertical": body.vertical}


@router.post("/pipeline/rescore-all")
def rescore_all(current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    """Score (or re-score) all leads in every ZIP for this org."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from pipeline.scorer import score_zip
    from pipeline.neighborhood import recompute_neighborhood_values
    acct = current_user["account_id"]
    # Refresh the account-wide neighborhood value benchmark before scoring, so the
    # neighborhood signal reads current ratios. Must run once for the whole org
    # (geohash cells cross ZIP boundaries), not per ZIP.
    recompute_neighborhood_values(db, acct)
    with db.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT zip FROM properties WHERE zip IS NOT NULL AND account_id = %s ORDER BY zip",
            (acct,),
        )
        zips = [row[0] for row in cur.fetchall()]
    total = 0
    for z in zips:
        total += score_zip(z, acct, vertical=None)
    return {"scored": total, "zips": len(zips)}


@router.delete("/pipeline/runs/{run_id}", status_code=204)
def cancel_run(run_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    """Signal a running pipeline to stop after its current step."""
    from api.scheduler import request_cancel
    acct = current_user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT status FROM pipeline_runs WHERE id = %s AND account_id = %s", (run_id, acct))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row[0] not in ("queued", "running"):
        raise HTTPException(status_code=400, detail=f"Run is already {row[0]}")
    request_cancel(run_id)
    # Mark as cancelled immediately so the UI updates even if the thread hasn't checked yet
    with db.cursor() as cur:
        cur.execute(
            "UPDATE pipeline_runs SET status = 'cancelled', finished_at = NOW() WHERE id = %s AND account_id = %s",
            (run_id, acct),
        )
    db.commit()
    return
