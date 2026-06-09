"""Workflow automation engine.

Evaluates active workflow rules when lead status changes and executes
matching actions (e.g., auto-creating tasks).
"""
import json
import logging
from datetime import datetime, timedelta

from api.deps import dict_fetchall

log = logging.getLogger(__name__)


def execute_status_change_rules(conn, lead_id: int, old_status: str | None, new_status: str, user_id: int, account_id: int) -> list[dict]:
    """Run all active status_change rules that match this transition.

    Only this org's rules are evaluated, and any actions they create are
    written under the same account. Returns a list of action results (e.g.,
    created tasks) so the caller can relay feedback to the frontend.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE trigger_type = 'status_change' AND is_active = TRUE AND account_id = %s",
            (account_id,),
        )
        rules = dict_fetchall(cur)

    results = []
    for rule in rules:
        if not _matches_trigger(rule, old_status, new_status):
            continue

        lead_vertical = _get_lead_vertical(conn, lead_id)
        if rule["vertical"] and rule["vertical"] != lead_vertical:
            continue

        try:
            result = _execute_action(conn, rule, lead_id, user_id, account_id)
            if result:
                results.append(result)
        except Exception:
            log.exception("Workflow rule %d failed for lead %d", rule["id"], lead_id)

    return results


def _matches_trigger(rule: dict, old_status: str | None, new_status: str) -> bool:
    cfg = rule["trigger_config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)

    from_match = cfg.get("from_status")
    to_match = cfg.get("to_status")

    if from_match and from_match != old_status:
        return False
    if to_match and to_match != new_status:
        return False

    return True


def _get_lead_vertical(conn, lead_id: int) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT vertical FROM properties WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    return row[0] if row else None


def _execute_action(conn, rule: dict, lead_id: int, user_id: int, account_id: int) -> dict | None:
    action_type = rule["action_type"]
    cfg = rule["action_config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)

    if action_type == "create_task":
        return _create_task(conn, cfg, lead_id, user_id, rule["name"], account_id)
    if action_type == "log_history":
        return _log_history(conn, cfg, lead_id, user_id)

    log.warning("Unknown action_type: %s", action_type)
    return None


def _create_task(conn, cfg: dict, lead_id: int, user_id: int, rule_name: str, account_id: int) -> dict:
    title = cfg.get("title", rule_name)
    priority = cfg.get("priority", "normal")
    due_days = cfg.get("due_days_offset", 3)
    due_date = (datetime.utcnow() + timedelta(days=due_days)).date().isoformat()

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tasks (property_id, title, due_date, priority, created_by, account_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, title, due_date, priority",
            (lead_id, title, due_date, priority, user_id, account_id),
        )
        row = cur.fetchone()
    conn.commit()
    return {"action": "task_created", "task_id": row[0], "title": row[1], "due_date": str(row[2]), "priority": row[3]}


def _log_history(conn, cfg: dict, lead_id: int, user_id: int) -> dict:
    action_text = cfg.get("action", "Automation")
    outcome = cfg.get("outcome")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, created_by) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (lead_id, action_text, outcome, user_id),
        )
        row = cur.fetchone()
    conn.commit()
    return {"action": "history_logged", "history_id": row[0]}


VERTICAL_DEFAULTS = {
    "epoxy_flooring": [
        {
            "name": "Send quote within 24hr",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Send quote within 24 hours", "due_days_offset": 1, "priority": "high"},
        },
        {
            "name": "Schedule job date",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Schedule job date with homeowner", "due_days_offset": 2, "priority": "high"},
        },
        {
            "name": "Follow up on quote",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Follow up on quote", "due_days_offset": 5, "priority": "normal"},
        },
    ],
    "pool_maintenance": [
        {
            "name": "Verify pool details",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Verify pool type and size", "due_days_offset": 1, "priority": "normal"},
        },
        {
            "name": "Prepare equipment checklist",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Prepare equipment checklist", "due_days_offset": 3, "priority": "normal"},
        },
        {
            "name": "Schedule first service",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Schedule first service visit", "due_days_offset": 2, "priority": "high"},
        },
    ],
    "solar": [
        {
            "name": "Check roof orientation",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Check roof orientation and shading", "due_days_offset": 2, "priority": "normal"},
        },
        {
            "name": "Follow up on proposal",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Follow up on solar proposal", "due_days_offset": 7, "priority": "normal"},
        },
        {
            "name": "Submit permit application",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Submit permit application", "due_days_offset": 3, "priority": "high"},
        },
    ],
}
