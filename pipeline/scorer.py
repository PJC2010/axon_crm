"""
Step 6 — Lead scoring.

Reads enriched property records and writes lead_score (0–100) + score_grade (A/B/C/D).
Pure scoring math lives in pipeline.scoring (DB-free, testable).
"""
import logging
from datetime import datetime, timezone

from config import SCORER_MODE
from pipeline.db import get_conn, fetch_by_zip, upsert_properties
from pipeline.equity import estimate_equity
from pipeline.job_value import estimate_job_value
from pipeline.score_snapshots import write_score_snapshots
from pipeline.scoring import (
    score_property, _compute_score, _grade, data_completeness,
    _age_signal, _sale_signal, _equity_signal,
    _garage_signal, _income_signal, _permit_signal,
)

log = logging.getLogger(__name__)


def score_zip(zip_code: str, account_id: int, vertical: str | None = None) -> int:
    # Resolved through the profile registry (pipeline/profiles.py); property
    # profiles wrap the same config weights, so output is unchanged.
    from pipeline.profiles import resolve_profile
    profile = resolve_profile(vertical)
    weights = profile.weights
    conn = get_conn()
    rows = fetch_by_zip(conn, zip_code, account_id)
    if not rows:
        conn.close()
        return 0

    updates = []
    scored_rows = []   # (row-as-scored, score, grade) for the feedback-loop snapshot
    for row in rows:
        update = {
            "address":          row["address"],
            "zip":              zip_code,
            "vertical":         vertical,
            "score_updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Backfill estimated_equity (never overwrite an enriched/manual value) so
        # the field is populated even on free-only data; do it before scoring so
        # the equity signal reflects it. When the flat fallback supplied the
        # number, flag the row so scoring can down-weight that equity signal —
        # fallback equity proxies home value, which other signals already cover.
        if row.get("estimated_equity") is None:
            equity, source = estimate_equity(
                row.get("estimated_value"),
                last_sale_price=row.get("last_sale_price"),
                last_sale_date=row.get("last_sale_date"),
                return_source=True,
            )
            if equity is not None:
                row["estimated_equity"] = equity
                update["estimated_equity"] = equity
                if source == "fallback":
                    row["estimated_equity_is_fallback"] = True

        # Backfill an auto job-value estimate only when the user hasn't set one.
        if row.get("estimated_job_value") is None:
            job_value = estimate_job_value(row, vertical)
            if job_value is not None:
                update["estimated_job_value"] = job_value

        score = _compute_score(row, weights, profile.gates)
        update["lead_score"]  = round(score, 2)
        update["score_grade"] = _grade(score)
        # How much of the weight profile real data backed — separates "weak
        # lead" from "thin file" in the UI and in the score snapshots.
        update["enrichment_flags"] = {
            "scored": vertical or "default",
            "data_completeness": data_completeness(row, weights),
        }
        updates.append(update)
        scored_rows.append((row, score, update["score_grade"]))

    n = upsert_properties(conn, updates, account_id)

    # Feedback loop: snapshot the exact features + score each lead was graded on,
    # keyed to the active model version, so later outcomes can be joined back to
    # what the model actually saw. Non-fatal by the same rule as _apply_ml.
    try:
        write_score_snapshots(conn, account_id, scored_rows)
    except Exception:
        conn.rollback()
        log.exception("Score snapshot write failed (non-fatal) for account %s", account_id)

    # Predictive layer (best-effort — never let it break the core pipeline):
    # capture point-in-time feature snapshots, and in shadow/learned mode also
    # store the learned conversion probability alongside the deterministic score.
    _apply_ml(conn, account_id, vertical, rows)

    conn.close()
    log.info("Scored %d properties in ZIP %s (grade dist: %s)", n, zip_code,
             _grade_dist(updates))
    return n


def _apply_ml(conn, account_id: int, vertical: str | None, rows: list[dict]) -> None:
    """Snapshot features for training, and (unless SCORER_MODE='rules') write the
    learned probability. Isolated in try/except so any ML failure is non-fatal."""
    try:
        from pipeline.ml import snapshot
        snapshot.write_snapshots(conn, rows, account_id, vertical)
    except Exception:
        log.exception("Feature snapshot capture failed (non-fatal) for account %s", account_id)

    if SCORER_MODE not in ("shadow", "learned"):
        return
    try:
        from pipeline.ml import predict
        scored = predict.score_and_store(conn, account_id, rows)
        if scored:
            log.info("Learned scoring (%s) updated %d lead(s)", SCORER_MODE, scored)
    except Exception:
        log.exception("Learned scoring failed (non-fatal) for account %s", account_id)


def _grade_dist(updates: list[dict]) -> str:
    dist: dict[str, int] = {}
    for u in updates:
        g = u.get("score_grade", "?")
        dist[g] = dist.get(g, 0) + 1
    return str(dist)
