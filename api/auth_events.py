"""Best-effort auth-event recording (migration 0073).

One row per login attempt — success and failure, password and OAuth — feeding
the admin security panel (api/routes/admin.py) and ``users.last_login_at``.
Recording must never break a login: everything is wrapped, a failed insert is
logged and swallowed, and the connection is rolled back so the caller's
transaction state stays clean.
"""
import logging

log = logging.getLogger(__name__)


def record_auth_event(db, *, success: bool, method: str = "password",
                      user_id: int | None = None, account_id: int | None = None,
                      identifier: str | None = None, failure_reason: str | None = None,
                      ip: str | None = None, user_agent: str | None = None) -> None:
    """Insert an auth_events row; on success also stamp users.last_login_at.

    Commits its own writes: it runs at the very end of a login handler (or
    immediately before the handler raises its 401/403) on the per-request
    connection, so nothing else is pending. Never raises.
    """
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO auth_events (user_id, account_id, attempted_identifier, "
                "method, success, failure_reason, ip, user_agent) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, account_id, identifier, method, success,
                 failure_reason, ip, (user_agent or "")[:512] or None),
            )
            if success and user_id is not None:
                cur.execute(
                    "UPDATE users SET last_login_at = NOW() WHERE id = %s", (user_id,)
                )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        log.warning("Failed to record auth event (method=%s success=%s)",
                    method, success, exc_info=True)
