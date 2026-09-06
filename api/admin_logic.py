"""Pure platform-admin logic — validation, classification, config checks.

Split out from the routes (api/routes/admin.py) so it unit-tests without a DB
or network, following the same pattern as api/signup_logic.py and
api/import_logic.py (see tests/test_admin_logic.py).
"""
import re
from datetime import datetime

from api.signup_logic import company_problem

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


# ── Audit action registry ─────────────────────────────────────────────────────
# Every action string record_admin_action() is ever called with, across all the
# admin route modules. Served by GET /admin/audit-log/actions so the audit
# page's filter cannot drift from the code — it used to be a hand-copied list
# in the frontend that lacked both delete actions. tests/test_admin_logic.py
# greps the route modules to prove nothing is recorded under a name missing here.
AUDIT_ACTIONS = (
    "account.create",
    "account.delete",
    "account.limits_set",
    "account.plan_set",
    "account.trial_expire",
    "account.trial_extend",
    "account.update",
    "data_health.refresh",
    "schedule.deactivate",
    "user.create",
    "user.delete",
    "user.reset_link",
    "user.sessions_revoked",
    "user.set_password",
    "user.update",
)


# ── Org edit (PATCH /admin/accounts/{id}) ─────────────────────────────────────

ACCOUNT_UPDATE_FIELDS = ("name", "business_type", "review_link")
MAX_REVIEW_LINK_LEN = 500
_HTTP_URL_RE = re.compile(r"^https?://\S+$")


def normalize_account_update(changes: dict) -> dict:
    """Trim what the admin typed. Only the three editable columns survive, an
    empty review link means "clear it", and anything else is dropped here
    rather than ever reaching a SET clause."""
    cleaned: dict = {}
    for key in ACCOUNT_UPDATE_FIELDS:
        if key not in changes:
            continue
        value = changes[key]
        if isinstance(value, str):
            value = value.strip()
        if key == "review_link" and value == "":
            value = None
        cleaned[key] = value
    return cleaned


def validate_account_update(changes: dict, business_types) -> list[str]:
    """Problems with an admin edit of an org (empty list = valid). ``changes``
    is the normalized dict — only the fields actually sent.

    The name rule is signup_logic.company_problem, shared with self-serve
    signup and both admin org-creation paths, so an org cannot be renamed into
    something it could not have been created as.
    """
    problems: list[str] = []
    if not changes:
        problems.append("No fields to update.")
        return problems
    if "name" in changes:
        name_problem = company_problem(changes["name"])
        if name_problem:
            problems.append(name_problem)
    if "business_type" in changes and changes["business_type"] not in business_types:
        problems.append(f"Unknown business type '{changes['business_type']}'.")
    if "review_link" in changes and changes["review_link"] is not None:
        link = changes["review_link"]
        if not isinstance(link, str) or not _HTTP_URL_RE.match(link):
            problems.append("Review link must be a full http(s) URL.")
        elif len(link) > MAX_REVIEW_LINK_LEN:
            problems.append(
                f"Review link must be {MAX_REVIEW_LINK_LEN} characters or fewer.")
    return problems


# ── Quota overrides (POST /admin/accounts/{id}/limits) ────────────────────────

LIMIT_FIELDS = ("scoring_monthly_limit", "territory_limit")


def validate_account_limits(changes: dict) -> list[str]:
    """Problems with a limits override (empty list = valid). A field that was
    not sent is left alone; ``None`` means "back to the plan default"."""
    problems: list[str] = []
    if not changes:
        problems.append("No limits to update.")
        return problems
    for key, value in changes.items():
        if key not in LIMIT_FIELDS:
            problems.append(f"Unknown limit '{key}'.")
        elif value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            problems.append(
                f"{key} must be a whole number of 0 or more, or null for the plan default.")
    return problems


# ── Usage tab (api/routes/admin_usage.py) ─────────────────────────────────────

def effective_scoring_limit(plan_name, override, plan_limits: dict):
    """Same resolution as entitlements.get_scoring_limit, over values already
    fetched: an explicit override wins, else the plan default, else unlimited
    (None) — an account with no plan row is unlimited, like module gating."""
    if override is not None:
        return override
    return plan_limits.get(plan_name)


