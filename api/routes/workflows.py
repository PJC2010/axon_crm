"""
GET    /api/workflows               — list all workflow rules
POST   /api/workflows               — create a rule (owner only)
PATCH  /api/workflows/{id}          — update a rule
DELETE /api/workflows/{id}          — delete a rule
POST   /api/workflows/seed-defaults — seed vertical-specific defaults
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner

router = APIRouter()


class WorkflowRuleCreate(BaseModel):
    name: str
    trigger_type: str = "status_change"
    trigger_config: dict = {}
    action_type: str = "create_task"
    action_config: dict = {}
    is_active: bool = True
    vertical: Optional[str] = None


class WorkflowRuleUpdate(BaseModel):
    name: Optional[str] = None
    trigger_config: Optional[dict] = None
    action_config: Optional[dict] = None
    is_active: Optional[bool] = None
    vertical: Optional[str] = None


@router.get("/workflows")
def list_workflows(db: PGConn = Depends(get_db), _: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM workflow_rules ORDER BY created_at")
        return dict_fetchall(cur)


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowRuleCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO workflow_rules (name, trigger_type, trigger_config, action_type, action_config, is_active, vertical, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (body.name, body.trigger_type, json.dumps(body.trigger_config), body.action_type,
             json.dumps(body.action_config), body.is_active, body.vertical, current_user["id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    return row


@router.patch("/workflows/{rule_id}")
def update_workflow(rule_id: int, body: WorkflowRuleUpdate, _: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    sets, params = [], []
    if body.name is not None:
        sets.append("name = %s"); params.append(body.name)
    if body.trigger_config is not None:
        sets.append("trigger_config = %s"); params.append(json.dumps(body.trigger_config))
    if body.action_config is not None:
        sets.append("action_config = %s"); params.append(json.dumps(body.action_config))
    if body.is_active is not None:
        sets.append("is_active = %s"); params.append(body.is_active)
    if body.vertical is not None:
        sets.append("vertical = %s"); params.append(body.vertical)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    sets.append("updated_at = NOW()")
    params.append(rule_id)
    with db.cursor() as cur:
        cur.execute(f"UPDATE workflow_rules SET {', '.join(sets)} WHERE id = %s RETURNING *", params)
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return row


@router.delete("/workflows/{rule_id}", status_code=204)
def delete_workflow(rule_id: int, _: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM workflow_rules WHERE id = %s RETURNING id", (rule_id,))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")


@router.post("/workflows/seed-defaults")
def seed_defaults(
    vertical: str = Query(...),
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    from api.workflow_engine import VERTICAL_DEFAULTS
    defaults = VERTICAL_DEFAULTS.get(vertical)
    if not defaults:
        raise HTTPException(status_code=400, detail=f"No defaults for vertical: {vertical}")

    created = []
    with db.cursor() as cur:
        for rule in defaults:
            cur.execute(
                "INSERT INTO workflow_rules (name, trigger_type, trigger_config, action_type, action_config, vertical, created_by) "
                "VALUES (%s, 'status_change', %s, 'create_task', %s, %s, %s) RETURNING *",
                (rule["name"], json.dumps(rule["trigger_config"]), json.dumps(rule["action_config"]),
                 vertical, current_user["id"]),
            )
            created.append(dict_fetchone(cur))
        db.commit()
    return {"created": len(created), "rules": created}
