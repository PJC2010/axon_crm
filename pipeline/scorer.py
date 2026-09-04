"""
Step 6 — Lead scoring.

Reads enriched property records and writes lead_score (0–100) + score_grade (A/B/C/D).
Pure scoring math lives in pipeline.scoring (DB-free, testable).
"""
import logging
from datetime import datetime, timezone

from config import SCORER_MODE, VERTICAL_WEIGHTS
from pipeline import regional
from pipeline.db import get_conn, fetch_by_zip, upsert_properties
from pipeline.equity import (
    EQUITY_SOURCE_FLAG, FALLBACK_SOURCE, estimate_equity, stored_equity_source,
)
from pipeline.job_value import estimate_job_value
from pipeline.score_snapshots import write_score_snapshots
from pipeline.scoring import (
    score_property, compute_score, _compute_score, _grade, data_completeness,
    _age_signal, _sale_signal, _equity_signal,
    _garage_signal, _income_signal, _permit_signal,
)

log = logging.getLogger(__name__)


def score_zip(zip_code: str, account_id: int, vertical: str | None = None) -> int:
    """Score every live row in one ZIP and write lead_score / score_grade.

    `vertical` chooses the weight profile. Passing one re-labels the whole ZIP:
    every row scores on that vertical and its `vertical` column is set to it.
    Passing None means "no opinion", not "default": each row keeps scoring on
    the vertical it was last scored with (`rows_by_vertical`), and only rows
    that never had one score on the default profile. The two account-wide
    rescores (POST /pipeline/rescore-all and the post-backfill rescore in
    api/scheduler.py) pass None, and before this rule they silently moved a
    roofing book onto the default profile — +14 to +28 points on the same row,
    with `vertical` still reading "roofing" because the upsert never writes a
    None — so an account's grade distribution flipped depending on which path
    ran last and the explain endpoint disagreed with the card.
    """
    # Resolved through the profile registry (pipeline/profiles.py); property
    # profiles wrap the same config weights, so output is unchanged.
    from pipeline.profiles import resolve_profile
    conn = get_conn()
    rows = fetch_by_zip(conn, zip_code, account_id)
    if not rows:
        conn.close()
        return 0

    # A run is per-ZIP, so the whole batch shares one market and the region is
    # resolved once rather than per row. The rows' own state is a cross-check
    # on the ZIP (pipeline/regional.py); a ZIP outside a calibrated market
    # resolves to the national profile, which is the object every non-regional
    # caller already gets.
    state = next((r.get("state") for r in rows if r.get("state")), None)
    region = regional.resolve_region(zip_code, state)
    scored_at = datetime.now(timezone.utc).isoformat()

    updates = []
    scored_rows = []   # (row-as-scored, score, grade) for the feedback-loop snapshot
    labels = []
    for group_vertical, group_rows in rows_by_vertical(rows, vertical).items():
        # A property row scores on a property profile only. The registry also
        # holds the roll-up profiles (insurance_renewal, retail_rfm, …), and a
        # stored `vertical` is a free-text column, so anything that is not a
        # configured vertical resolves to the default profile — the stored
        # label is still preserved on the row.
        profile = resolve_profile(
            group_vertical if group_vertical in VERTICAL_WEIGHTS else None, region)
        weights = profile.weights
        job_value_mult = regional.job_value_multiplier(region, profile.key)
        labels.append(f"{profile.key}/{profile.region_label}")

        for row in group_rows:
            update = {
                "address":          row["address"],
                "zip":              zip_code,
                "vertical":         group_vertical,
                "score_updated_at": scored_at,
            }

            # Backfill estimated_equity (never overwrite an enriched/manual value)
            # so the field is populated even on free-only data; do it before
            # scoring so the equity signal reflects it. The basis is flagged on
            # the row for this run and persisted below, so scoring can
            # down-weight flat-fallback equity — which proxies home value, a
            # thing other signals already cover — on every later pass too.
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
                    if source == FALLBACK_SOURCE:
                        row["estimated_equity_is_fallback"] = True

            # Backfill an auto job-value estimate only when the user hasn't set one.
            if row.get("estimated_job_value") is None:
                job_value = estimate_job_value(row, group_vertical, multiplier=job_value_mult)
                if job_value is not None:
                    update["estimated_job_value"] = job_value

            # compute_score (not _compute_score) so the profile's OWN signal
            # functions run: a regional profile's thresholds live in those
            # closures, and the raw-weights path would silently score them
            # nationally.
            score = compute_score(row, profile)
            update["lead_score"]  = round(score, 2)
            update["score_grade"] = _grade(score)
            # How much of the weight profile real data backed — separates "weak
            # lead" from "thin file" in the UI and in the score snapshots.
            # `region` records which calibration produced the number, so a
            # score can be reproduced later even after the matrix moves.
            flags = {
                # The profile that produced the number — the vertical's own key,
                # or "default" for rows with no vertical (and for a stored one
                # the registry does not know, which resolve_profile falls back on).
                "scored": profile.key,
                "region": region,
                "data_completeness": data_completeness(row, weights, profile.factor_meta),
            }
            # Persist the equity basis the score was computed against. Rows
            # written before the stamp existed resolve it by re-derivation
            # (pipeline/equity.py::stored_equity_source), so one rescore
            # converges them without a migration.
            equity_source = stored_equity_source(row)
            if equity_source and (row.get("enrichment_flags") or {}).get(
                    EQUITY_SOURCE_FLAG) != equity_source:
                flags[EQUITY_SOURCE_FLAG] = equity_source
            update["enrichment_flags"] = flags
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
    # With vertical=None the snapshot writer falls back to each row's own.
    _apply_ml(conn, account_id, vertical, rows)

    # Focus view: grades just moved, so re-pick the account's surfacing cutoff
    # (pipeline/focus.py). Non-fatal by the same rule as the snapshot write —
    # including the rollback itself, so a connection stub without one (the
    # golden scoring suite) can't turn a best-effort step into a crash.
    try:
        from pipeline.focus import recompute_focus
        recompute_focus(conn, account_id)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        log.exception("Focus recompute failed (non-fatal) for account %s", account_id)

    conn.close()
    log.info("Scored %d properties in ZIP %s [%s] (grade dist: %s)",
             n, zip_code, ", ".join(labels), _grade_dist(updates))
    return n


def rows_by_vertical(rows: list[dict], vertical: str | None) -> dict:
    """Group rows by the vertical they score on. Pure, so the rule is testable.

    An explicit `vertical` puts every row under it. None keeps each row on its
    stored `vertical` (a NULL or '' groups under None → the default profile).
    Groups keep first-seen order and rows keep fetch order within a group; the
    ZIP's updates therefore come out grouped by vertical, not in fetch order.
    """
    if vertical is not None:
        return {vertical: list(rows)}
    groups: dict = {}
    for row in rows:
        groups.setdefault(row.get("vertical") or None, []).append(row)
    return groups

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
