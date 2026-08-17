"""Pure platform-admin logic — validation, classification, config checks.

Split out from the routes (api/routes/admin.py) so it unit-tests without a DB
or network, following the same pattern as api/signup_logic.py and
api/import_logic.py (see tests/test_admin_logic.py).
"""
import re

ADMIN_ROLES = ("owner", "sales_rep")

MAX_PAGE_SIZE = 100

# Unquoted lower-case identifier — every table in this schema. Names reaching
# build_leftover_probe_sql come from information_schema, but they are still
# interpolated into SQL, so they are validated rather than trusted.
TABLE_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def clamp_page(page: int, page_size: int, max_page_size: int = MAX_PAGE_SIZE) -> tuple[int, int]:
    """Sanitize pagination params into (page, page_size) safe for LIMIT/OFFSET."""
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 1)), max_page_size)
    return page, page_size


def classify_login_failure(user_row: dict | None, password_ok: bool) -> str:
    """Server-side failure reason for auth_events. Never surfaced to the client —
    login responses stay generic to avoid account enumeration."""
    if user_row is None:
        return "unknown_user"
    if not password_ok:
        return "bad_password"
    return "inactive"


def parse_forwarded_for(header_value: str | None, fallback: str) -> str:
    """Best client IP from an X-Forwarded-For header.

    Takes the LAST entry: each proxy appends the address it accepted the
    connection from, so the last hop is the only one our own proxy (Render)
    vouches for — earlier entries are client-suppliable. Without a proxy the
    header is absent (or wholly untrusted) and the socket address wins.
    """
    if header_value:
        parts = [p.strip() for p in header_value.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return fallback


def build_reset_url(app_base_url: str, raw_token: str) -> str:
    """The link the existing frontend reset page consumes — same shape as the
    reset email in api/routes/signup.py."""
    return f"{app_base_url.rstrip('/')}/reset-password?token={raw_token}"


def validate_admin_user_update(body: dict, *, is_self: bool) -> list[str]:
    """Problems with an admin PATCH of a user (empty list = valid).

    ``body`` holds only the fields the admin actually sent. The self-lockout
    guards exist because the admin surface has no second door: a platform admin
    who deactivates or demotes themselves locks the whole platform out.
    """
    problems: list[str] = []
    if not body:
        problems.append("No fields to update.")
    if "role" in body and body["role"] not in ADMIN_ROLES:
        problems.append(f"Role must be one of: {', '.join(ADMIN_ROLES)}.")
    if is_self and body.get("is_active") is False:
        problems.append("You cannot deactivate your own account.")
    if is_self and body.get("is_platform_admin") is False:
        problems.append("You cannot revoke your own platform-admin access.")
    return problems


def validate_user_delete(user: dict, *, admin_id: int, siblings: int,
                         other_owners: int) -> list[str]:
    """Problems with hard-deleting a user (empty list = deletable).

    Deleting is not deactivating. ``is_active = FALSE`` keeps the row, so their
    leads stay assigned and their notes stay signed; a delete drops the row and
    every attribution FK pointing at it goes NULL (migration 0074). These guards
    are about the states you cannot climb back out of afterwards:

    ``siblings`` — other users in the same account. The last one going means an
    org that exists but nobody can sign into, and the admin surface has no
    "adopt an orphan org" flow. Deleting the org is the honest operation.

    ``other_owners`` — users in the account with role 'owner', excluding this
    one. An org with no owner still logs in but fails every require_owner
    endpoint, which reads as a broken product rather than a deleted user.

    Platform admins are refused outright: revoking the flag is a PATCH away and
    forces the "am I removing platform access?" decision to be made on its own,
    rather than as a side effect of tidying up a user list.
    """
    problems: list[str] = []
    if user["id"] == admin_id:
        problems.append("You cannot delete your own account.")
    if user.get("is_platform_admin"):
        problems.append("Revoke this user's platform-admin access before deleting them.")
    if siblings == 0:
        problems.append(
            "This is the last user in the organization — delete the organization instead.")
    elif user.get("role") == "owner" and other_owners == 0:
        problems.append(
            "This is the organization's only owner — promote another member to owner first.")
    return problems


def validate_account_delete(account: dict, *, admin_account_id: int | None,
                            confirm_name: str, has_subscription: bool,
                            platform_admins: list[str]) -> list[str]:
    """Problems with hard-deleting an organization (empty list = deletable).

    This one is unrecoverable — the cascade takes every lead, invoice, quote,
    call and note the org ever had — so the guards are deliberately blunt:

    * you cannot delete the org you belong to (it would delete you mid-request,
      and cascade away the audit row recording that you did it);
    * a live Stripe subscription blocks it, matching the plan and trial
      endpoints: Stripe owns that state and would keep billing a dead org;
    * a platform admin living inside the org blocks it, so cross-tenant access
      is never revoked as a side effect of deleting a customer;
    * the org's exact name must be typed back. Deletes here are addressed by
      integer id, and ids are one keystroke apart.
    """
    problems: list[str] = []
    if admin_account_id is not None and admin_account_id == account["id"]:
        problems.append("You cannot delete the organization you belong to.")
    if has_subscription:
        problems.append(
            "This organization has a live Stripe subscription — cancel it in Stripe first.")
    if platform_admins:
        problems.append(
            "Platform admin(s) belong to this organization ("
            + ", ".join(platform_admins)
            + ") — revoke their platform-admin access first.")
    if (confirm_name or "").strip() != account["name"]:
        problems.append("Type the organization's name exactly as shown to confirm.")
    return problems


def build_leftover_probe_sql(tables: list[str]) -> str:
    """One query asking "did anything survive?" of every account-scoped table.

    Built from the live catalog (information_schema) rather than a hand-kept
    list, so a table added later is probed without anyone remembering to add it
    — which is the point, since the failure being guarded against is exactly
    "somebody added a table and forgot". Table names are interpolated, so every
    one is re-checked against ``TABLE_IDENT_RE`` here rather than at the call
    site: the check **is** the injection guard (same rule as pipeline/db.py's
    column allowlist) and putting it next to the interpolation is what stops it
    from being skipped.

    EXISTS rather than COUNT: the expected answer is "no rows", and EXISTS stops
    at the first one instead of counting a table that should be empty. The
    account id is bound once as the named param ``%(id)s`` — psycopg2 binds
    positional ``%s`` in text order, and this statement repeats the same value
    forty-odd times, which is precisely where that goes wrong.
    """
    bad = [t for t in tables if not TABLE_IDENT_RE.match(t)]
    if bad:
        raise ValueError(f"Refusing to interpolate table name(s): {', '.join(bad)}")
    if not tables:
        return "SELECT NULL::text AS table_name WHERE FALSE"
    return "\nUNION ALL\n".join(
        f"SELECT '{t}' AS table_name WHERE EXISTS "
        f"(SELECT 1 FROM {t} WHERE account_id = %(id)s)"
        for t in tables
    )


def evaluate_config_checks(env: dict) -> list[dict]:
    """Deployment-configuration sanity checks for the admin security panel.

    ``env`` is a plain snapshot dict built by the route from config.py — this
    function never reads the environment itself, and only booleans/hostnames go
    in, so no secret value can ever be echoed back out. Each check returns
    {key, label, status: ok|warn|error|info, detail}.
    """
    checks: list[dict] = []

    def add(key: str, label: str, status: str, detail: str) -> None:
        checks.append({"key": key, "label": label, "status": status, "detail": detail})

    if env.get("jwt_secret_set"):
        add("jwt_secret_set", "JWT signing secret", "ok", "JWT_SECRET_KEY is set.")
    else:
        add("jwt_secret_set", "JWT signing secret", "error",
            "JWT_SECRET_KEY is not set — sessions are unsigned or the app is "
            "running on the insecure dev fallback.")

    if env.get("allow_insecure_dev_jwt"):
        add("insecure_dev_jwt", "Insecure dev JWT mode", "error",
            "ALLOW_INSECURE_DEV_JWT is enabled — never run production this way.")
    else:
        add("insecure_dev_jwt", "Insecure dev JWT mode", "ok", "Disabled.")

    # Static finding from the dashboard build: render.yaml historically declared
    # JWT_SECRET while the code reads JWT_SECRET_KEY, so the blueprint-generated
    # value was ignored. Fixed in render.yaml; keep the check as a tripwire.
    add("render_jwt_env_name", "Render JWT env-var name", "info",
        "render.yaml must declare JWT_SECRET_KEY (not JWT_SECRET) — verify the "
        "dashboard value on the next blueprint sync.")

    app_base_url = env.get("app_base_url") or ""
    if "localhost" in app_base_url or "127.0.0.1" in app_base_url:
        add("app_base_url", "APP_BASE_URL", "warn",
            f"APP_BASE_URL is {app_base_url} — emailed links (password reset, "
            "verification) will point at localhost.")
    elif "onrender.com" in app_base_url:
        add("app_base_url", "APP_BASE_URL", "warn",
            f"APP_BASE_URL is {app_base_url} — that looks like the API's own "
            "origin, but reset/verification links must point at the FRONTEND.")
    else:
        add("app_base_url", "APP_BASE_URL", "ok", f"Set to {app_base_url}.")

    if env.get("resend_api_key_set") and env.get("resend_from_email_set"):
        add("email_configured", "Transactional email (Resend)", "ok", "Configured.")
    else:
        add("email_configured", "Transactional email (Resend)", "warn",
            "RESEND_API_KEY / RESEND_FROM_EMAIL not both set — verification and "
            "password-reset emails fail soft (nothing is sent).")

    if env.get("billing_configured"):
        add("billing_configured", "Stripe subscription billing", "ok",
            "Secret key and price ids configured.")
    else:
        add("billing_configured", "Stripe subscription billing", "warn",
            "Not configured — plans are admin-managed only; self-serve checkout 503s.")

    if env.get("stripe_billing_webhook_secret_set"):
        add("billing_webhook_secret", "Stripe billing webhook secret", "ok", "Set.")
    else:
        add("billing_webhook_secret", "Stripe billing webhook secret", "warn",
            "STRIPE_BILLING_WEBHOOK_SECRET unset — subscription events will not "
            "update account plans.")

    if env.get("admin_notification_email_set"):
        add("admin_alerts", "Admin email alerts", "ok", "ADMIN_NOTIFICATION_EMAIL is set.")
    else:
        add("admin_alerts", "Admin email alerts", "warn",
            "ADMIN_NOTIFICATION_EMAIL unset — signup/prospect alerts and the "
            "unverified-signup digest go nowhere.")

    add("self_serve_signup", "Self-serve signup",
        "info", "Enabled." if env.get("self_serve_signup") else "Disabled (invite-only).")

    add("twilio_configured", "Twilio (SMS/calls)",
        "info", "Configured." if env.get("twilio_configured") else "Not configured.")

    return checks
