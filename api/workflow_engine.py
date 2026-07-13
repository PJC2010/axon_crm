"""Workflow automation engine.

Evaluates active workflow rules on lead lifecycle events (status changes,
signals, imports, quote events) and on the daily scheduled tick (date_offset /
inactivity triggers) and executes matching actions (e.g., auto-creating tasks).
"""
import json
import logging
from datetime import datetime, timedelta

from api.deps import dict_fetchall, dict_fetchone

log = logging.getLogger(__name__)

# ── Scheduled (date-based) trigger sources ────────────────────────────────────
# Whitelist of tables/date columns a `date_offset` rule may target. SQL is built
# only from these entries — never from user input — so rule configs cannot
# inject identifiers. Each source yields (target_id, lead_id, anchor) rows;
# `lead_id` is the properties row actions run against, `target_id` + the
# anchor's date value form the idempotency key in workflow_rule_firings.
# Later phases add child-object tables (policies, orders, appointments) here —
# the daily tick needs no changes.
DATE_TRIGGER_SOURCES = {
    "properties": {
        "target_type": "property",
        "table": "properties",
        "fields": ("last_sale_date", "refi_date", "last_storm_date", "created_at"),
        "id_col": "id",
        "lead_col": "id",
        "extra_where": "AND archived_at IS NULL",
    },
    # Child objects (Phase 5): actions run against the linked lead, so rows
    # without a property_id are skipped; the child row is the dedup target so
    # e.g. each policy's renewal fires independently.
    "policies": {
        "target_type": "policy",
        "table": "policies",
        "fields": ("effective_date", "expiration_date"),
        "id_col": "id",
        "lead_col": "property_id",
        "extra_where": "AND property_id IS NOT NULL",
    },
    "orders": {
        "target_type": "order",
        "table": "orders",
        "fields": ("order_date",),
        "id_col": "id",
        "lead_col": "property_id",
        "extra_where": "AND property_id IS NOT NULL",
    },
    "appointments": {
        "target_type": "appointment",
        "table": "appointments",
        "fields": ("starts_at",),
        "id_col": "id",
        "lead_col": "property_id",
        "extra_where": "AND property_id IS NOT NULL",
    },
    # "N days after a job was won" — anchors on the win's stage transition, so
    # the firings ledger fires the rule once per win (a re-won lead re-arms).
    # stage_transitions has no account_id column; this static subquery joins it
    # in from the lead. Powers the review-request default (business_types.py).
    "won_transitions": {
        "target_type": "stage_transition",
        "table": ("(SELECT st.id, st.property_id, st.transitioned_at, p.account_id "
                  "FROM stage_transitions st JOIN properties p ON p.id = st.property_id "
                  "WHERE st.to_status = 'won' AND p.archived_at IS NULL) won_transitions"),
        "fields": ("transitioned_at",),
        "id_col": "id",
        "lead_col": "property_id",
    },
}

# Object types whose routes fire lifecycle events ({object_type}_event rules).
OBJECT_EVENT_TYPES = ("policy", "order", "appointment")


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


def execute_import_rules(conn, account_id: int, lead_ids: list[int], user_id: int) -> list[dict]:
    """Run active lead_imported rules against rows just created by an import.

    Fires once per newly inserted lead (updates to existing leads don't fire, so
    re-imports stay quiet). `user_id` is the importing user, who owns any tasks
    the rules create. Vertical-scoped rules only apply to leads in that vertical.
    Returns action results, including failures, for the import response.
    """
    if not lead_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE trigger_type = 'lead_imported' AND is_active = TRUE AND account_id = %s",
            (account_id,),
        )
        rules = dict_fetchall(cur)
    if not rules:
        return []

    results = []
    for lead_id in lead_ids:
        lead_vertical = _get_lead_vertical(conn, lead_id, account_id)
        for rule in rules:
            if rule["vertical"] and rule["vertical"] != lead_vertical:
                continue
            try:
                result = _execute_action(conn, rule, lead_id, user_id, account_id)
                if result:
                    results.append(result)
            except Exception as exc:
                log.exception("Import rule %d failed for lead %d", rule["id"], lead_id)
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


