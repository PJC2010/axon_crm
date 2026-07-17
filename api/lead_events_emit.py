"""
Server-side auto-emission of lead outcome events (scoring feedback loop, Phase 2).

Instruments the actions contractors already take — no new required inputs. The
build plan's rule is "instrument, don't ask": rather than having the UI POST to
/api/leads/{id}/events for routine actions, the backend emits events as a side
effect of the endpoints those actions already hit (list/detail/status/quote).

Every emitter is **best-effort**: a failure here — including a pre-migration
database with no lead_events table yet — is logged and swallowed so it can never
break the host request. The append-only log's job is to accumulate training
signal, not to gate the CRM.

**Volume control.** `surfaced` and `viewed` are emitted at most once per lead
(the first time it is listed / opened), via an idempotent NOT EXISTS insert — a
list render must not append an event per row per page load. Stage events
(contacted / quote_sent / won / lost) fire on the actual status transition,
which is naturally infrequent; duplicates across triggers are harmless because
the labeling job (Phase 3) keys off the earliest event per lead.

Each emitter runs in its own transaction (commit on success, rollback on
failure), so callers must invoke them **after** committing their own work — the
commit here would otherwise flush the caller's pending writes early.
"""
import logging

import psycopg2.extras

log = logging.getLogger(__name__)

# Lead status -> emitted event_type. Statuses with no training signal ('new',
# 'qualified', 'not_interested') are intentionally absent. 'converted' maps to
# 'won' because the codebase treats won/converted as the same customer state
# (config.CUSTOMER_STATUSES) and the lead_events vocabulary has no 'converted'.
STATUS_EVENT_MAP = {
    "contacted":  "contacted",
    "quote_sent": "quote_sent",
    "won":        "won",
    "converted":  "won",
    "lost":       "lost",
}


def emit_event(conn, property_id: int, account_id: int, event_type: str, *,
               actor_user_id: int | None = None, channel: str | None = None,
               metadata: dict | None = None) -> bool:
    """Best-effort single-event insert in its own transaction. Never raises."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lead_events "
                "(property_id, account_id, event_type, channel, actor_user_id, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (property_id, account_id, event_type, channel, actor_user_id,
                 psycopg2.extras.Json(metadata) if metadata is not None else None),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        log.exception("lead_event emit failed (%s) for lead %s account %s",
                      event_type, property_id, account_id)
        return False


def emit_stage_event(conn, property_id: int, account_id: int,
                     new_status: str | None, old_status: str | None, *,
                     actor_user_id: int | None = None,
                     metadata: dict | None = None) -> str | None:
    """Emit the event mapped to a status transition — but only when the status
    actually changed and the new status carries training signal. Returns the
    emitted event_type, or None when nothing was emitted."""
    if new_status == old_status:
        return None
    event_type = STATUS_EVENT_MAP.get(new_status)
    if not event_type:
        return None
    emit_event(conn, property_id, account_id, event_type,
               actor_user_id=actor_user_id, metadata=metadata)
    return event_type


def emit_surfaced(conn, property_ids, account_id: int, *,
                  actor_user_id: int | None = None) -> int:
    """First-only bulk 'surfaced' insert for the given leads (list render /
    export). Emits a surfaced event only for leads in this account that don't
    already have one, in a single statement. Best-effort; returns rows written."""
    ids = [int(p) for p in property_ids if p is not None]
    if not ids:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lead_events (property_id, account_id, event_type, actor_user_id) "
                "SELECT p.id, %s, 'surfaced', %s FROM properties p "
                "WHERE p.account_id = %s AND p.id = ANY(%s) "
                "  AND NOT EXISTS (SELECT 1 FROM lead_events e "
                "                  WHERE e.property_id = p.id AND e.event_type = 'surfaced')",
                (account_id, actor_user_id, account_id, ids),
            )
            written = cur.rowcount
        conn.commit()
        return written
    except Exception:
        conn.rollback()
        log.exception("surfaced emit failed for account %s (%d leads)", account_id, len(ids))
        return 0


def emit_viewed(conn, property_id: int, account_id: int, *,
                actor_user_id: int | None = None) -> int:
    """First-only 'viewed' insert for a single lead-detail open. Emits only when
    the lead (in this account) has no prior 'viewed' event. Best-effort."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lead_events (property_id, account_id, event_type, actor_user_id) "
                "SELECT %s, %s, 'viewed', %s "
                "WHERE NOT EXISTS (SELECT 1 FROM lead_events e "
                "                  WHERE e.property_id = %s AND e.account_id = %s "
                "                    AND e.event_type = 'viewed')",
                (property_id, account_id, actor_user_id, property_id, account_id),
            )
            written = cur.rowcount
        conn.commit()
        return written
    except Exception:
        conn.rollback()
        log.exception("viewed emit failed for lead %s account %s", property_id, account_id)
        return 0
