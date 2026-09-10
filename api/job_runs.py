"""Scheduler job-run ledger (migration 0088) — every tick leaves a row.

Ten of the twelve scheduler ticks used to be log-only: the trial-expiry
downgrade, the workflow rules, the nightly rescores, the digests, the sweeps and
the stale-run reconcile each ``log.info``'d a summary and returned. A tick that
silently stopped firing — a lock held every night by a wedged sibling instance,
a crash, a feature flag left off — was invisible until a customer noticed. Now
every tick is wrapped in ``tracked(job_id)``: a ``scheduler_job_runs`` row is
opened when it starts and closed with ok / error / skipped when it ends, and
GET /admin/jobs (api/routes/admin_ops.py) reads the newest row per job next to
APScheduler's own registry.

Three rules keep the ledger honest without changing what a tick does:

* **Its own connection, autocommit, opened and closed per write.** A tick opens
  its own connection *after* the lock check, sometimes never (a disabled
  sweep). The ledger cannot ride that connection and still record those runs,
  and it must never hold a connection open across a forty-minute snapshot.
* **It never raises into the tick.** A failed INSERT or UPDATE is a
  ``log.warning``; the tick runs regardless. Observability must not become a
  new way for the job to fail.
* **It never masks the tick's own error handling.** Every tick swallows its
  exceptions with ``except Exception: log.exception(...)``, so a plain wrapper
  would record ``ok`` for a failed tick. The tick therefore reports through two
  one-line hooks: ``failed(exc)`` inside that except block, and ``skip(reason)``
  where it used to ``return`` early. ``skip`` raises ``Skipped``, a
  ``BaseException`` on purpose: the tick's ``except Exception`` cannot catch it
  on the way back to the decorator, while its ``finally`` blocks (close the
  connection, release the lock) still run exactly as they did for the return.

The pipeline run family (``_run_pipeline``, ``_run_backfill``, ``_scheduled_job``)
is deliberately not wrapped: ``pipeline_runs`` is its ledger.
"""
import functools
import inspect
import json
import logging
import socket
import threading

import psycopg2
from psycopg2.extras import Json

from config import DATABASE_URL

log = logging.getLogger(__name__)

# Every job id a tracked() tick registers under. GET /admin/jobs uses it to tell
# a tick from a pipeline schedule or a one-shot run job.
TRACKED_JOB_IDS: set[str] = set()

# APScheduler runs ticks in a thread pool; the run a tick is inside is
# thread-local so nested or concurrent ticks never see each other's row.
_state = threading.local()
_dumps = functools.partial(json.dumps, default=str)   # dates/Decimals in summaries


class Skipped(BaseException):
    """Raised by skip(): the tick decided not to run (lock held, feature off).
    A BaseException on purpose — see the module docstring."""

    def __init__(self, reason: str, result=None):
        super().__init__(reason)
        self.reason = reason
        self.result = result


class _Run:
    __slots__ = ("job_id", "row_id", "status", "error", "detail")

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.row_id = None
        self.status = "ok"
        self.error = None
        self.detail: dict = {}


def _current():
    return getattr(_state, "ctx", None)


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:2000]


def _connect():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def _open(job_id: str):
    """INSERT the running row; None when it could not be written."""
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO scheduler_job_runs (job_id, host) VALUES (%s, %s) RETURNING id",
                    (job_id, socket.gethostname()),
                )
                row = cur.fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except Exception:
        log.warning("job ledger: could not open a run for %s", job_id, exc_info=True)
        return None


def _close(run: _Run, status: str, error) -> None:
    # Identity, not truthiness: a test fake hands back id 0, which is a real id.
    if run.row_id is None:
        return
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE scheduler_job_runs SET finished_at = NOW(), status = %s, "
                    "error = %s, detail = %s WHERE id = %s",
                    (status, error, Json(run.detail, dumps=_dumps), run.row_id),
                )
        finally:
            conn.close()
    except Exception:
        log.warning("job ledger: could not close run %s for %s", run.row_id, run.job_id,
                    exc_info=True)


def skip(reason: str, result=None):
    """Leave the tick early with status 'skipped'. Replaces the early `return`;
    ``result`` is what the tick returns to its caller (reconcile returns 0)."""
    raise Skipped(reason, result)


def failed(exc: BaseException) -> None:
    """Call inside a tick's own ``except Exception as exc:`` block — the block
    swallows the exception, so this is how the ledger learns about it."""
    run = _current()
    if run is not None:
        run.status = "error"
        run.error = _error_text(exc)


def note(*mappings, **detail) -> None:
    """Merge figures into the row's detail JSONB (a summary dict, counters).
    A no-op outside a tracked tick; never raises."""
    run = _current()
    if run is None:
        return
    for m in mappings:
        if isinstance(m, dict):
            run.detail.update(m)
        elif m is not None:
            run.detail["result"] = m
    run.detail.update(detail)


def tracked(job_id: str, *, manual_id: str | None = None):
    """Decorate a scheduler tick so every execution lands in the ledger.

    ``manual_id``: when the tick is also fired on demand with a ``triggered_by``
    argument other than "schedule" (api/data_health.py::enqueue_snapshot), that
    run is ledgered under ``manual_id``. The Jobs table is keyed by the
    APScheduler job that fired, and "did the nightly job run?" must not be
    answered by an afternoon refresh, nor the nightly job's 7-day counts mix
    manual runs in.
    """
    def deco(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            jid = job_id
            if manual_id:
                try:
                    bound = sig.bind_partial(*args, **kwargs)
                    bound.apply_defaults()
                    if bound.arguments.get("triggered_by", "schedule") != "schedule":
                        jid = manual_id
                except TypeError:
                    pass
            run = _Run(jid)
            run.row_id = _open(jid)
            previous = _current()
            _state.ctx = run
            try:
                result = fn(*args, **kwargs)
            except Skipped as skipped:
                run.detail.setdefault("reason", skipped.reason)
                _close(run, "skipped", skipped.reason)
                return skipped.result
            except BaseException as exc:
                # Escaped the tick's own handling (or a KeyboardInterrupt):
                # record it, then let it go where it was going.
                _close(run, "error", _error_text(exc))
                raise
            else:
                _close(run, run.status, run.error)
                return result
            finally:
                _state.ctx = previous

        wrapper.__job_id__ = job_id
        wrapper.__job_ids__ = (job_id,) + ((manual_id,) if manual_id else ())
        TRACKED_JOB_IDS.update(wrapper.__job_ids__)
        return wrapper
    return deco
