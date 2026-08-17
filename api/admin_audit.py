"""Admin-action audit trail (migration 0073).

Every mutation made through the /api/admin surface records who did what to
which target. Deliberately does NOT commit: the caller runs it in the same
transaction as the mutation and commits both together, so the trail can never
disagree with the data. ``detail`` carries diffs (changed fields, plan names) —
never tokens or passwords.

The actor is stored twice on purpose (migration 0074): ``admin_user_id`` is the
live link, ``admin_username`` a denormalized copy taken at write time. Platform
admins are deletable now, and when one is deleted the FK goes NULL — the copy is
what keeps the row saying who did it. Same trade 0073 made for
``auth_events.account_id``.
"""
from psycopg2.extras import Json


def record_admin_action(db, admin: dict, action: str,
                        target_type: str | None = None,
                        target_id: int | str | None = None,
                        detail: dict | None = None) -> None:
    """``admin`` is the row from require_platform_admin (needs id + username)."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO admin_audit_log "
            "(admin_user_id, admin_username, action, target_type, target_id, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (admin.get("id"), admin.get("username"), action, target_type,
             str(target_id) if target_id is not None else None, Json(detail or {})),
        )
