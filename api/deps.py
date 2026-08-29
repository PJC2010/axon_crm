"""FastAPI dependencies: DB connection and auth."""
import threading
import time

import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError

from config import (
    DASHBOARD_STATEMENT_TIMEOUT_MS, DATABASE_URL, DB_CONNECT_TIMEOUT_SECONDS,
    DB_POOL_MAX, DB_POOL_MIN, DB_STATEMENT_TIMEOUT_MS,
)

# ── Database ──────────────────────────────────────────────────────────────────

# Bounded per-instance pool: without one, every request opened a fresh Postgres
# connection, and 2 web instances × uvicorn's ~40-thread pool + the in-process
# scheduler could exhaust a small managed Postgres' connection cap in a burst.
# Lazily created so importing this module (tests, scripts) never dials the DB.
_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()

# How long a request waits for a free pooled connection before giving up.
_POOL_WAIT_SECONDS = 5.0


def _connect_options() -> str:
    if DB_STATEMENT_TIMEOUT_MS > 0:
        return f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}"
    return ""


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    DB_POOL_MIN, DB_POOL_MAX, DATABASE_URL,
                    connect_timeout=DB_CONNECT_TIMEOUT_SECONDS,
                    options=_connect_options(),
                    # Detect a silently dropped server (restart, failover)
                    # instead of holding a dead socket for kernel-default hours.
                    keepalives=1, keepalives_idle=30,
                    keepalives_interval=10, keepalives_count=3,
                )
    return _pool


def get_db():
    pool = _get_pool()
    deadline = time.monotonic() + _POOL_WAIT_SECONDS
    while True:
        try:
            conn = pool.getconn()
            break
        except psycopg2.pool.PoolError:
            # Pool exhausted: brief wait beats an instant 500 under a burst.
            if time.monotonic() >= deadline:
                raise HTTPException(status_code=503,
                                    detail="Server busy — try again shortly.")
            time.sleep(0.05)
    broken = False
    try:
        yield conn
    finally:
        try:
            # A connection goes back to the pool only in a clean state: an
            # uncommitted transaction must never leak into the next request.
            conn.rollback()
        except Exception:
            broken = True
        pool.putconn(conn, close=broken or conn.closed)


def soft_query(db, fn, fallback, *, timeout_ms: int | None = None):
    """Run one read under a tighter statement_timeout; degrade instead of 500.

    Returns ``(value, timed_out)``. On timeout the value is `fallback` and the
    caller is expected to mark its response degraded rather than raise, so a
    dashboard panel that cannot answer shows the rest of the page.

    Three details are load-bearing:

    * ``SET LOCAL`` — not ``SET``. These connections are pooled and long-lived;
      a session-level timeout would follow the connection into every later
      request. LOCAL lapses with the transaction below.
    * The ``rollback()`` is mandatory, not tidiness. A cancelled statement
      leaves the transaction ABORTED, and every subsequent statement on that
      connection fails with InFailedSqlTransaction until it is unwound. The
      endpoints here run several queries in sequence, so without this the first
      timeout would take the whole response down anyway — which is exactly the
      500 this function exists to prevent.
    * ``QueryCanceled`` only. A cancelled statement is the expected outcome of a
      cap; a syntax error, a permissions failure or a dropped connection are
      not, and must still surface. psycopg2 raises QueryCanceled for both a
      statement_timeout and a server-side pg_cancel_backend, and treating the
      latter as a degraded panel is the correct reading too.

    A statement that is genuinely fast is unaffected: the SET LOCAL costs one
    round trip on a connection the request already holds.
    """
    ms = DASHBOARD_STATEMENT_TIMEOUT_MS if timeout_ms is None else timeout_ms
    try:
        with db.cursor() as cur:
            if ms and ms > 0:
                cur.execute("SELECT set_config('statement_timeout', %s, true)",
                            (str(int(ms)),))
            value = fn(cur)
            # Hand the cap back, on the success path only. SET LOCAL is scoped
            # to the TRANSACTION, not to this call, and a request does more than
            # its degradable reads: /api/pipeline/alerts then runs the scoring
            # quota masker on the same connection. Leaving 5s in force would put
            # security-relevant code — which must never fail open, and so is
            # deliberately NOT wrapped in soft_query — under a budget it was
            # never designed for, and a cancel there would 500 the very endpoint
            # this function exists to keep up.
            #
            # Not a `finally`: on the cancel path the transaction is already
            # ABORTED, and issuing this there would raise InFailedSqlTransaction
            # over the top of the QueryCanceled we need to catch. The rollback
            # below discards the setting anyway.
            if ms and ms > 0:
                cur.execute("SELECT set_config('statement_timeout', %s, true)",
                            (str(int(DB_STATEMENT_TIMEOUT_MS)),))
            return value, False
    except psycopg2.errors.QueryCanceled:
        # Unwind the aborted transaction so the caller's next query can run.
        # This also discards the SET LOCAL, so the reset above is only needed on
        # the path where the transaction survives.
        db.rollback()
        return fallback, True


