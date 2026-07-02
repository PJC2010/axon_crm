"""Account-wide lead scoring for non-property business types.

Property/home-services accounts score per ZIP through the enrichment pipeline
(pipeline/scorer.py score_zip). Insurance and retail accounts have no property
pipeline — their records are scored here by rolling up the child-object tables
(policies / orders) into the fields the insurance_renewal / retail_rfm profiles
expect (see pipeline/profiles.py), then reusing the same pure scoring math
(compute_score / _grade) and writing lead_score / score_grade back.

The roll-ups are time-relative (days to renewal, days since last order), so this
runs daily and can be triggered manually by an owner. The pure row-builders are
DB-free and tested; rescore_account is thin SQL orchestration.
"""
import logging
from datetime import date

from pipeline.profiles import PROFILES, SCORING_PROFILE_BY_BUSINESS_TYPE
from pipeline.scoring import compute_score, _grade

log = logging.getLogger(__name__)


def _days_between(later: date | None, earlier: date | None) -> int | None:
    if later is None or earlier is None:
        return None
    return (later - earlier).days


def insurance_rollup_row(next_expiration: date | None, policy_count: int,
                         premium_in_force: float, *, today: date | None = None) -> dict:
    """Build the insurance_renewal profile's input row from a client's active
    policies: soonest renewal proximity, cross-sell headroom, and book value."""
    today = today or date.today()
    return {
        "days_to_expiration": _days_between(next_expiration, today),
        "policy_count": policy_count or 0,
        "premium_in_force": float(premium_in_force or 0),
    }


def retail_rollup_row(last_order_date: date | None, order_count_365d: int,
                      lifetime_spend: float, *, today: date | None = None) -> dict:
    """Build the retail_rfm profile's input row (recency / frequency / monetary)
    from a customer's completed orders."""
    today = today or date.today()
    return {
        "days_since_last_order": _days_between(today, last_order_date),
        "order_count_365d": order_count_365d or 0,
        "lifetime_spend": float(lifetime_spend or 0),
    }


# Per-profile roll-up query + row-builder. Each query returns
# (property_id, *raw aggregates) for every non-archived record in the account;
# the builder turns the raw aggregates into the profile's input row.
_ROLLUPS = {
    "insurance_renewal": {
        "sql": (
            "SELECT p.id, "
            "MIN(pol.expiration_date) FILTER (WHERE pol.status = 'active' "
            "                                 AND pol.expiration_date >= CURRENT_DATE), "
            "COUNT(pol.id) FILTER (WHERE pol.status = 'active'), "
            "COALESCE(SUM(pol.premium) FILTER (WHERE pol.status = 'active'), 0) "
            "FROM properties p "
            "LEFT JOIN policies pol ON pol.property_id = p.id AND pol.account_id = p.account_id "
            "WHERE p.account_id = %s AND p.archived_at IS NULL "
            "GROUP BY p.id"
        ),
        "builder": lambda raw: insurance_rollup_row(raw[0], raw[1], raw[2]),
    },
    "retail_rfm": {
        "sql": (
            "SELECT p.id, "
            "MAX(o.order_date) FILTER (WHERE o.status = 'completed'), "
            "COUNT(o.id) FILTER (WHERE o.status = 'completed' "
            "                    AND o.order_date >= CURRENT_DATE - 365), "
            "COALESCE(SUM(o.total) FILTER (WHERE o.status = 'completed'), 0) "
            "FROM properties p "
            "LEFT JOIN orders o ON o.property_id = p.id AND o.account_id = p.account_id "
            "WHERE p.account_id = %s AND p.archived_at IS NULL "
            "GROUP BY p.id"
        ),
        "builder": lambda raw: retail_rollup_row(raw[0], raw[1], raw[2]),
    },
}


def profile_key_for_account(conn, account_id: int) -> str | None:
    """The account-wide scoring profile key for an account, or None if its
    business type isn't scored this way (property types, general_sales, …)."""
    with conn.cursor() as cur:
        cur.execute("SELECT business_type FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
    business_type = row[0] if row and row[0] else None
    return SCORING_PROFILE_BY_BUSINESS_TYPE.get(business_type)


def rescore_account(conn, account_id: int, business_type: str | None = None) -> int:
    """Recompute lead_score / score_grade for every record in a non-property
    account. Returns the number of records updated (0 when the account's
    business type has no account-wide profile). Caller owns the transaction.
    """
    profile_key = (
        SCORING_PROFILE_BY_BUSINESS_TYPE.get(business_type)
        if business_type is not None
        else profile_key_for_account(conn, account_id)
    )
    if not profile_key:
        return 0

    profile = PROFILES[profile_key]
    rollup = _ROLLUPS[profile_key]
    with conn.cursor() as cur:
        cur.execute(rollup["sql"], (account_id,))
        rows = cur.fetchall()

    updates = []
    for raw in rows:
        property_id = raw[0]
        row = rollup["builder"](raw[1:])
        score = round(compute_score(row, profile), 2)
        updates.append((score, _grade(score), property_id, account_id))

    if updates:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE properties SET lead_score = %s, score_grade = %s, score_updated_at = NOW() "
                "WHERE id = %s AND account_id = %s",
                updates,
            )
    log.info("Rescored %d record(s) for account %d (%s)", len(updates), account_id, profile_key)
    return len(updates)


def rescore_all_accounts(conn) -> dict:
    """Rescore every account whose business type has an account-wide profile.
    Per-account isolation so one failure doesn't block the rest."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, business_type FROM accounts WHERE business_type = ANY(%s)",
            (list(SCORING_PROFILE_BY_BUSINESS_TYPE),),
        )
        accounts = cur.fetchall()

    summary = {"accounts": 0, "records": 0}
    for account_id, business_type in accounts:
        try:
            n = rescore_account(conn, account_id, business_type)
            conn.commit()
            summary["accounts"] += 1
            summary["records"] += n
        except Exception:
            conn.rollback()
            log.exception("Account rescore failed for account %d", account_id)
    return summary