def execute_object_event_rules(conn, account_id: int, lead_id: int | None,
                               object_type: str, event: str, user_id: int) -> list[dict]:
    """Run active {object_type}_event rules for a child-object lifecycle event.

    Mirrors execute_quote_event_rules: `event` is 'created' or the object's new
    status (e.g. 'active', 'refunded', 'no_show'); rules whose trigger_config
    names a different event are skipped, and lead-targeting actions are skipped
    when the object isn't linked to a lead.
    """
    if object_type not in OBJECT_EVENT_TYPES:
        log.warning("Unknown object_type for event rules: %r", object_type)
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE trigger_type = %s AND is_active = TRUE AND account_id = %s",
            (f"{object_type}_event", account_id),
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
            log.exception("%s rule %d failed for lead %s", object_type, rule["id"], lead_id)
            results.append({
                "action": "rule_failed",
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "error": str(exc),
            })
    return results


def _date_source_sql(source: str, field: str) -> str:
    """Candidate query for a date_offset rule. `source`/`field` are validated
    against DATE_TRIGGER_SOURCES by the caller; params are (account_id, offset_days)."""
    src = DATE_TRIGGER_SOURCES[source]
    return (
        f"SELECT {src['id_col']} AS target_id, {src['lead_col']} AS lead_id, {field}::date AS anchor "
        f"FROM {src['table']} "
        f"WHERE account_id = %s {src.get('extra_where', '')} "
        f"AND {field} IS NOT NULL "
        # Fire when today ≈ anchor + offset (negative offset = before the anchor).
        # The 3-day catch-up window tolerates missed ticks; the firings ledger
        # makes re-scanning those days safe.
        f"AND {field}::date + %s BETWEEN CURRENT_DATE - 3 AND CURRENT_DATE"
    )


