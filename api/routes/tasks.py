"""
GET  /api/tasks                   — list tasks (filters: due=today, overdue, property_id, complete)
POST /api/tasks                   — create task
GET  /api/tasks/counts            — {today: N, overdue: N} for notification badge
GET  /api/tasks/{id}              — single task
PATCH /api/tasks/{id}             — update task fields
POST /api/tasks/{id}/complete     — mark done
DELETE /api/tasks/{id}            — delete (owner only)
GET  /api/leads/{lead_id}/tasks   — tasks for a specific lead
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner

router = APIRouter()

PRIORITY_VALUES = {"low", "normal", "high", "urgent"}


# ── Pydantic models ───────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    property_id: Optional[int] = None
    title: str
    due_date: Optional[str] = None
    priority: str = "normal"
    assigned_to: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None


class Task(BaseModel):
    id: int
    property_id: Optional[int] = None
    assigned_to: Optional[int] = None
    title: str
    due_date: Optional[date] = None
    priority: str
    is_complete: bool
    completed_at: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tasks/counts")
def task_counts(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE due_date = CURRENT_DATE AND is_complete = FALSE",
        )
        today = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE due_date < CURRENT_DATE AND is_complete = FALSE",
        )
        overdue = cur.fetchone()[0]
    return {"today": today, "overdue": overdue}


@router.get("/tasks", response_model=list[Task])
def list_tasks(
    due: str | None = Query(None, description="'today' to filter to today's tasks"),
    overdue: bool | None = Query(None),
    property_id: int | None = Query(None),
    assigned_to: int | None = Query(None),
    complete: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    conditions, params = ["is_complete = %s"], [complete]

    if due == "today":
        conditions.append("due_date = CURRENT_DATE")
    if overdue:
        conditions.append("due_date < CURRENT_DATE")
    if property_id is not None:
        conditions.append("property_id = %s"); params.append(property_id)
    if assigned_to is not None:
        conditions.append("assigned_to = %s"); params.append(assigned_to)

    where = "WHERE " + " AND ".join(conditions)
    with db.cursor() as cur:
        cur.execute(
            f"SELECT * FROM tasks {where} ORDER BY due_date ASC NULLS LAST, priority DESC",
            params,
        )
        return [Task(**r) for r in dict_fetchall(cur)]


@router.post("/tasks", response_model=Task, status_code=201)
def create_task(body: TaskCreate, current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    if body.priority not in PRIORITY_VALUES:
        raise HTTPException(status_code=400, detail=f"priority must be one of {PRIORITY_VALUES}")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO tasks (property_id, assigned_to, title, due_date, priority, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (body.property_id, body.assigned_to, body.title, body.due_date, body.priority, current_user["id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    return Task(**row)


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: int, _: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return Task(**row)


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, body: TaskUpdate, _: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    sets, params = ["updated_at = NOW()"], []
    if body.title is not None:
        sets.append("title = %s"); params.append(body.title)
    if body.due_date is not None:
        sets.append("due_date = %s"); params.append(body.due_date)
    if body.priority is not None:
        if body.priority not in PRIORITY_VALUES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        sets.append("priority = %s"); params.append(body.priority)
    if body.assigned_to is not None:
        sets.append("assigned_to = %s"); params.append(body.assigned_to)
    params.append(task_id)
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = %s RETURNING *", params
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return Task(**row)


@router.post("/tasks/{task_id}/complete", response_model=Task)
def complete_task(task_id: int, _: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "UPDATE tasks SET is_complete = TRUE, completed_at = NOW(), updated_at = NOW() "
            "WHERE id = %s RETURNING *",
            (task_id,),
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return Task(**row)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, _: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s RETURNING id", (task_id,))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")


@router.get("/leads/{lead_id}/tasks", response_model=list[Task])
def lead_tasks(lead_id: int, _: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM tasks WHERE property_id = %s ORDER BY due_date ASC NULLS LAST",
            (lead_id,),
        )
        return [Task(**r) for r in dict_fetchall(cur)]
