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
            [(account_id, *stage) for stage in DEFAULT_STAGES],
        )
        cur.execute(
            "INSERT INTO account_plans (account_id, plan_name, modules) VALUES (%s, %s, %s) "
            "ON CONFLICT (account_id) DO NOTHING",
            (account_id, plan_name, Json(modules)),
        )
    return account_id
