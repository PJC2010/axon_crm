"""Pure platform-admin logic — validation, classification, config checks.

Split out from the routes (api/routes/admin.py) so it unit-tests without a DB
or network, following the same pattern as api/signup_logic.py and
api/import_logic.py (see tests/test_admin_logic.py).
"""

ADMIN_ROLES = ("owner", "sales_rep")

MAX_PAGE_SIZE = 100


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
