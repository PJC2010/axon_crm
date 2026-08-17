"""Admin-action audit trail (migration 0073).

Every mutation made through the /api/admin surface records who did what to
which target. Deliberately does NOT commit: the caller runs it in the same
transaction as the mutation and commits both together, so the trail can never
disagree with the data. ``detail`` carries diffs (changed fields, plan names) —
never tokens or passwords.
"""
from psycopg2.extras import Json


def record_admin_action(db, admin_user_id: int, action: str,
                        target_type: str | None = None,
                        target_id: int | str | None = None,
                        detail: dict | None = None) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO admin_audit_log (admin_user_id, action, target_type, target_id, detail) "
            "VALUES (%s, %s, %s, %s, %s)",
            (admin_user_id, action, target_type,
             str(target_id) if target_id is not None else None, Json(detail or {})),
        )
