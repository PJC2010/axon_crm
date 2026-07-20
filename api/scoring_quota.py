"""Monthly scored-lead reveal quota (positioning plan Phase 3).

Every plan sees Axon's graded leads — lower tiers meter how many unmask each
month (api/entitlements.py PLAN_SCORING_LIMITS, overridable per account via
account_plans.scoring_monthly_limit) instead of losing the prospecting module.

A *quota candidate* is a scored lead the user hasn't worked yet (status still
'new'): the prospecting engine's raw output. Records the user created, imported,
or has already touched are never masked — the quota gates the engine, not the
user's own book. A candidate is *revealed* the first time it renders unmasked in
a calendar month (ledger: scoring_reveals, migration 0061) and stays open for
the rest of that month; once the allowance is spent, further candidates render
masked — the same address-masking trust contract as the public ZIP-sample teaser
(api/zip_sample_logic.py) — with an upgrade prompt in the UI.

Enforcement is best-effort in the same spirit as api/lead_events_emit.py: a
ledger failure (e.g. a pre-migration database) degrades to no masking rather
than breaking the lead list. The pure helpers (``is_quota_candidate`` /
``mask_lead_row``) are dependency-free — see tests/test_scoring_quota.py.
"""
import logging
from datetime import date

from api.zip_sample_logic import mask_address

log = logging.getLogger(__name__)

# Identity/contact fields withheld on a masked lead — what people pay for. The
# score, grade, and street context stay visible so the value is provable,
# exactly like the public teaser.
MASKED_FIELDS = (
    "account_number", "owner_name", "contact_name",
    "contact_phone", "contact_email", "contact_phone_alt", "contact_email_alt",
    "mailing_address", "latitude", "longitude",
)


def is_quota_candidate(row: dict) -> bool:
    """Only scored, not-yet-worked leads count against (or are hidden by) the
    quota. Anything unscored or already in play stays fully visible."""
    return row.get("lead_score") is not None and (row.get("status") or "new") == "new"


def mask_lead_row(row: dict) -> dict:
    """A copy of the lead with identity/contact withheld and the address
    partially hidden ('1842 Westheimer Rd' → '18XX Westheimer Rd')."""
    masked = dict(row)
    masked["address"] = mask_address(row.get("address"))
    for field in MASKED_FIELDS:
        if field in masked:
            masked[field] = None
    masked["quota_masked"] = True
    return masked


def month_start(today: date | None = None) -> date:
    d = today or date.today()
    return date(d.year, d.month, 1)


def used_this_month(db, account_id: int) -> int:
    """Reveals consumed so far this calendar month (0 on ledger failure)."""
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM scoring_reveals WHERE account_id = %s AND month = %s",
                (account_id, month_start()),
            )
            return cur.fetchone()[0]
    except Exception:
        db.rollback()
        log.exception("scoring_reveals usage read failed for account %s", account_id)
        return 0


def apply_quota(db, account_id: int, rows: list[dict], limit: int):
    """Walk ``rows`` in display order, enforcing the monthly reveal allowance.

    Already-revealed candidates stay open; unrevealed candidates consume the
    remaining allowance (recorded in the ledger); the rest are masked. Returns
    ``(rows, state)`` where state is ``{"limit", "used", "remaining"}`` — or
    ``(rows, None)`` unchanged when the ledger is unavailable, so quota problems
    can never take down the lead list.
    """
    month = month_start()
    candidate_ids = [r["id"] for r in rows if is_quota_candidate(r)]
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM scoring_reveals WHERE account_id = %s AND month = %s",
                (account_id, month),
            )
            used = cur.fetchone()[0]
            revealed: set[int] = set()
            if candidate_ids:
                cur.execute(
                    "SELECT property_id FROM scoring_reveals "
                    "WHERE account_id = %s AND month = %s AND property_id = ANY(%s)",
                    (account_id, month, candidate_ids),
                )
                revealed = {r[0] for r in cur.fetchall()}
    except Exception:
        db.rollback()
        log.exception("scoring quota check failed for account %s", account_id)
        return rows, None

    remaining = max(0, limit - used)
    out: list[dict] = []
    to_reveal: list[int] = []
    for row in rows:
        if not is_quota_candidate(row) or row["id"] in revealed:
            out.append(row)
        elif remaining > 0:
            remaining -= 1
            to_reveal.append(row["id"])
            out.append(row)
        else:
            out.append(mask_lead_row(row))

    if to_reveal:
        used += _record_reveals(db, account_id, to_reveal, month)

    return out, {"limit": limit, "used": used, "remaining": max(0, limit - used)}


def _record_reveals(db, account_id: int, property_ids: list[int], month: date) -> int:
    """Best-effort ledger insert in its own transaction (mirrors
    api/lead_events_emit.py). Returns rows written."""
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO scoring_reveals (account_id, property_id, month) "
                "SELECT %s, p.id, %s FROM properties p "
                "WHERE p.account_id = %s AND p.id = ANY(%s) "
                "ON CONFLICT DO NOTHING",
                (account_id, month, account_id, property_ids),
            )
            written = cur.rowcount
        db.commit()
        return written
    except Exception:
        db.rollback()
        log.exception("scoring reveal write failed for account %s (%d leads)",
                      account_id, len(property_ids))
        return 0
