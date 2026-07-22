"""Account (organization) provisioning.

A new org needs its own set of pipeline stages, since stage keys are unique per
account (see migration 017). Both the CLI bootstrap (scripts/create_user.py) and
any future self-signup path should create accounts through here so the defaults
stay in one place.
"""

# Mirrors the seed in db/migrations/0011_custom_stages.sql, but per-account.
DEFAULT_STAGES = [
    ("new",            "New",            "var(--color-ink-300)", 0, False, True),
    ("contacted",      "Contacted",      "var(--color-ocean)",   1, False, False),
    ("qualified",      "Qualified",      "var(--color-accent)",  2, False, False),
    ("quote_sent",     "Quote Sent",     "var(--color-gold)",    3, False, False),
    ("won",            "Won",            "var(--color-moss)",    4, True,  False),
    ("lost",           "Lost",           "var(--color-danger)",  5, True,  False),
    ("not_interested", "Not Interested", "var(--color-ink-200)", 6, True,  False),
]


def create_account(conn, name: str, plan_name: str = "pro",
                   business_type: str = "home_services") -> int:
    """Create an organization and seed its default pipeline stages, plan, and type.

    The seeded module set is the business type's defaults bounded by the plan's
    allowance — a module is enabled only if both the plan grants it and the type
    wants it on (so a non-property type ships with prospecting/map off even on a
    `pro` plan). Admins can change either later via scripts/set_account_plan.py.
    Returns the new account id. Caller owns the transaction (commits).
    """
    from psycopg2.extras import Json
    from api.entitlements import MODULE_KEYS, PLAN_CATALOG
    from api.business_types import get_business_type

    granted = PLAN_CATALOG.get(plan_name, set(MODULE_KEYS))
    bt = get_business_type(business_type)
    modules = {key: (key in granted) and bt.default_modules.get(key, True) for key in MODULE_KEYS}

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO accounts (name, business_type) VALUES (%s, %s) RETURNING id",
            (name, bt.key),
        )
        account_id = cur.fetchone()[0]
        cur.executemany(
            "INSERT INTO pipeline_stages "
            "(account_id, key, label, color, sort_order, is_terminal, is_default) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(account_id, *stage) for stage in (bt.default_stages or DEFAULT_STAGES)],
        )
        cur.execute(
            "INSERT INTO account_plans (account_id, plan_name, modules) VALUES (%s, %s, %s) "
            "ON CONFLICT (account_id) DO NOTHING",
            (account_id, plan_name, Json(modules)),
        )
    seed_business_type_fields(conn, account_id, business_type)
    return account_id


def provision_owner(conn, *, company: str, email: str, username_base: str,
                    hashed_pw: str, business_type: str = "home_services",
                    email_verified: bool = False) -> dict:
    """Self-serve provisioning: fresh org + its owner user in one transaction.

    Shared by POST /auth/signup and the OAuth first-login path so both funnels
    produce identical accounts (same defaults as scripts/create_user.py: stages,
    fields, plan, then the preset's workflows once the owner exists). New
    self-serve accounts start on the full `pro` module set with a local trial
    row in account_billing (see api/billing.py for what happens at expiry).

    ``username_base`` collides with existing users occasionally (emails share
    local parts), so numbered variants are tried before giving up. Caller owns
    the transaction (commits) — everything rolls back together on failure.
    Returns {"user_id", "account_id", "username"}.
    """
    from api.signup_logic import username_candidates
    from config import TRIAL_DAYS

    account_id = create_account(conn, company, plan_name="pro",
                                business_type=business_type)
    user_id = username = None
    with conn.cursor() as cur:
        for candidate in username_candidates(username_base):
            cur.execute("SELECT 1 FROM users WHERE username = %s", (candidate,))
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO users (username, email, hashed_pw, role, account_id, email_verified) "
                "VALUES (%s, %s, %s, 'owner', %s, %s) RETURNING id",
                (candidate, email, hashed_pw, account_id, email_verified),
            )
            user_id, username = cur.fetchone()[0], candidate
            break
        if user_id is None:
            raise RuntimeError(f"Could not find a free username for {username_base!r}")
        cur.execute(
            "INSERT INTO account_billing (account_id, plan_name, status, trial_ends_at) "
            "VALUES (%s, 'pro', 'trialing', NOW() + make_interval(days => %s)) "
            "ON CONFLICT (account_id) DO NOTHING",
            (account_id, TRIAL_DAYS),
        )
    seed_business_type_workflows(conn, account_id, business_type, user_id)
    return {"user_id": user_id, "account_id": account_id, "username": username}


