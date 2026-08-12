"""
Outcome labeling — derive the supervised target from a lead's pipeline state.
Pure: no DB. The DB layer (snapshot.py) feeds rows here and persists the result.

Label definition
-----------------
  1  (won)    — the lead reached a terminal win: status 'won'/'converted', or an
                accepted quote / paid invoice tied to it (passed in via `outcome_hint`).
  0  (loss)   — status 'lost'/'not_interested', OR an "aged-out" open lead: created
                more than `stale_open_days` ago and never advanced past 'contacted'.
  None        — still genuinely in flight (censored). Excluded from training; still
                scored at inference time.
"""
from __future__ import annotations

from datetime import date, datetime

WON_STATUSES = {"won", "converted"}
LOST_STATUSES = {"lost", "not_interested"}
EARLY_STATUSES = {"new", "contacted"}


def _to_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def outcome_sort_key(value) -> datetime:
    """Sortable timestamp for an `outcome_at`; undated/unparseable sorts last.

    Single source of truth for outcome ordering: the time-based train/test split
    and the "keep the most recently decided rows" training-set cap must agree, or
    the cap would discard rows the split expects to be there.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value[:19])
        except ValueError:
            return datetime.max
    return datetime.max


def derive_label(
    row: dict,
    *,
    stale_open_days: int = 120,
    now: date | None = None,
    outcome_hint: str | None = None,
) -> int | None:
    """Return 1 (won), 0 (lost/aged-out) or None (censored) for a lead row.

    `outcome_hint` lets the DB layer pass a stronger revenue signal it computed via
    joins ('paid_invoice' or 'accepted_quote' => win) that the bare property row
    can't express.
    """
    now = now or date.today()
    status = (row.get("status") or "new").strip().lower()

    if outcome_hint in ("paid_invoice", "accepted_quote") or status in WON_STATUSES:
        return 1
    if status in LOST_STATUSES:
        return 0

    # Open lead: treat a stale, never-advanced lead as a soft loss.
    if status in EARLY_STATUSES:
        created = _to_date(row.get("created_at"))
        if created is not None and (now - created).days >= stale_open_days:
            return 0
        return None

    # qualified / quote_sent and still open — genuinely censored.
    return None


def derive_outcome_at(row: dict, label: int | None) -> datetime | str | None:
    """Best-available timestamp for when the outcome was decided (for time splits)."""
    if label is None:
        return None
    return row.get("stage_moved_at") or row.get("updated_at") or row.get("created_at")


def derive_job_value(row: dict) -> float | None:
    """Realized revenue for a won lead, when available (for value regression later)."""
    for key in ("job_value", "invoice_total", "quote_total", "estimated_job_value"):
        v = row.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None
