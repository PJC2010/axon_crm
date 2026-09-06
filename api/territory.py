"""Per-plan territory limit — only pro runs the pipeline in unlimited ZIPs.

A *territory* is a distinct ZIP code the account works through the prospecting
pipeline. Plan defaults live in api/entitlements.py PLAN_TERRITORY_LIMITS
(starter 1, growth 3, pro unlimited), overridable per account via
account_plans.territory_limit (migration 0085). Unlike the scoring quota there
is no ledger: the territory set is derived live as the union of

  * ZIPs with an active pipeline schedule (a claimed automation slot),
  * ZIPs with a queued/running pipeline run (enqueued but not yet seeded), and
  * ZIPs holding non-archived ENGINE-sourced properties (the data itself).

The last leg is the durable one and gives the single release valve: archiving
every engine lead in a ZIP frees its slot. CSV imports, inbound calls/texts and
web-form leads never count — provenance comes from the same own-book rule as
the scoring quota (api/scoring_quota.py), so the two can't disagree about
which ZIPs are the engine's.

Two guards, both permissive/degrade-open (a counting failure logs and allows;
only the deliberate 403 denies):

  * **Expansion** (schedule create/reactivate, manual and region runs): the
    action's NEW ZIPs must fit the limit. Re-running a held ZIP is always free.
  * **Scheduling** (schedule create/reactivate only): distinct actively
    scheduled ZIPs after the change must fit the limit. This is what keeps the
    downgrade trim (``trim_schedules_to_limit``) from being undone with a
    toggle — without it a downgraded account could just reactivate everything.

FastAPI and entitlements are imported lazily inside the guards (the
require_actionable pattern) so the pure helpers stay importable bare in tests.
"""
import logging

from api.scoring_quota import engine_book_sql

log = logging.getLogger(__name__)

ENGINE_BOOK_SQL = engine_book_sql()

# pipeline_runs.zip carries two non-ZIP sentinels: 'region:<id>' for region
# runs (api/routes/pipeline.py) and 'backfill' for account sweeps
# (api/scheduler.py). Neither is a territory. Doubled percent = LIKE wildcard;
# every query using this fragment passes params, which collapses it.
_RUN_ZIP_SQL = "zip IS NOT NULL AND zip <> 'backfill' AND zip NOT LIKE 'region:%%'"
# Public name for the same predicate — the admin usage router counts an org's
# territories with it, and one definition is what keeps the two counts equal.
RUN_ZIP_SQL = _RUN_ZIP_SQL


# ── pure helpers ──────────────────────────────────────────────────────────────

def new_zips(candidates, used) -> list[str]:
    """The candidate ZIPs not already in the territory set, deduped."""
    return sorted({z for z in candidates if z and z not in used})


def _created_key(created_at):
    # NULLS LAST without comparing None to a datetime: shorter tuple sorts by
    # its first element alone, and equal (1,) keys fall through to the zip
    # tiebreak in the caller.
    return (1,) if created_at is None else (0, created_at)


def zips_to_keep(schedules, limit: int) -> set[str]:
    """The oldest ``limit`` distinct ZIPs among active schedule rows.

    Ordering — first schedule's created_at ascending, NULLs last, ZIP as the
    tiebreak — must match ``trim_schedules_to_limit``'s window ORDER BY, or the
    fire-time backstop would disagree with the downgrade trim about which
    schedules survive.
    """
    firsts: dict[str, object] = {}
    for s in schedules:
        z = s.get("zip")
        if not z:
            continue
        key = _created_key(s.get("created_at"))
        if z not in firsts or key < firsts[z]:
            firsts[z] = key
    ordered = sorted(firsts, key=lambda z: (firsts[z], z))
    return set(ordered[: max(limit, 0)])


# ── territory measurement ─────────────────────────────────────────────────────

def used_territories(db, account_id: int) -> set[str] | None:
    """The account's territory set, or None when it can't be measured —
    callers treat None as "allow" (degrade-open, like the scoring quota)."""
    sql = (
        "SELECT zip FROM pipeline_schedules "
        "WHERE account_id = %s AND is_active AND zip IS NOT NULL "
        "UNION "
        "SELECT zip FROM pipeline_runs "
        f"WHERE account_id = %s AND status IN ('queued', 'running') AND {_RUN_ZIP_SQL} "
        "UNION "
        "SELECT zip FROM properties "
        "WHERE account_id = %s AND zip IS NOT NULL AND archived_at IS NULL "
        f"AND {ENGINE_BOOK_SQL}"
    )
    try:
        with db.cursor() as cur:
            cur.execute(sql, (account_id, account_id, account_id))
            return {r[0] for r in cur.fetchall()}
    except Exception:
        db.rollback()
        log.exception("territory measurement failed for account %s", account_id)
        return None


def active_scheduled_zips(db, account_id: int,
                          exclude_schedule_id: int | None = None) -> set[str]:
    sql = "SELECT DISTINCT zip FROM pipeline_schedules WHERE account_id = %s AND is_active"
    params: list = [account_id]
    if exclude_schedule_id is not None:
        sql += " AND id <> %s"
        params.append(exclude_schedule_id)
    with db.cursor() as cur:
        cur.execute(sql, params)
        return {r[0] for r in cur.fetchall() if r[0]}


def territory_quota(db, account_id: int, limit: int) -> dict | None:
    """Meter payload for GET /api/account/features; None when unmeasurable."""
    used = used_territories(db, account_id)
    if used is None:
        return None
    zips = sorted(used)
    return {"limit": limit, "used": len(zips), "zips": zips,
            "remaining": max(0, limit - len(zips))}


