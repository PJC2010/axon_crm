"""Neighbor-of-customer targeting.

The cheapest lead a service business gets is the house next to a job site.
When a lead is won, look up nearby uncontacted leads (same geohash cell —
~1.2 km at precision 6 — using the geohash already populated by the geocode
pipeline step) and create a door-knock task so the crew works the street
while they're there.
"""
import logging

from api.deps import dict_fetchall

log = logging.getLogger(__name__)

GEOHASH_PRECISION = 6   # ~1.2km x 0.6km cell — "same street/block" scale
NEIGHBOR_LIMIT = 10


def find_neighbors(conn, lead_id: int, account_id: int, limit: int = NEIGHBOR_LIMIT) -> list[dict]:
    """Best uncontacted leads in the same geohash cell as `lead_id`."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT geohash FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return []
        cell = row[0][:GEOHASH_PRECISION]

        cur.execute(
            "SELECT id, address, zip, lead_score, score_grade, vertical, lead_source "
            "FROM properties "
            "WHERE account_id = %s AND id != %s AND archived_at IS NULL "
            "  AND status = 'new' AND geohash IS NOT NULL "
            "  AND LEFT(geohash, %s) = %s "
            "ORDER BY lead_score DESC NULLS LAST "
            "LIMIT %s",
            (account_id, lead_id, GEOHASH_PRECISION, cell, limit),
        )
        return dict_fetchall(cur)


def create_neighbor_task(conn, lead_id: int, account_id: int, user_id: int) -> dict | None:
    """Create a door-knock task for neighbors of a just-won lead.

    Returns an action-result dict (same shape the workflow engine uses) or
    None when there are no neighbors or an equivalent open task already exists.
    """
    neighbors = find_neighbors(conn, lead_id, account_id)
    if not neighbors:
        return None

    with conn.cursor() as cur:
        cur.execute(
            "SELECT address FROM properties WHERE id = %s AND account_id = %s",
            (lead_id, account_id),
        )
        row = cur.fetchone()
        address = (row[0] if row else None) or "this job site"

        # Don't stack duplicates if the lead bounces in and out of won.
        cur.execute(
            "SELECT 1 FROM tasks WHERE property_id = %s AND account_id = %s "
            "AND is_complete = FALSE AND title LIKE 'Knock %% doors near %%' LIMIT 1",
            (lead_id, account_id),
        )
        if cur.fetchone():
            return None

        title = f"Knock {len(neighbors)} doors near {address} — neighbors of a new customer"
        cur.execute(
            "INSERT INTO tasks (property_id, title, due_date, priority, created_by, account_id) "
            "VALUES (%s, %s, CURRENT_DATE + 3, 'high', %s, %s) RETURNING id",
            (lead_id, title, user_id, account_id),
        )
        task_id = cur.fetchone()[0]
    conn.commit()

    log.info("Neighbor task %d created for won lead %d (%d neighbors)", task_id, lead_id, len(neighbors))
    return {
        "action": "neighbor_task_created",
        "task_id": task_id,
        "title": title,
        "neighbor_count": len(neighbors),
        "neighbor_ids": [n["id"] for n in neighbors],
    }
