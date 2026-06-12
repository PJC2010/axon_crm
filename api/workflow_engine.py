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

    lead_vertical = _get_lead_vertical(conn, lead_id, account_id)

    results = []
    for rule in rules:
        if not _matches_trigger(rule, old_status, new_status):
            continue

        if rule["vertical"] and rule["vertical"] != lead_vertical:
            continue

        try:
            result = _execute_action(conn, rule, lead_id, user_id, account_id)
            if result:
                results.append(result)
        except Exception as exc:
            log.exception("Workflow rule %d failed for lead %d", rule["id"], lead_id)
            results.append({
                "action": "rule_failed",
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "error": str(exc),
            })

    return results


def execute_signal_event_rules(conn, account_id: int, events: list[dict]) -> list[dict]:
    """Run active signal_event rules against pipeline-detected timing signals.

    `events` are dicts with property_id, vertical, signal_type (from
    pipeline/signals.py). Actions run as the rule's creator since there is no
    acting user in a pipeline run. Returns action results, including failures.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE trigger_type = 'signal_event' AND is_active = TRUE AND account_id = %s",
            (account_id,),
        )
        rules = dict_fetchall(cur)
    if not rules or not events:
        return []

    results = []
    for event in events:
        for rule in rules:
            cfg = rule["trigger_config"]
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            if cfg.get("signal_type") and cfg["signal_type"] != event["signal_type"]:
                continue
            if rule["vertical"] and rule["vertical"] != event["vertical"]:
                continue

            try:
                result = _execute_action(conn, rule, event["property_id"], rule["created_by"], account_id)
                if result:
                    results.append(result)
            except Exception as exc:
                log.exception("Signal rule %d failed for lead %d", rule["id"], event["property_id"])
                results.append({
                    "action": "rule_failed",
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "error": str(exc),
                })
    return results


def execute_quote_event_rules(conn, account_id: int, lead_id: int | None, event: str, user_id: int) -> list[dict]:
    """Run active quote_event rules for a quote lifecycle event.

    `event` is one of: sent, accepted, declined. Rules whose trigger_config
    names a different event are skipped. Lead-targeting actions are skipped
    when the quote isn't linked to a lead (lead_id is None). Public-page
    events have no acting user, so callers pass the quote's creator.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE trigger_type = 'quote_event' AND is_active = TRUE AND account_id = %s",
            (account_id,),
        )
        rules = dict_fetchall(cur)
    if not rules:
        return []

    lead_vertical = _get_lead_vertical(conn, lead_id, account_id) if lead_id else None

    results = []
    for rule in rules:
        cfg = rule["trigger_config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        if cfg.get("event") and cfg["event"] != event:
            continue
        if rule["vertical"] and rule["vertical"] != lead_vertical:
            continue
        if lead_id is None:
            continue  # all current actions target the linked lead

        try:
            result = _execute_action(conn, rule, lead_id, user_id, account_id)
            if result:
                results.append(result)
        except Exception as exc:
            log.exception("Quote rule %d failed for lead %s", rule["id"], lead_id)
            results.append({
                "action": "rule_failed",
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "error": str(exc),
            })
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


def _get_lead_vertical(conn, lead_id: int, account_id: int) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT vertical FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
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
    if action_type == "move_lead_status":
        return _move_lead_status(conn, cfg, lead_id, user_id, account_id)

    log.warning("Unknown action_type: %s", action_type)
    return None


def _move_lead_status(conn, cfg: dict, lead_id: int, user_id: int, account_id: int) -> dict | None:
    """Move the linked lead to cfg["status"] with full side effects.

    Chains into status_change rules (e.g. quote accepted → lead to won →
    "Schedule job date" task), so one quote event can drive the whole
    pipeline response. No-op when the lead is already in that status.
    """
    new_status = cfg.get("status")
    if not new_status:
        return None
    # No-op when already there, so repeated events don't re-log transitions
    # or re-fire chained rules.
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM properties WHERE id = %s AND account_id = %s", (lead_id, account_id))
        row = cur.fetchone()
    if not row or row[0] == new_status:
        return None

    from api.lead_logic import apply_status_change
    _, chained = apply_status_change(conn, lead_id, new_status, user_id, account_id)
    return {"action": "lead_moved", "lead_id": lead_id, "status": new_status, "chained_actions": chained}


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
    "roofing": [
        {
            "name": "Schedule roof inspection",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Schedule on-roof inspection", "due_days_offset": 1, "priority": "high"},
        },
        {
            "name": "Follow up on estimate",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Follow up on roofing estimate", "due_days_offset": 4, "priority": "normal"},
        },
        {
            "name": "Order materials",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Order materials and schedule crew", "due_days_offset": 2, "priority": "high"},
        },
    ],
    "hvac": [
        {
            "name": "Ask system age",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Confirm system age and last service date", "due_days_offset": 1, "priority": "normal"},
        },
        {
            "name": "Follow up on quote",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Follow up on HVAC quote", "due_days_offset": 3, "priority": "normal"},
        },
        {
            "name": "Schedule install",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Schedule installation date", "due_days_offset": 2, "priority": "high"},
        },
    ],
    "fencing": [
        {
            "name": "Schedule measurement",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Schedule property line measurement", "due_days_offset": 2, "priority": "normal"},
        },
        {
            "name": "Follow up on quote",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Follow up on fencing quote", "due_days_offset": 5, "priority": "normal"},
        },
        {
            "name": "Check HOA/permit requirements",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Verify HOA and permit requirements before build", "due_days_offset": 2, "priority": "high"},
        },
    ],
    "landscaping": [
        {
            "name": "Schedule walkthrough",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Schedule yard walkthrough", "due_days_offset": 2, "priority": "normal"},
        },
        {
            "name": "Follow up on proposal",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Follow up on landscaping proposal", "due_days_offset": 5, "priority": "normal"},
        },
        {
            "name": "Offer recurring plan",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Offer recurring maintenance plan", "due_days_offset": 7, "priority": "normal"},
        },
    ],
    "pressure_washing": [
        {
            "name": "Confirm surfaces",
            "trigger_config": {"from_status": "new", "to_status": "contacted"},
            "action_config": {"title": "Confirm surfaces and square footage", "due_days_offset": 1, "priority": "normal"},
        },
        {
            "name": "Follow up on quote",
            "trigger_config": {"to_status": "quote_sent"},
            "action_config": {"title": "Follow up on pressure-washing quote", "due_days_offset": 3, "priority": "normal"},
        },
        {
            "name": "Schedule job",
            "trigger_config": {"to_status": "won"},
            "action_config": {"title": "Schedule job and confirm water access", "due_days_offset": 2, "priority": "high"},
        },
    ],
}