# ── guards ────────────────────────────────────────────────────────────────────

def _refuse(limit: int, used, message: str):
    from fastapi import HTTPException

    raise HTTPException(
        status_code=403,
        detail={
            "detail": message,
            "territory": True,
            "upgrade": True,
            "limit": limit,
            "used": sorted(used),
        },
    )


def require_run_allowed(db, account_id: int, zips) -> None:
    """Expansion guard for one-off runs (per-ZIP and region fan-outs)."""
    from api.entitlements import get_territory_limit

    zips = [z for z in zips if z]
    if not zips:
        return
    limit = get_territory_limit(account_id, db)
    if limit is None:
        return
    used = used_territories(db, account_id)
    if used is None:
        return
    fresh = new_zips(zips, used)
    if fresh and len(used) + len(fresh) > limit:
        label = f"'{fresh[0]}'" if len(fresh) == 1 else f"{len(fresh)} new ZIPs"
        _refuse(limit, used,
                f"Your plan includes {limit} territor{'y' if limit == 1 else 'ies'} "
                f"(ZIP codes) and {label} would exceed it. Upgrade to add more, "
                "or archive an existing territory's leads to free its slot.")


def require_schedule_allowed(db, account_id: int, zip_code: str,
                             exclude_schedule_id: int | None = None) -> None:
    """Expansion + scheduling guards for schedule create/reactivate."""
    from api.entitlements import get_territory_limit

    limit = get_territory_limit(account_id, db)
    if limit is None:
        return
    used = used_territories(db, account_id)
    if used is not None and zip_code not in used and len(used) + 1 > limit:
        _refuse(limit, used,
                f"Your plan includes {limit} territor{'y' if limit == 1 else 'ies'} "
                f"(ZIP codes) and '{zip_code}' would be a new one. Upgrade to add "
                "more, or archive an existing territory's leads to free its slot.")
    try:
        scheduled = active_scheduled_zips(db, account_id, exclude_schedule_id)
    except Exception:
        db.rollback()
        log.exception("scheduled-zip count failed for account %s", account_id)
        return
    if zip_code not in scheduled and len(scheduled) + 1 > limit:
        _refuse(limit, scheduled,
                f"Your plan schedules refreshes for up to {limit} "
                f"territor{'y' if limit == 1 else 'ies'} (ZIP codes). Deactivate "
                "another ZIP's schedule or upgrade to automate more.")


def schedule_may_fire(conn, account_id: int, zip_code: str) -> tuple[bool, str | None]:
    """Fire-time backstop for scheduled jobs (api/scheduler.py::_scheduled_job).

    A trimmed-on-downgrade schedule is already inactive, but APScheduler state
    is per-process: the other instance of a multi-instance deploy still holds
    the job, and a plan write that bypassed the trim would leave over-limit
    schedules firing forever. The rule mirrors the trim: only the oldest
    ``limit`` distinct scheduled ZIPs may fire. Degrades open.
    """
    try:
        from api.entitlements import get_territory_limit

        limit = get_territory_limit(account_id, conn)
        if limit is None:
            return True, None
        with conn.cursor() as cur:
            cur.execute(
                "SELECT zip, created_at FROM pipeline_schedules "
                "WHERE account_id = %s AND is_active",
                (account_id,),
            )
            rows = [{"zip": r[0], "created_at": r[1]} for r in cur.fetchall()]
        if zip_code in zips_to_keep(rows, limit):
            return True, None
        return False, "territory_limit"
    except Exception:
        conn.rollback()
        log.exception("territory fire-time check failed for account %s", account_id)
        return True, None


# ── downgrade trim ────────────────────────────────────────────────────────────

def trim_schedules_to_limit(db, account_id: int) -> list[int]:
    """Deactivate active schedules beyond the account's territory limit,
    keeping the oldest ``limit`` distinct ZIPs (the ORDER BY must stay in
    lockstep with ``zips_to_keep``). Called after every plan write
    (api/billing.py::apply_plan, the admin set-plan endpoint,
    scripts/set_account_plan.py) and rides the caller's transaction — the
    caller commits. Returns the deactivated schedule ids. Rows are deactivated,
    never deleted: an upgrade lets the owner toggle them back on.
    """
    from api.entitlements import get_territory_limit

    limit = get_territory_limit(account_id, db)
    if limit is None:
        return []
    with db.cursor() as cur:
        cur.execute(
            "WITH zip_rank AS ("
            " SELECT zip, ROW_NUMBER() OVER (ORDER BY MIN(created_at) ASC NULLS LAST, zip) AS rnk"
            " FROM pipeline_schedules WHERE account_id = %s AND is_active"
            " GROUP BY zip"
            ") "
            "UPDATE pipeline_schedules s SET is_active = FALSE "
            "FROM zip_rank z "
            "WHERE s.account_id = %s AND s.is_active AND s.zip = z.zip AND z.rnk > %s "
            "RETURNING s.id",
            (account_id, account_id, limit),
        )
        ids = [r[0] for r in cur.fetchall()]
    for sid in ids:
        # Best-effort in-process deregistration; the fire-time backstop covers
        # anything missed (including the other instance's APScheduler).
        try:
            from api.scheduler import remove_schedule_job
            remove_schedule_job(sid)
        except Exception:
            log.exception("could not deregister trimmed schedule job %s", sid)
    if ids:
        log.info("Territory trim deactivated %d schedule(s) for account %s", len(ids), account_id)
    return ids