def _claim_firing(conn, rule_id: int, account_id: int, target_type: str, target_id: int, fire_key: str) -> bool:
    """Atomically claim a (rule, target, anchor) firing. Returns False when this
    exact firing already happened — the caller must then skip the action."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workflow_rule_firings (rule_id, account_id, target_type, target_id, fire_key) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
            (rule_id, account_id, target_type, target_id, fire_key),
        )
        return cur.fetchone() is not None


def execute_date_offset_rules(conn, account_id: int) -> list[dict]:
    """Run active date_offset rules for one account (called by the daily tick).

    trigger_config: {"source": "properties", "date_field": "last_sale_date",
    "offset_days": -30} — fire when CURRENT_DATE is (anchor + offset_days),
    with a 3-day catch-up window. Actions run as the rule's creator since
    there is no acting user. The workflow_rule_firings ledger keeps a rule
    from firing twice for the same target/anchor.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE trigger_type = 'date_offset' AND is_active = TRUE AND account_id = %s",
            (account_id,),
        )
        rules = dict_fetchall(cur)

    results = []
    for rule in rules:
        cfg = rule["trigger_config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        source = cfg.get("source", "properties")
        field = cfg.get("date_field")
        src = DATE_TRIGGER_SOURCES.get(source)
        if not src or field not in src["fields"]:
            log.warning("date_offset rule %d has invalid source/field %r.%r — skipped", rule["id"], source, field)
            continue
        try:
            offset_days = int(cfg.get("offset_days", 0))
        except (TypeError, ValueError):
            log.warning("date_offset rule %d has non-integer offset_days — skipped", rule["id"])
            continue

        with conn.cursor() as cur:
            cur.execute(_date_source_sql(source, field), (account_id, offset_days))
            candidates = cur.fetchall()

        for target_id, lead_id, anchor in candidates:
            if lead_id is None:
                continue
            if rule["vertical"] and rule["vertical"] != _get_lead_vertical(conn, lead_id, account_id):
                continue
            if not _claim_firing(conn, rule["id"], account_id, src["target_type"], target_id, anchor.isoformat()):
                continue
            try:
                # send_template renders child-object merge fields (e.g. a policy's
                # carrier/expiration in a renewal reminder), so fetch the firing
                # row for it. Other actions don't read context — skip the query.
                extra = None
                if source != "properties" and rule["action_type"] == "send_template":
                    with conn.cursor() as cur:
                        cur.execute(
                            f"SELECT * FROM {src['table']} WHERE id = %s AND account_id = %s",
                            (target_id, account_id),
                        )
                        row = dict_fetchone(cur)
                    if row:
                        extra = {src["target_type"]: row}
                result = _execute_action(conn, rule, lead_id, rule["created_by"], account_id, extra=extra)
                if result:
                    results.append(result)
            except Exception as exc:
                # Roll back so the unclaimed firing is released and retried next tick.
                conn.rollback()
                log.exception("Date rule %d failed for lead %d", rule["id"], lead_id)
                results.append({
                    "action": "rule_failed",
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "error": str(exc),
                })
    return results


def execute_inactivity_rules(conn, account_id: int) -> list[dict]:
    """Run active inactivity rules for one account (called by the daily tick).

    trigger_config: {"days": 60, "statuses": ["contacted", ...]?} — fire for
    leads whose last contact_history touch (or creation, if never contacted)
    is older than `days`. Without an explicit status scope, leads in the
    account's terminal stages (won/lost/...) are excluded so closed work
    doesn't nag. One firing per lapse episode: the fire key is the last-touch
    date, so a new touch re-arms the rule for a future lapse.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM workflow_rules WHERE trigger_type = 'inactivity' AND is_active = TRUE AND account_id = %s",
            (account_id,),
        )
        rules = dict_fetchall(cur)

    results = []
    for rule in rules:
        cfg = rule["trigger_config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        try:
            days = int(cfg.get("days", 0))
        except (TypeError, ValueError):
            days = 0
        if days <= 0:
            log.warning("inactivity rule %d has invalid days — skipped", rule["id"])
            continue
        statuses = cfg.get("statuses") or None

        sql = (
            "SELECT p.id, COALESCE(MAX(ch.created_at), p.created_at) AS last_touch "
            "FROM properties p "
            "LEFT JOIN contact_history ch ON ch.property_id = p.id "
            "WHERE p.account_id = %s AND p.archived_at IS NULL "
        )
        params: list = [account_id]
        if statuses:
            sql += "AND p.status = ANY(%s) "
            params.append(list(statuses))
        else:
            sql += ("AND p.status NOT IN "
                    "(SELECT key FROM pipeline_stages WHERE account_id = %s AND is_terminal) ")
            params.append(account_id)
        if rule["vertical"]:
            sql += "AND p.vertical = %s "
            params.append(rule["vertical"])
        sql += ("GROUP BY p.id, p.created_at "
                "HAVING COALESCE(MAX(ch.created_at), p.created_at) < NOW() - make_interval(days => %s)")
        params.append(days)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            candidates = cur.fetchall()

        for lead_id, last_touch in candidates:
            fire_key = last_touch.date().isoformat() if last_touch else "never"
            if not _claim_firing(conn, rule["id"], account_id, "property", lead_id, fire_key):
                continue
            try:
                result = _execute_action(conn, rule, lead_id, rule["created_by"], account_id)
                if result:
                    results.append(result)
            except Exception as exc:
                conn.rollback()
                log.exception("Inactivity rule %d failed for lead %d", rule["id"], lead_id)
                results.append({
                    "action": "rule_failed",
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "error": str(exc),
                })
    return results


def run_daily_rules(conn) -> dict:
    """Evaluate all accounts' scheduled rules (called by the daily workflow tick).

    Per-account isolation: one account's failure never blocks the rest.
    Returns a summary for the tick's log line.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT account_id FROM workflow_rules "
            "WHERE trigger_type IN ('date_offset', 'inactivity') AND is_active = TRUE"
        )
        account_ids = [r[0] for r in cur.fetchall()]

    summary = {"accounts": len(account_ids), "actions": 0, "failures": 0}
    for account_id in account_ids:
        try:
            results = execute_date_offset_rules(conn, account_id)
            results += execute_inactivity_rules(conn, account_id)
            conn.commit()
            summary["actions"] += sum(1 for r in results if r.get("action") != "rule_failed")
            summary["failures"] += sum(1 for r in results if r.get("action") == "rule_failed")
        except Exception:
            conn.rollback()
            summary["failures"] += 1
            log.exception("Daily workflow rules failed for account %d", account_id)
    return summary


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


