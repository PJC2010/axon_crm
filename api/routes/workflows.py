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


TRIGGER_TYPES = ("status_change", "signal_event", "lead_imported", "quote_event",
                 "date_offset", "inactivity",
                 "policy_event", "order_event", "appointment_event")
ACTION_TYPES = ("create_task", "log_history", "move_lead_status", "send_notification")


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
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None
    action_type: Optional[str] = None
    action_config: Optional[dict] = None
    is_active: Optional[bool] = None
    vertical: Optional[str] = None


def _validate_rule(trigger_type: str, trigger_config: dict, action_type: str, action_config: dict) -> None:
    """Reject configs the engine would silently skip, so mistakes surface at
    save time instead of as a rule that never fires."""
    if trigger_type not in TRIGGER_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown trigger_type: {trigger_type}")
    if action_type not in ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown action_type: {action_type}")

    if trigger_type == "date_offset":
        from api.workflow_engine import DATE_TRIGGER_SOURCES
        source = trigger_config.get("source", "properties")
        src = DATE_TRIGGER_SOURCES.get(source)
        if not src:
            raise HTTPException(status_code=400, detail=f"Unknown date source: {source}")
        field = trigger_config.get("date_field")
        if field not in src["fields"]:
            raise HTTPException(
                status_code=400,
                detail=f"date_field must be one of {sorted(src['fields'])} for source {source}",
            )
        try:
            int(trigger_config.get("offset_days", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="offset_days must be an integer")

    if trigger_type == "inactivity":
        days = trigger_config.get("days")
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise HTTPException(status_code=400, detail="inactivity rules need a positive integer `days`")

    if action_type == "send_notification" and action_config.get("channel", "email") != "email":
        raise HTTPException(status_code=400, detail="send_notification supports only the email channel")


@router.get("/workflows")
def list_workflows(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE account_id = %s ORDER BY created_at",
            (user["account_id"],),
        )
        return dict_fetchall(cur)


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowRuleCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    _validate_rule(body.trigger_type, body.trigger_config, body.action_type, body.action_config)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO workflow_rules (name, trigger_type, trigger_config, action_type, action_config, is_active, vertical, created_by, account_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (body.name, body.trigger_type, json.dumps(body.trigger_config), body.action_type,
             json.dumps(body.action_config), body.is_active, body.vertical, current_user["id"],
             current_user["account_id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    return row


@router.patch("/workflows/{rule_id}")
def update_workflow(rule_id: int, body: WorkflowRuleUpdate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    # Validate against the merged (current ⊕ patch) rule so a partial update
    # can't leave an inconsistent trigger/action combination behind.
    with db.cursor() as cur:
        cur.execute(
            "SELECT trigger_type, trigger_config, action_type, action_config FROM workflow_rules "
            "WHERE id = %s AND account_id = %s",
            (rule_id, current_user["account_id"]),
        )
        current = dict_fetchone(cur)
    if not current:
        raise HTTPException(status_code=404, detail="Rule not found")
    for key in ("trigger_config", "action_config"):
        if isinstance(current[key], str):
            current[key] = json.loads(current[key])
    _validate_rule(
        body.trigger_type if body.trigger_type is not None else current["trigger_type"],
        body.trigger_config if body.trigger_config is not None else current["trigger_config"],
        body.action_type if body.action_type is not None else current["action_type"],
        body.action_config if body.action_config is not None else current["action_config"],
    )

    sets, params = [], []
    if body.name is not None:
        sets.append("name = %s"); params.append(body.name)
    if body.trigger_type is not None:
        sets.append("trigger_type = %s"); params.append(body.trigger_type)
    if body.trigger_config is not None:
        sets.append("trigger_config = %s"); params.append(json.dumps(body.trigger_config))
    if body.action_type is not None:
        sets.append("action_type = %s"); params.append(body.action_type)
    if body.action_config is not None:
        sets.append("action_config = %s"); params.append(json.dumps(body.action_config))
    if body.is_active is not None:
        sets.append("is_active = %s"); params.append(body.is_active)
    if body.vertical is not None:
        sets.append("vertical = %s"); params.append(body.vertical)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    sets.append("updated_at = NOW()")
    params.extend([rule_id, current_user["account_id"]])
    with db.cursor() as cur:
        cur.execute(f"UPDATE workflow_rules SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *", params)
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return row


@router.delete("/workflows/{rule_id}", status_code=204)
def delete_workflow(rule_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM workflow_rules WHERE id = %s AND account_id = %s RETURNING id", (rule_id, current_user["account_id"]))
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
                "INSERT INTO workflow_rules (name, trigger_type, trigger_config, action_type, action_config, vertical, created_by, account_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (rule["name"], rule.get("trigger_type", "status_change"),
                 json.dumps(rule["trigger_config"]),
                 rule.get("action_type", "create_task"), json.dumps(rule["action_config"]),
                 vertical, current_user["id"], current_user["account_id"]),
            )
            created.append(dict_fetchone(cur))
        db.commit()
    return {"created": len(created), "rules": created}
