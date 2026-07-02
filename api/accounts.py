"""Account (organization) provisioning.

A new org needs its own set of pipeline stages, since stage keys are unique per
account (see migration 017). Both the CLI bootstrap (scripts/create_user.py) and
any future self-signup path should create accounts through here so the defaults
stay in one place.
"""

# Mirrors the seed in db/migrations/011_custom_stages.sql, but per-account.
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


def seed_business_type_workflows(conn, account_id: int, business_type: str, user_id: int) -> int:
    """Seed the preset's default workflow rules, skipping names already present.

    Separate from create_account because rules need a creator: scheduled rules
    (date_offset/inactivity) execute as ``created_by``, and at account-creation
    time no user exists yet. Callers run this right after the first user insert
    (scripts/create_user.py) or as the acting owner (business-type switch).
    """
    import json as _json
    from api.business_types import get_business_type

    bt = get_business_type(business_type)
    created = 0
    with conn.cursor() as cur:
        for rule in bt.default_workflows:
            cur.execute(
                "SELECT 1 FROM workflow_rules WHERE account_id = %s AND name = %s",
                (account_id, rule["name"]),
            )
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO workflow_rules (name, trigger_type, trigger_config, action_type, "
                "action_config, created_by, account_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (rule["name"], rule.get("trigger_type", "status_change"),
                 _json.dumps(rule.get("trigger_config", {})),
                 rule.get("action_type", "create_task"),
                 _json.dumps(rule.get("action_config", {})),
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