def dict_fetchall(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def dict_fetchone(cur) -> dict | None:
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


# ── Auth ──────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def _query_token_allowed(path: str) -> bool:
    """The ``?token=`` fallback exists only for ``<a download>`` links, where
    headers can't be set (frontend/lib/api.ts: exportUrl, invoiceExportUrl,
    expenseExportUrl, qboExportUrl, invoicePdfUrl). Everywhere else a URL-borne
    session token just leaks into access logs and browser history, so the
    fallback is scoped to exactly those download routes."""
    if path == "/api/export" or path.startswith("/api/export/"):
        return True
    if path.endswith("/export"):          # /api/invoices/export, /api/expenses/export
        return True
    if path.startswith("/api/invoices/") and path.endswith("/pdf"):
        return True
    return False


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(None),
    db=Depends(get_db),
) -> dict:
    """Decode JWT and return the user row. Raises 401 if missing/invalid.

    The token normally arrives in the ``Authorization: Bearer`` header. As a
    fallback it may be passed as a ``?token=`` query param on the CSV/PDF
    download routes only (see _query_token_allowed).
    """
    from api.security import decode_token  # late import avoids circular deps

    raw_token = credentials.credentials if credentials is not None else None
    if raw_token is None and token and _query_token_allowed(request.url.path):
        raw_token = token
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(raw_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, is_active, account_id, "
            "is_platform_admin, email_verified, password_changed_at "
            "FROM users WHERE id = %s",
            (user_id,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    user = dict(zip(cols, row))
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")
    # A password reset invalidates every token issued before it — the reset is
    # what a compromised user does, so a stolen session must not survive it.
    # Tokens minted before `iat` existed count as pre-change and are rejected
    # too (only for users who have actually changed their password).
    changed_at = user.pop("password_changed_at", None)
    if changed_at is not None:
        issued_at = payload.get("iat")
        # +1s grace: iat is truncated to whole seconds, so a login in the same
        # second as the reset must not be rejected as pre-change.
        if issued_at is None or issued_at + 1 < changed_at.timestamp():
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def require_verified_sender(current_user: dict = Depends(get_current_user)) -> dict:
    """Gate for outbound customer messaging (lead messages, invoice/quote
    delivery). Those sends ride the platform's Resend/Twilio identity, so an
    unverified self-serve signup must not reach them — a bot with a fabricated
    email would otherwise send spam from the platform's domain minutes after
    signing up. Existing users were backfilled verified (migration 0055), so
    this only bites accounts that never clicked their verification link.
    """
    if not current_user.get("email_verified"):
        raise HTTPException(
            status_code=403,
            detail="Verify your email address to send messages — check your "
                   "inbox for the verification link, or re-send it from Settings.",
        )
    return current_user


def require_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner access required")
    return current_user


def require_platform_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Gate for the cross-tenant /api/admin surface (api/routes/admin.py).

    Orthogonal to ``require_owner``: ``role`` governs power inside one org,
    ``users.is_platform_admin`` (migration 0073) governs the whole platform.
    The flag is read from the DB on every request, never from the JWT, so
    revocation takes effect immediately.
    """
    if not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return current_user
