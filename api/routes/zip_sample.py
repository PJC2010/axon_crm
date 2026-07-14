"""
GET /api/public/zip-sample — the landing page's "see your ZIP's top leads, free"
teaser (prospective-user audit P1: the highest-leverage growth loop in the repo).

Public and unauthenticated by design: it serves a masked sample of scored
properties from a designated demo org (PUBLIC_SAMPLE_ACCOUNT_ID) — partial
addresses, grades, and the human "why", never contact info or exact addresses
(those are the product, behind signup). Scores are recomputed against the
requested vertical's weight profile so a roofer and a pool company see
different, honest rankings from the same enriched rows.

For a ZIP the sample account hasn't scored yet, one free HCAD-seeded pipeline
run is queued (globally rate-capped, Harris County only) and the widget polls
until the data lands. ZIPs outside the free county data report unsupported
rather than spending paid API calls on strangers.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn

from config import (
    DEFAULT_WEIGHTS, VERTICAL_WEIGHTS,
    PUBLIC_SAMPLE_ACCOUNT_ID, PUBLIC_SAMPLE_AUTORUN, PUBLIC_SAMPLE_RUNS_PER_HOUR,
    PUBLIC_SAMPLE_TOP_N,
)
from api.deps import get_db, dict_fetchall
from api.ratelimit import RateLimiter, client_ip
from api.zip_sample_logic import mask_address, value_label
from pipeline.scoring import explain_score

log = logging.getLogger(__name__)
public_router = APIRouter()

_ZIP_RE = re.compile(r"^\d{5}$")

# Per-IP browsing cap + a global cap on autorun pipeline work (CPU, not API
# dollars — HCAD seeding is free — but strangers shouldn't soak the worker).
zip_sample_limiter = RateLimiter(max_calls=30, per_seconds=3600, name="ZIP sample")
zip_sample_run_limiter = RateLimiter(
    max_calls=PUBLIC_SAMPLE_RUNS_PER_HOUR, per_seconds=3600, name="ZIP sample run")

# Over-fetch by stored score, then re-rank under the requested vertical's
# weights (verticals order the same rows differently).
_CANDIDATE_ROWS = 60


def sample_configured() -> bool:
    return bool(PUBLIC_SAMPLE_ACCOUNT_ID)


def _zip_supported(db: PGConn, zip_code: str) -> bool:
    """Whether the free county mirror has parcels for this ZIP. Fail-open when
    the mirror table isn't loaded — the queued run then settles the question."""
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1 FROM hcad_properties WHERE site_zip = %s LIMIT 1", (zip_code,))
            return cur.fetchone() is not None
    except Exception:
        db.rollback()
        return True


def _queue_sample_run(db: PGConn, account_id: int, zip_code: str, vertical: str | None) -> bool:
    """Create + enqueue one free HCAD-seeded run for the sample account.
    Returns False when the hourly autorun budget is spent."""
    try:
        zip_sample_run_limiter.check("global")
    except HTTPException:
        return False
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (zip, vertical, triggered_by, account_id) "
            "VALUES (%s, %s, 'zip_sample', %s) RETURNING id",
            (zip_code, vertical, account_id),
        )
        run_id = cur.fetchone()[0]
        db.commit()
    from api.scheduler import enqueue_run
    enqueue_run(run_id, zip_code, vertical, account_id, seed_source="hcad")
    log.info("ZIP-sample run %d queued for %s", run_id, zip_code)
    return True


@public_router.get("/public/zip-sample")
def zip_sample(zip: str, vertical: str | None = None, request: Request = None,
               db: PGConn = Depends(get_db)):
    if not sample_configured():
        return {"configured": False, "available": False}
    if not _ZIP_RE.match((zip or "").strip()):
        raise HTTPException(status_code=400, detail="Enter a 5-digit ZIP code.")
    zip_code = zip.strip()
    vertical = (vertical or "").strip() or None
    if vertical and vertical not in VERTICAL_WEIGHTS:
        raise HTTPException(status_code=400, detail=f"Unknown trade: {vertical}")
    if request is not None:
        zip_sample_limiter.check(client_ip(request))

    account_id = int(PUBLIC_SAMPLE_ACCOUNT_ID)
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM properties WHERE account_id = %s AND zip = %s "
            "AND lead_score IS NOT NULL AND archived_at IS NULL "
            "ORDER BY lead_score DESC LIMIT %s",
            (account_id, zip_code, _CANDIDATE_ROWS),
        )
        rows = dict_fetchall(cur)

    if not rows:
        # No *live* leads, but the ZIP may already be seeded with archived ones.
        # Archival is a per-account CRM working state that's meaningless to a
        # public visitor — the teaser exists to prove coverage — so fall back to
        # the seeded rows rather than falsely reporting the ZIP as unsupported.
        with db.cursor() as cur:
            cur.execute(
                "SELECT * FROM properties WHERE account_id = %s AND zip = %s "
                "AND lead_score IS NOT NULL "
                "ORDER BY lead_score DESC LIMIT %s",
                (account_id, zip_code, _CANDIDATE_ROWS),
            )
            rows = dict_fetchall(cur)

    if not rows:
        # Nothing scored yet — report run-in-progress, queue one, or admit the
        # ZIP isn't covered by the free county data.
        with db.cursor() as cur:
            cur.execute(
                "SELECT status FROM pipeline_runs WHERE account_id = %s AND zip = %s "
                "ORDER BY id DESC LIMIT 1",
                (account_id, zip_code),
            )
            last = cur.fetchone()
        if last and last[0] in ("queued", "running"):
            return {"configured": True, "available": False, "queued": True}
        if last and last[0] == "done":
            return {"configured": True, "available": False, "queued": False, "supported": False}
        if not _zip_supported(db, zip_code):
            return {"configured": True, "available": False, "queued": False, "supported": False}
        if PUBLIC_SAMPLE_AUTORUN and _queue_sample_run(db, account_id, zip_code, vertical):
            return {"configured": True, "available": False, "queued": True}
        return {"configured": True, "available": False, "queued": False, "supported": True}

    weights = VERTICAL_WEIGHTS.get(vertical, DEFAULT_WEIGHTS) if vertical else DEFAULT_WEIGHTS
    explained = []
    for row in rows:
        e = explain_score(row, weights)
        explained.append((e["score"], e, row))
    explained.sort(key=lambda t: t[0], reverse=True)

    leads = [
        {
            "address": mask_address(row.get("address")),
            "grade": e["grade"],
            "score": round(e["score"]),
            "year_built": row.get("year_built"),
            "value": value_label(row.get("estimated_value")),
            "why": e["summary"],
        }
        for _, e, row in explained[:PUBLIC_SAMPLE_TOP_N]
    ]

    with db.cursor() as cur:
        # Coverage stats mirror the leads we surface above (which fall back to
        # seeded-but-archived rows), so this count must not filter on archival —
        # otherwise an all-archived ZIP shows leads under a "0 scored" header.
        cur.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE score_grade = 'A'), "
            "COUNT(*) FILTER (WHERE score_grade = 'B') "
            "FROM properties WHERE account_id = %s AND zip = %s "
            "AND lead_score IS NOT NULL",
            (account_id, zip_code),
        )
        total, grade_a, grade_b = cur.fetchone()

    return {
        "configured": True,
        "available": True,
        "zip": zip_code,
        "vertical": vertical,
        "total_scored": total,
        "grade_a": grade_a,
        "grade_b": grade_b,
        "leads": leads,
    }