def seed_business_type_fields(conn, account_id: int, business_type: str) -> int:
    """Seed the preset's custom-field definitions (idempotent per key)."""
    from psycopg2.extras import Json
    from api.business_types import get_business_type

    bt = get_business_type(business_type)
    created = 0
    with conn.cursor() as cur:
        for i, f in enumerate(bt.default_fields):
            cur.execute(
                "INSERT INTO record_field_defs (account_id, key, label, field_type, options, sort_order) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (account_id, key) DO NOTHING RETURNING id",
                (account_id, f["key"], f["label"], f.get("field_type", "text"),
                 Json(f.get("options", [])), i),
            )
            if cur.fetchone():
                created += 1
    return created


def seed_business_type_templates(conn, account_id: int, business_type: str, user_id: int) -> dict[str, int]:
    """Seed the preset's default message templates (idempotent per name).

    Returns name → id for every preset template — created now or already
    present — so workflow seeding can resolve template_names references.
    """
    from api.business_types import get_business_type

    bt = get_business_type(business_type)
    ids: dict[str, int] = {}
    with conn.cursor() as cur:
        for t in bt.default_templates:
            cur.execute(
                "INSERT INTO message_templates (account_id, name, channel, subject, body, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (account_id, name) DO NOTHING RETURNING id",
                (account_id, t["name"], t.get("channel", "email"), t.get("subject"),
                 t["body"], user_id),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT id FROM message_templates WHERE account_id = %s AND name = %s",
                    (account_id, t["name"]),
                )
                row = cur.fetchone()
            if row:
                ids[t["name"]] = row[0]
    return ids


def seed_business_type_workflows(conn, account_id: int, business_type: str, user_id: int) -> int:
    """Seed the preset's default workflow rules, skipping names already present.

    Separate from create_account because rules need a creator: scheduled rules
    (date_offset/inactivity) execute as ``created_by``, and at account-creation
    time no user exists yet. Callers run this right after the first user insert
    (scripts/create_user.py) or as the acting owner (business-type switch).

    The preset's default templates are seeded first; a rule whose action_config
    carries {"template_names": {channel: name}} gets them resolved to this
    account's template ids ({"templates": {channel: id}}). A send rule none of
    whose templates resolved is skipped rather than seeded broken.
    """
    import json as _json
    from api.business_types import get_business_type

    bt = get_business_type(business_type)
    template_ids = seed_business_type_templates(conn, account_id, business_type, user_id)
    created = 0
    with conn.cursor() as cur:
        for rule in bt.default_workflows:
            cur.execute(
                "SELECT 1 FROM workflow_rules WHERE account_id = %s AND name = %s",
                (account_id, rule["name"]),
            )
            if cur.fetchone():
                continue
            action_config = dict(rule.get("action_config", {}))
            names = action_config.pop("template_names", None)
            if names:
                resolved = {ch: template_ids[n] for ch, n in names.items() if n in template_ids}
                if not resolved:
                    continue
                action_config["templates"] = resolved
            cur.execute(
                "INSERT INTO workflow_rules (name, trigger_type, trigger_config, action_type, "
                "action_config, created_by, account_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (rule["name"], rule.get("trigger_type", "status_change"),
                 _json.dumps(rule.get("trigger_config", {})),
                 rule.get("action_type", "create_task"),
                 _json.dumps(action_config),
                 user_id, account_id),
            )
            created += 1
    return created


def seed_business_type_stages(conn, account_id: int, business_type: str) -> int:
    """Insert any of the preset's stages missing for the account (never deletes).

    Used by the opt-in business-type switch: existing stages (and the leads on
    them) are left alone; only the pack's missing stage keys are added.
    """
    from api.business_types import get_business_type

    bt = get_business_type(business_type)
    stages = bt.default_stages or DEFAULT_STAGES
    created = 0
    with conn.cursor() as cur:
        for stage in stages:
            key = stage[0]
            cur.execute(
                "SELECT 1 FROM pipeline_stages WHERE account_id = %s AND key = %s",
                (account_id, key),
            )
            if cur.fetchone():
                continue
            # Never seed a second default stage into an existing account.
            cur.execute(
                "INSERT INTO pipeline_stages "
                "(account_id, key, label, color, sort_order, is_terminal, is_default) "
                "VALUES (%s, %s, %s, %s, %s, %s, FALSE)",
                (account_id, *stage[:5]),
            )
            created += 1
    return created
