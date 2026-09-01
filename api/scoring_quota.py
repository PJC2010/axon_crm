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

Every surface that renders or acts on a candidate goes through this module, in
one of three modes:

  * **Reveal surfaces** (lead list, lead detail, by-number lookup, CSV export,
    dialer queue, Kanban board) call ``apply_quota`` with the default
    ``consume=True``: rendering spends the allowance, best leads first.
  * **Passive surfaces** (customer search, pipeline alerts, the neighbors
    panel) call it with ``consume=False``: already-revealed leads show, but a
    widget the user didn't deliberately point at a lead never spends reveals —
    unrevealed candidates just render masked (or are dropped, for search,
    where a masked hit would confirm address guesses).
  * **Mutations** (status change, contact edit, enrich, send-message,
    appointment binding, CSV import address-merges) call
    ``require_actionable``/``check_reveal``: acting on a lead is a reveal,
    because ``is_quota_candidate`` requires status 'new' — any write would end
    candidacy and unmask the row for free. Within the allowance the reveal is
    consumed; past it the mutation is refused with the same upgrade-shaped 403
    as ``require_module``.

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


# Acquisition sources that mark a row as the tenant's OWN book rather than the
# prospecting engine's output. A CSV the tenant uploaded, a call/text they
# received, a web-form a visitor submitted — the tenant already has that
# person's details, so metering them would wall the tenant off from their own
# contacts (the module docstring's "the quota gates the engine, not the user's
# own book"). Pipeline-seeded rows are NULL or an engine source ('prospecting',
# 'rentcast', 'hcad'), so they remain candidates. Websites use a
# 'website_<form>_form' family, matched by prefix.
#
# Provenance is only trustworthy if the tenant can't stamp it themselves on an
# engine row: the CSV importer never overwrites lead_source on an existing lead
# (api/routes/imports.py), so a guessed-address upload can't launder a seeded
# candidate into the tenant's book.
_OWN_BOOK_SOURCES = frozenset({"csv_import", "inbound_call", "inbound_sms", "manual"})


def _is_own_book(lead_source) -> bool:
    if not lead_source:
        return False
    return lead_source in _OWN_BOOK_SOURCES or lead_source.startswith("website_")


def engine_book_sql(prefix: str = "") -> str:
    """SQL twin of ``not _is_own_book(lead_source)``: TRUE when the row is the
    prospecting ENGINE's output rather than the tenant's own book. Generated
    from ``_OWN_BOOK_SOURCES`` so the SQL and the Python rule can't drift;
    consumed by the territory limit (api/territory.py) and the focus view
    (pipeline/focus.py). The fragment contains doubled percents (LIKE
    wildcards), so it must ride a *parameterized* execute() — psycopg2 only
    collapses ``%%`` to ``%`` when params are passed.
    """
    col = f"{prefix}lead_source"
    sources = ", ".join(f"'{s}'" for s in sorted(_OWN_BOOK_SOURCES))
    return (f"({col} IS NULL OR ({col} NOT IN ({sources}) "
            f"AND {col} NOT LIKE 'website\\_%%'))")


def is_quota_candidate(row: dict) -> bool:
    """Only scored, not-yet-worked leads from the prospecting ENGINE count
    against (or are hidden by) the quota. Anything unscored, already in play, or
    from the tenant's own book (imports, inbound calls/texts, web forms) stays
    fully visible.

    ``lead_source`` may be absent from a row a caller projected without it; a
    missing source is treated as engine-origin (a candidate), so a guard site
    that must respect own-book provenance has to select ``lead_source``."""
    return (
        row.get("lead_score") is not None
        and (row.get("status") or "new") == "new"
        and not _is_own_book(row.get("lead_source"))
    )


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


def apply_quota(db, account_id: int, rows: list[dict], limit: int,
                consume: bool = True):
    """Walk ``rows`` in display order, enforcing the monthly reveal allowance.

    Already-revealed candidates stay open; unrevealed candidates consume the
    remaining allowance (recorded in the ledger); the rest are masked. Returns
    ``(rows, state)`` where state is ``{"limit", "used", "remaining"}`` — or
    ``(rows, None)`` unchanged when the ledger is unavailable, so quota problems
    can never take down the lead list.

    With ``consume=False`` the call is read-only: unrevealed candidates render
    masked even while allowance remains and the ledger is never written, so a
    passively loaded widget can't spend the month's reveals on arbitrary rows.
    Candidacy needs each row to carry ``id``, ``lead_score`` and ``status``.
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

    remaining = max(0, limit - used) if consume else 0
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


def mask_named_fields(db, account_id: int, rows: list[dict], limit: int | None,
                      id_key: str, fields: tuple[str, ...]) -> None:
    """In-place: blank ``fields`` on rows that are unrevealed quota candidates.

    For secondary surfaces (job-costing, discrepancy and non-residential
    reports) whose row is not a lead payload — the property id lives under
    ``id_key`` (e.g. ``property_id``) and only a few identity columns are
    present. Read-only (never consumes reveals); a NULL limit or ledger failure
    leaves every row untouched. ``address`` is partially masked, everything else
    nulled, matching ``mask_lead_row``. Candidacy needs each row to carry
    ``lead_score``, ``status`` and (for own-book provenance) ``lead_source``.
    """
    if limit is None or not rows:
        return
    shadow = [{"id": r.get(id_key), "lead_score": r.get("lead_score"),
               "status": r.get("status"), "lead_source": r.get("lead_source"),
               "address": r.get("address")} for r in rows]
    masked, _ = apply_quota(db, account_id, shadow, limit, consume=False)
    for row, m in zip(rows, masked):
        if not m.get("quota_masked"):
            continue
        for field in fields:
            if field == "address":
                row[field] = m["address"]
            elif field in row:
                row[field] = None


def check_reveal(db, account_id: int, row: dict, limit: int | None) -> bool:
    """May the caller act on this lead unmasked?

    Consumes a reveal when the month's allowance covers an unrevealed
    candidate; returns False when the row must stay masked. Degrades open on
    ledger failure, like ``apply_quota``. ``row`` must carry ``id``,
    ``lead_score`` and ``status``.
    """
    if limit is None or not is_quota_candidate(row):
        return True
    (out,), _ = apply_quota(db, account_id, [row], limit)
    return not out.get("quota_masked")


def require_actionable(db, account_id: int, row: dict) -> None:
    """Guard for id-addressed lead mutations (status change, contact edit,
    enrich, send-message, appointment binding).

    Acting on a lead is a reveal: ``is_quota_candidate`` requires status 'new',
    so any mutation would end candidacy and unmask the row for free — one drag
    on the Kanban board would otherwise bypass the whole meter. Raises the same
    upgrade-shaped 403 as ``require_module`` when the allowance can't cover it.
    """
    # Local imports keep the pure helpers importable without FastAPI/psycopg2
    # on the path (tests/test_scoring_quota.py runs without either).
    from fastapi import HTTPException

    from api.entitlements import get_scoring_limit

    # Non-candidates (worked leads, the user's own contacts) are the common
    # case — skip the plan lookup entirely for them.
    if not is_quota_candidate(row):
        return
    limit = get_scoring_limit(account_id, db)
    if check_reveal(db, account_id, row, limit):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "detail": "This scored lead is past your monthly reveal allowance. "
                      "Upgrade your plan to work more scored leads.",
            "quota": True,
            "upgrade": True,
        },
    )


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
