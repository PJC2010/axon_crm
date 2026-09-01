"""Automatic "focus view": surface only the account's top-graded leads.

A pipeline run seeds every parcel in the ZIP as a live lead (status 'new'), so
one run can bury a user's list under tens of thousands of rows. The focus view
narrows the DEFAULT lead list to the best grade bands, with a one-click "Show
all" — nothing is archived or permanently hidden, and the user never enters a
number: the cutoff is chosen here, automatically, after every scoring pass.

The cutoff is one number per account (accounts.focus_score_cutoff, migration
0086), always a GRADE_BANDS threshold so the banner can honestly say "A- and
B-grade". ``recompute_focus`` walks the bands best-first and stops at the first
one whose cumulative candidate count reaches an adaptive floor —
max(FOCUS_FLOOR_MIN, 10% of the scored book), capped at FOCUS_FLOOR_MAX — so a
thin ZIP with no A's widens to B or C instead of showing three leads, and a
200k-row account still gets a genuine shortlist. If even the last real band
can't reach the floor (or only "everything" can), the cutoff is NULL and focus
turns itself off: a focus view that shows everything is noise.

Counts — and the query-time predicate (``focus_condition``) — cover only
quota-candidate-shaped rows (scored, still 'new', engine-sourced, per
api/scoring_quota.py's own-book rule): a lead the user has worked, or one from
their own book (CSV import, inbound call/text, web form), must never vanish
from the default list.

The writer runs from pipeline/scorer.py (non-fatal, like score snapshots);
readers live in api/routes/leads.py. Only the threshold is stored — the
banner's counts are computed live per request, so a stale cutoff can mis-size
the shortlist but never mis-report it.
"""
import logging

from config import GRADE_BANDS

log = logging.getLogger(__name__)

FOCUS_FLOOR_MIN = 50     # roughly a workable week of outreach
FOCUS_FLOOR_PCT = 0.10   # keeps the floor proportional for mid-size books
FOCUS_FLOOR_MAX = 500    # a shortlist, even for a 200k-row account


def _engine_book_sql(prefix: str = "") -> str:
    # Lazy import: pipeline modules only reach into api/ inside functions
    # (the pipeline/signals.py precedent), keeping the package importable
    # standalone. scoring_quota itself is FastAPI-free.
    from api.scoring_quota import engine_book_sql
    return engine_book_sql(prefix)


# ── pure logic ────────────────────────────────────────────────────────────────

def focus_floor(scored_total: int) -> int:
    """How many leads a focus view must show to be worth having."""
    import math
    return min(max(FOCUS_FLOOR_MIN, math.ceil(scored_total * FOCUS_FLOOR_PCT)),
               FOCUS_FLOOR_MAX)


def compute_focus_cutoff(band_counts: dict[float, int], scored_total: int) -> float | None:
    """Pick the score cutoff: the best GRADE_BANDS threshold whose cumulative
    candidate count reaches the floor. ``band_counts`` maps each non-zero band
    threshold to the count of candidates scoring at or above it. None = focus
    off (book thinner than the floor, or only "show everything" reaches it).
    """
    floor = focus_floor(scored_total)
    if scored_total < floor:
        return None
    for threshold, _grade in GRADE_BANDS:
        if threshold <= 0:
            # The bottom band is "everything" — a cutoff there filters nothing.
            return None
        if band_counts.get(threshold, 0) >= floor:
            return float(threshold)
    return None


def focus_condition(prefix: str = "") -> str:
    """WHERE fragment (one ``%s``: the cutoff) appended to the lead list when
    focus is on. Hides only candidate-shaped rows — worked leads and the
    tenant's own book always show. Contains doubled percents, so it must ride
    a parameterized execute().
    """
    p = prefix
    return (f"({p}lead_score IS NULL OR {p}lead_score >= %s "
            f"OR COALESCE({p}status, 'new') <> 'new' "
            f"OR NOT {_engine_book_sql(p)})")


def grade_for_cutoff(cutoff: float | None) -> str | None:
    """The grade label a cutoff corresponds to, for the banner ("B" = "B-grade
    and up")."""
    if cutoff is None:
        return None
    for threshold, grade in GRADE_BANDS:
        if cutoff >= threshold:
            return grade
    return None


# ── database ──────────────────────────────────────────────────────────────────

def recompute_focus(conn, account_id: int) -> float | None:
    """Re-derive and store the account's focus cutoff. One FILTER aggregate
    over the candidate book (bounded memory: a single row back), then a PK
    UPDATE. Commits. Called after every scoring pass — non-fatal at the call
    site, so a focus failure never fails a run.
    """
    thresholds = [float(t) for t, _g in GRADE_BANDS if t > 0]
    filters = ", ".join(
        f"COUNT(*) FILTER (WHERE lead_score >= {t})" for t in thresholds
    )
    sql = (
        f"SELECT {filters}, COUNT(*) FROM properties "
        "WHERE account_id = %s AND archived_at IS NULL AND lead_score IS NOT NULL "
        f"AND COALESCE(status, 'new') = 'new' AND {_engine_book_sql()}"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (account_id,))
        row = cur.fetchone()
    # A real aggregate always returns one row; connection fakes may not.
    counts = dict(zip(thresholds, row[:-1])) if row else {}
    scored_total = row[-1] if row else 0
    cutoff = compute_focus_cutoff(counts, scored_total)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET focus_score_cutoff = %s, focus_updated_at = NOW() "
            "WHERE id = %s",
            (cutoff, account_id),
        )
    conn.commit()
    log.info("Focus cutoff for account %s: %s (%d scored candidates)",
             account_id, cutoff, scored_total)
    return cutoff


def get_focus_cutoff(db, account_id: int) -> float | None:
    """PK read of the stored cutoff; None (focus off) on any failure."""
    try:
        with db.cursor() as cur:
            cur.execute("SELECT focus_score_cutoff FROM accounts WHERE id = %s",
                        (account_id,))
            row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        db.rollback()
        log.exception("focus cutoff read failed for account %s", account_id)
        return None
