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


def create_account(conn, name: str) -> int:
    """Create an organization and seed its default pipeline stages.

    Returns the new account id. Caller owns the transaction (commits).
    """
    with conn.cursor() as cur:
        cur.execute("INSERT INTO accounts (name) VALUES (%s) RETURNING id", (name,))
        account_id = cur.fetchone()[0]
        cur.executemany(
            "INSERT INTO pipeline_stages "
            "(account_id, key, label, color, sort_order, is_terminal, is_default) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(account_id, *stage) for stage in DEFAULT_STAGES],
        )
    return account_id