def merge_usage(accounts: list[dict], metric_rows: dict, metric_columns: dict,
                plan_limits: dict) -> list[dict]:
    """One row per account with every usage column filled.

    ``metric_rows`` maps a metric name to its GROUP BY account_id rows, or to
    None when that metric's query was cut off — then its columns are None on
    every row (rendered "—"), never 0, which would read as "no usage".
    ``metric_columns`` maps each metric to the value columns it produces.
    """
    indexed: dict = {}
    for metric, rows in metric_rows.items():
        indexed[metric] = None if rows is None else {r["account_id"]: r for r in rows}
    out = []
    for a in accounts:
        row = {
            "account_id": a["id"], "name": a["name"], "plan_name": a.get("plan_name"),
            "scoring_limit": effective_scoring_limit(
                a.get("plan_name"), a.get("scoring_monthly_limit"), plan_limits),
        }
        for metric, cols in metric_columns.items():
            src = indexed.get(metric)
            for col in cols:
                if src is None:
                    row[col] = None
                else:
                    row[col] = (src.get(a["id"]) or {}).get(col) or 0
        out.append(row)
    return out


def sort_usage(rows: list[dict], sort: str | None, allowed) -> list[dict]:
    """Order usage rows: ``name`` ascending, any metric column descending with
    unmeasured (None) values last. An unknown key raises ValueError — the sort
    never reaches SQL, but the whitelist keeps the API contract explicit."""
    key = sort or "name"
    if key == "name":
        return sorted(rows, key=lambda r: ((r.get("name") or "").lower(), r["account_id"]))
    if key not in allowed:
        raise ValueError(f"Unknown sort '{key}'.")
    return sorted(rows, key=lambda r: (r.get(key) is None, -(r.get(key) or 0), r["account_id"]))


def paginate_rows(rows: list, page: int, page_size: int) -> list:
    start = (page - 1) * page_size
    return rows[start:start + page_size]


# ── Platform data health (api/data_health.py, api/routes/admin_data.py) ───────

RULE_STATES = ("current", "stale", "unstamped")


def pct(numerator, denominator):
    """Percentage to one decimal; None when either side is unknown (a degraded
    block) or there is nothing to divide by."""
    if numerator is None or denominator is None or not denominator:
        return None
    return round(100.0 * numerator / denominator, 1)


def match_rate(with_apn, matched):
    """APN→centroid match rate over parcels that HAVE an APN — the same
    denominator as pipeline/county_build.py::assert_match_rate, for the same
    reason: an all-zero placeholder acct can never match, and counting those
    would let a real join regression hide behind a fixed floor of unmatchables."""
    if with_apn is None or matched is None or not with_apn:
        return None
    return matched / with_apn


def rule_state(stamped_hash, current_hash) -> str:
    """How a stored residential verdict relates to the rule as deployed."""
    if stamped_hash is None:
        return "unstamped"
    return "current" if stamped_hash == current_hash else "stale"


def overlay_zip_rule_state(zips: list[dict], stamps: list[dict], current_hash) -> list[dict]:
    """Attach each ZIP's parcel_rule_stamps state to the snapshot's per-ZIP rows.
    Staleness is decided at read time, not snapshot time: a deploy that changes
    the rule must show every ZIP stale immediately, not after the next tick."""
    by_zip = {s["zip"]: s for s in stamps}
    out = []
    for z in zips:
        s = by_zip.get(z.get("zip"))
        out.append({
            **z,
            "rule_state": rule_state(s["rule_hash"] if s else None, current_hash),
            "classified_at": s.get("classified_at") if s else None,
        })
    return out


def overlay_account_state(rows: list[dict], names: dict, stamps: list[dict],
                          live_unclassified, current_hash) -> list[dict]:
    """Join the snapshot's per-account block with what is live now: the org's
    name (an org deleted since the snapshot drops out; one created since shows
    with unknown counts), its property_rule_stamps state, and the index-only
    unclassified count. ``live_unclassified`` is None when that read was cut
    off, and every row then carries None for it."""
    by_acct = {s["account_id"]: s for s in stamps}

    def _state(aid):
        s = by_acct.get(aid)
        return (rule_state(s["rule_hash"] if s else None, current_hash),
                s.get("classified_at") if s else None)

    def _live(aid):
        if live_unclassified is None:
            return None
        return live_unclassified.get(aid, 0)

    out, seen = [], set()
    for r in rows:
        aid = r.get("account_id")
        if aid not in names:
            continue
        seen.add(aid)
        state, at = _state(aid)
        out.append({**r, "name": names[aid], "rule_state": state,
                    "classified_at": at, "unclassified_live": _live(aid)})
    for aid, name in names.items():
        if aid in seen:
            continue
        state, at = _state(aid)
        out.append({"account_id": aid, "name": name, "properties": None,
                    "with_coords": None, "unclassified": None, "excludable": None,
                    "rule_state": state, "classified_at": at,
                    "unclassified_live": _live(aid)})
    out.sort(key=lambda r: (-(r.get("properties") or 0), (r.get("name") or "").lower()))
    return out