# Timing-signal automations every vertical benefits from: react when the
# pipeline detects a sale or fresh permit activity (see pipeline/signals.py).
_SIGNAL_DEFAULTS = [
    {
        "name": "New owner follow-up",
        "trigger_type": "signal_event",
        "trigger_config": {"signal_type": "just_sold"},
        "action_config": {"title": "Property just sold — reach out to the new homeowner", "due_days_offset": 3, "priority": "high"},
    },
    {
        "name": "Permit activity follow-up",
        "trigger_type": "signal_event",
        "trigger_config": {"signal_type": "new_permit"},
        "action_config": {"title": "Owner is pulling permits — call about related work", "due_days_offset": 2, "priority": "normal"},
    },
]

# Quote-event automations every vertical benefits from. Moving the lead chains
# into the status_change rules above, so "sent" also gets the vertical's
# follow-up task and "accepted" gets its schedule-the-job task for free.
_QUOTE_DEFAULTS = [
    {
        "name": "Quote sent → move lead to Quote Sent",
        "trigger_type": "quote_event",
        "trigger_config": {"event": "sent"},
        "action_type": "move_lead_status",
        "action_config": {"status": "quote_sent"},
    },
    {
        "name": "Quote accepted → move lead to Won",
        "trigger_type": "quote_event",
        "trigger_config": {"event": "accepted"},
        "action_type": "move_lead_status",
        "action_config": {"status": "won"},
    },
    {
        "name": "Quote declined → ask why",
        "trigger_type": "quote_event",
        "trigger_config": {"event": "declined"},
        "action_config": {"title": "Quote declined — call to ask why and salvage the job", "due_days_offset": 1, "priority": "high"},
    },
]

for _rules in VERTICAL_DEFAULTS.values():
    _rules.extend(_SIGNAL_DEFAULTS)
    _rules.extend(_QUOTE_DEFAULTS)