def _execute_action(conn, rule: dict, lead_id: int, user_id: int, account_id: int,
                    extra: dict | None = None) -> dict | None:
    """`extra` carries trigger context (e.g. {"policy": row} from a date_offset
    firing on the policies table) for actions that render merge fields."""
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
    if action_type == "send_notification":
        return _send_notification(conn, cfg, lead_id, rule, account_id)
    if action_type == "send_template":
        return _send_template(conn, cfg, lead_id, rule, account_id, extra=extra)

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


def _send_notification(conn, cfg: dict, lead_id: int, rule: dict, account_id: int) -> dict | None:
    """Email the rule's creator about the matched lead ("notify me" semantics).

    Email-only for now (users have no phone column). Fails soft when the email
    channel isn't configured so scheduled rules keep working on hosts without
    Resend — the skip is visible in the results/log rather than an exception.
    """
    from api import notifications

    channel = cfg.get("channel", "email")
    if channel != "email":
        log.warning("send_notification supports only the email channel (got %r)", channel)
        return None

    recipient_id = rule.get("created_by")
    if not recipient_id:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id = %s", (recipient_id,))
        row = cur.fetchone()
    to_email = row[0] if row else None
    if not to_email:
        return None

    if not notifications.email_configured():
        log.info("send_notification skipped for rule %r — email not configured", rule["name"])
        return {"action": "notification_skipped", "rule_name": rule["name"], "reason": "email_not_configured"}

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(contact_name, owner_name, address) FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
        row = cur.fetchone()
    lead_label = (row[0] if row else None) or f"lead #{lead_id}"

    subject = cfg.get("subject") or rule["name"]
    message = cfg.get("message") or subject
    html = (
        '<div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">'
        f'<h2 style="margin:0 0 4px">{subject}</h2>'
        f'<p style="color:#555;margin:0 0 20px">Automation: {rule["name"]} — {lead_label}</p>'
        f"<p>{message}</p>"
        "</div>"
    )
    notifications.send_email(to_email=to_email, subject=subject, html=html)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, created_by) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (lead_id, f"Notification sent — {rule['name']}", None, recipient_id),
        )
        history_id = cur.fetchone()[0]
    conn.commit()
    return {"action": "notification_sent", "rule_name": rule["name"], "to": to_email, "history_id": history_id}