def rule_summary(zips: list[dict], accounts: list[dict]) -> dict:
    def count(rows, state):
        return sum(1 for r in rows if r.get("rule_state") == state)
    return {
        "accounts_stale": count(accounts, "stale"),
        "accounts_unstamped": count(accounts, "unstamped"),
        "zips_stale": count(zips, "stale"),
        "zips_unstamped": count(zips, "unstamped"),
    }


def data_health_alerts(snapshot: dict | None, live: dict | None, rule: dict | None,
                       *, now: datetime, min_match_rate: float = 0.9,
                       max_age_hours: float = 48) -> list[dict]:
    """The Data tab's "needs attention" list — same {key, severity, label,
    detail} shape as evaluate_config_checks, severity in error|warn|info.
    Reads a snapshot row {started_at, status, report} plus the live blocks."""
    alerts: list[dict] = []

    def add(key, severity, label, detail):
        alerts.append({"key": key, "severity": severity, "label": label, "detail": detail})

    if snapshot is None:
        add("no_snapshot", "warn", "No data-health snapshot yet",
            "Nothing has been computed. Refresh now, or wait for the nightly job — "
            "every cache figure reads as \u2014 until one lands.")
    else:
        report = snapshot.get("report") or {}
        started = snapshot.get("started_at")
        if started is not None:
            age_h = (now - started).total_seconds() / 3600
            if age_h > max_age_hours:
                add("snapshot_stale", "warn", "Snapshot is out of date",
                    f"Last computed {age_h / 24:.1f} days ago — the nightly job may be "
                    "failing. Refresh to recompute now.")
        failed = report.get("blocks_failed") or []
        if failed:
            add("blocks_failed", "error", "Some health blocks failed to compute",
                "Not measured: " + ", ".join(failed) + ". Their figures show as \u2014; "
                "the server log has the query error.")
        apn = report.get("apn_match") or {}
        rate = match_rate(apn.get("with_apn"), apn.get("matched"))
        if rate is not None and rate < min_match_rate:
            add("apn_match_rate", "error", "APN\u2192centroid match rate is low",
                f"{rate:.1%} of parcels with an APN match a county centroid (floor "
                f"{min_match_rate:.0%}). Inspect the parcel_apn format for padding or "
                "format drift before trusting free coordinates.")
        parcels = report.get("parcels") or {}
        if (parcels.get("unclassified") or 0) > 0:
            add("parcels_unclassified", "warn", "Cached parcels awaiting classification",
                f"{parcels['unclassified']:,} parcels have no residential verdict yet; "
                "seeds cannot filter them until their ZIP is next touched.")
        city = report.get("city_sanity") or {}
        leak = (city.get("parcels_mail_city_leak") or 0) + (city.get("properties_mail_city_leak") or 0)
        if leak > 0:
            add("mail_city_leak", "error", "Mailing city leaked into the situs city",
                f"{leak:,} HCAD-seeded rows carry the owner's mailing city as the "
                "property city — a writer regressed to mail_city (migration 0079). "
                "Find it before it reaches lead cards.")
        for key, label in (
            ("accounts_stale", "Orgs classified under an old rule"),
            ("accounts_unstamped", "Orgs never classified"),
            ("zips_stale", "ZIPs classified under an old rule"),
            ("zips_unstamped", "ZIPs never classified"),
        ):
            n = (rule or {}).get(key) or 0
            if n:
                add(key, "warn", label,
                    f"{n:,} — the nightly sweep re-derives orgs; a ZIP re-derives on "
                    "its next seed touch.")

    gq = (live or {}).get("geocode_queue") or {}
    failed_geo = gq.get("failed") or 0
    if failed_geo:
        add("geocode_failed", "warn", "Geocode queue has failures",
            f"{failed_geo:,} addresses failed geocoding; the top errors are listed "
            "below.")
    if (live or {}).get("hcad_source") == "none":
        add("hcad_source", "error", "No HCAD source available",
            "Neither a DuckDB file nor the hcad_properties mirror has data — HCAD "
            "seeding returns nothing. Load the mirror with tools/load_hcad_to_postgres.py.")
    return alerts
