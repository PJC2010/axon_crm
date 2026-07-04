"""Shared lead status-change logic.

Extracted from api/routes/leads.py so non-route code (e.g. quote-event
workflow actions moving a lead to quote_sent/won) can change status with the
same side effects as the API route: stage_transitions audit row, status_change
workflow rules, and the neighbor door-knock task on a win.
"""
import logging

from api.deps import dict_fetchone

log = logging.getLogger(__name__)


def apply_status_change(conn, lead_id: int, new_status: str, user_id: int, account_id: int) -> tuple[dict | None, list[dict]]:
    """Move a lead to `new_status` with full side effects.

    Returns (lead_row, workflow_results); lead_row is None when the lead
    doesn't exist in this account.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM properties WHERE id = %s AND account_id = %s", (lead_id, account_id))
        prev = cur.fetchone()
        old_status = prev[0] if prev else None

        cur.execute(
            "UPDATE properties SET status = %s, stage_moved_at = NOW() WHERE id = %s AND account_id = %s RETURNING *",
            (new_status, lead_id, account_id),
        )
        row = dict_fetchone(cur)
        if not row:
            return None, []

        cur.execute(
            "INSERT INTO stage_transitions (property_id, from_status, to_status, transitioned_by) "
            "VALUES (%s, %s, %s, %s)",
            (lead_id, old_status, new_status, user_id),
        )
        conn.commit()

    from api.workflow_engine import execute_status_change_rules
    workflow_results = execute_status_change_rules(conn, lead_id, old_status, new_status, user_id, account_id)

    # Winning a job makes the surrounding street the cheapest lead source —
    # queue a door-knock task for nearby uncontacted leads.
    if new_status == "won" and old_status != "won":
        from api.neighbors import create_neighbor_task
        try:
            neighbor_result = create_neighbor_task(conn, lead_id, account_id, user_id)
            if neighbor_result:
                workflow_results.append(neighbor_result)
        except Exception:
            log.exception("Neighbor task creation failed for lead %d", lead_id)

    # Becoming a customer (won/converted) reshapes the geo landscape for nearby
    # leads — enqueue a blast-radius re-score off the request path.
    from config import CUSTOMER_STATUSES
    if new_status in CUSTOMER_STATUSES and old_status not in CUSTOMER_STATUSES:
        try:
            from api.scheduler import enqueue_customer_geo_rescore
            enqueue_customer_geo_rescore(account_id, lead_id)
        except Exception:
            log.exception("Could not enqueue geo rescore for new customer %d", lead_id)

    return row, workflow_results