def _send_template(conn, cfg: dict, lead_id: int, rule: dict, account_id: int,
                   extra: dict | None = None) -> dict | None:
    """Message the matched record's own contact from saved template(s).

    Distinct from send_notification (which emails the rule's owner): this
    renders message_templates rows against the record and sends to the record's
    contact email/phone. Two config shapes:

      {"template_id": 5}                                     — single template,
        sent on that template's own channel (legacy rules).
      {"templates": {"sms": 5, "email": 7}, "delivery": m}   — multi-channel;
        m is "sms_first" / "email_first" (send on the preferred channel, fall
        back to the other when the contact has no address for it or the
        provider isn't configured) or "both" (send on every deliverable one).

    `extra` (e.g. {"policy": row}) adds child-object merge fields so a renewal
    reminder can name the expiring policy. Fails soft — missing templates,
    unconfigured channels, or a contact with no address are skipped (surfaced
    in the results), never raised. A provider error on one channel doesn't
    void another channel's completed send: the failure is only re-raised (to
    release the firing claim for retry) when nothing was delivered at all.
    """
    from api import messaging, notifications

    # Resolve the template set and channel plan.
    template_ids: list[int] = []
    delivery = None
    if cfg.get("templates"):
        template_ids = [tid for tid in cfg["templates"].values() if tid]
        delivery = cfg.get("delivery") or "both"
    elif cfg.get("template_id"):
        template_ids = [cfg["template_id"]]
    if not template_ids:
        return None

    by_channel: dict[str, dict] = {}
    for template_id in template_ids:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM message_templates WHERE id = %s AND account_id = %s",
                        (template_id, account_id))
            template = dict_fetchone(cur)
        if template:
            by_channel[template["channel"]] = template
        else:
            log.warning("send_template rule %r references missing template %s", rule["name"], template_id)
    if not by_channel:
        return {"action": "template_skipped", "rule_name": rule["name"], "reason": "template_not_found"}

    if delivery:
        channels, send_all = messaging.channel_order(delivery)
    else:
        channels, send_all = [next(iter(by_channel))], False

    def _configured(ch: str) -> bool:
        return notifications.email_configured() if ch == "email" else notifications.sms_configured()

    skipped: dict[str, str] = {}
    viable = []
    for ch in channels:
        if ch not in by_channel:
            skipped[ch] = "no_template"
        elif not _configured(ch):
            skipped[ch] = "not_configured"
        else:
            viable.append(ch)
    if not viable:
        reason = f"{channels[0]}_not_configured" if by_channel else "template_not_found"
        log.info("send_template skipped for rule %r — %s", rule["name"], skipped)
        return {"action": "template_skipped", "rule_name": rule["name"], "reason": reason, "skipped": skipped}

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, contact_name, contact_email, contact_phone, address, owner_name "
            "FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
        record = dict_fetchone(cur)
    if not record:
        return None

    deliverable = []
    for ch in viable:
        recipient = messaging.recipient_for_channel(record, ch)
        if recipient:
            deliverable.append((ch, recipient))
        else:
            skipped[ch] = "no_address"
    if not deliverable:
        return {"action": "template_skipped", "rule_name": rule["name"],
                "reason": f"no_{viable[0]}_address", "skipped": skipped}

    with conn.cursor() as cur:
        cur.execute("SELECT name, review_link FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
    ctx = messaging.build_context(record, row[0] if row else None,
                                  policy=(extra or {}).get("policy"),
                                  review_link=row[1] if row else None)

    sent = []
    last_error: Exception | None = None
    for channel, recipient in deliverable:
        template = by_channel[channel]
        # A review request without a review link would trail off mid-sentence —
        # skip until the account sets one (Settings → Business profile).
        if not ctx.get("review_link") and (
                messaging.references_field(template["body"], "review_link")
                or messaging.references_field(template.get("subject"), "review_link")):
            skipped[channel] = "no_review_link"
            continue
        body = messaging.render_template(template["body"], ctx)
        try:
            if channel == "email":
                subject = messaging.render_template(template["subject"], ctx) or template["name"]
                notifications.send_email(to_email=recipient, subject=subject, html=body.replace("\n", "<br>"))
            else:
                notifications.send_sms(to_phone=recipient, body=body)
        except Exception as exc:
            log.exception("send_template rule %r failed on %s", rule["name"], channel)
            skipped[channel] = f"send_failed: {exc}"
            last_error = exc
            continue

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO contact_history (property_id, action, outcome, created_by, "
                "channel, direction, body) "
                "VALUES (%s, %s, %s, %s, %s, 'outbound', %s) RETURNING id",
                (lead_id, f"{channel.upper()} sent — {template['name']}", "sent",
                 rule.get("created_by"), channel, body),
            )
            history_id = cur.fetchone()[0]
        sent.append({"channel": channel, "to": recipient, "history_id": history_id})
        if not send_all:
            break

    if not sent:
        if last_error is not None:
            raise last_error
        return {"action": "template_skipped", "rule_name": rule["name"],
                "reason": "not_delivered", "skipped": skipped}

    conn.commit()
    result = {"action": "template_sent", "rule_name": rule["name"],
              "to": sent[0]["to"], "history_id": sent[0]["history_id"], "sent": sent}
    if skipped:
        result["skipped"] = skipped
    return result


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

# Import automations: the moment a fresh lead lands from a CSV/contact import,
# put it on a rep's radar so imported lists actually get worked.
_IMPORT_DEFAULTS = [
    {
        "name": "New imported lead → initial outreach",
        "trigger_type": "lead_imported",
        "trigger_config": {},
        "action_config": {"title": "Initial outreach call to new lead", "due_days_offset": 2, "priority": "high"},
    },
]

for _rules in VERTICAL_DEFAULTS.values():
    _rules.extend(_SIGNAL_DEFAULTS)
    _rules.extend(_QUOTE_DEFAULTS)
    _rules.extend(_IMPORT_DEFAULTS)
