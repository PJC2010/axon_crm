"""
The power dialer (the `calls` module's outbound half — the public TwiML
webhooks live in api/routes/twilio_voice.py).

Endpoints:
  POST /dialer/token        — Twilio Voice access token for browser calling
  GET  /dialer/queue        — who to call next: A-grade first, best score first
  POST /dialer/dispositions — the rep's verdict after a call (both modes)

"Call the A's first" is the queue's ORDER BY, not a filter: every workable
lead with a dialable phone is listed, graded A→D and best-score-first within
the grade; the optional `grade` param narrows to one band. Leads flagged
do_not_call (or litigator-flagged by skip-trace) never appear, and a lead just
dialed sits out a cooldown window so refreshing the page naturally resumes a
session where it left off — there is no server-side session state.

Browser calling degrades gracefully: with the TWILIO_API_KEY_* / TWIML_APP
env vars unset, /dialer/token 503s, GET /calls/settings reports
voice_dialing=false, and the frontend falls back to tel: links + manual
disposition logging (call_sid absent → a synthetic manual-… calls row).

The whole router is gated on the `calls` module in api/main.py. The scored-
lead reveal quota applies exactly as on the lead list — masked rows are
dropped, never rendered phone-less — so metered plans can't harvest contact
info through the dialer.
"""
import logging
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from api import call_logic, dialer_logic, scoring_quota
from api.deps import get_db, get_current_user, dict_fetchall
from api.entitlements import get_scoring_limit
from api.lead_events_emit import emit_event, emit_surfaced
from api.routes.twilio_voice import dialer_configured

log = logging.getLogger(__name__)

router = APIRouter()


class DispositionCreate(BaseModel):
    lead_id: int
    disposition: str
    call_sid: str | None = None       # set = browser call; absent = manual (tel:)
    phone_choice: str = "primary"     # which number a manual call used
    notes: str | None = None
    callback_due_date: date | None = None


@router.post("/dialer/token")
def mint_voice_token(current_user: dict = Depends(get_current_user)):
    """A short-lived Voice access token for the browser SDK. Outgoing-only
    grant — the dialer places calls, it doesn't receive them."""
    if not dialer_configured():
        raise HTTPException(
            status_code=503,
            detail="Browser calling is not configured (TWILIO_API_KEY_SID / "
                   "TWILIO_API_KEY_SECRET / TWILIO_TWIML_APP_SID)",
        )
    import config
    from twilio.jwt.access_token import AccessToken
    from twilio.jwt.access_token.grants import VoiceGrant

    identity = dialer_logic.build_identity(current_user["account_id"], current_user["id"])
    token = AccessToken(config.TWILIO_ACCOUNT_SID, config.TWILIO_API_KEY_SID,
                        config.TWILIO_API_KEY_SECRET, identity=identity, ttl=3600)
    token.add_grant(VoiceGrant(outgoing_application_sid=config.TWILIO_TWIML_APP_SID))
    return {"token": token.to_jwt(), "identity": identity, "ttl_seconds": 3600}


@router.get("/dialer/queue")
def get_queue(
    grade: str | None = Query(None, pattern="^[ABCD]$"),
    statuses: str = Query("new,contacted", description="CSV of lead statuses"),
    cooldown_hours: int = Query(4, ge=0, le=168,
                                description="Hide leads dialed within this window; 0 disables"),
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    account_id = current_user["account_id"]
    status_list = tuple(s.strip() for s in statuses.split(",") if s.strip())
    try:
        conditions, params = dialer_logic.build_queue_filters(
            account_id, grade=grade, statuses=status_list or None,
            cooldown_hours=cooldown_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    where = " AND ".join(conditions)

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM properties p WHERE {where}", params)
        total = cur.fetchone()[0]
        # LATERAL last-outbound-call join: the queue card shows when this lead
        # was last dialed and how it went (idx_calls_property_outbound, 0069).
        cur.execute(
            "SELECT p.id, p.contact_name, p.owner_name, p.address, p.city, p.zip, "
            "       p.contact_phone, p.contact_phone_alt, p.contact_email, "
            "       p.best_time_to_call, p.preferred_contact_method, p.vertical, "
            "       p.status, p.lead_score, p.score_grade, p.estimated_job_value, p.lead_source, "
            "       lc.started_at AS last_call_at, lc.disposition AS last_disposition, "
            "       lc.outcome AS last_outcome "
            "FROM properties p "
            "LEFT JOIN LATERAL ("
            "    SELECT c.started_at, c.disposition, c.outcome FROM calls c "
            "    WHERE c.property_id = p.id AND c.direction = 'outbound' "
            "    ORDER BY c.started_at DESC LIMIT 1"
            ") lc ON TRUE "
            f"WHERE {where} "
            "ORDER BY p.score_grade ASC NULLS LAST, p.lead_score DESC NULLS LAST, p.id "
            "LIMIT %s",
            params + [limit],
        )
        rows = dict_fetchall(cur)

    # Same monthly reveal allowance as the lead list — but a masked lead is
    # useless to a dialer (its phone is withheld), so masked rows are dropped
    # and counted rather than rendered.
    quota = None
    masked_count = 0
    quota_limit = get_scoring_limit(account_id, db)
    if quota_limit is not None:
        rows, quota = scoring_quota.apply_quota(db, account_id, rows, quota_limit)
        visible = [r for r in rows if not r.get("quota_masked")]
        masked_count = len(rows) - len(visible)
        rows = visible

    # Feedback loop: a queued lead has been surfaced (first-only, best-effort).
    emit_surfaced(db, [r["id"] for r in rows], account_id,
                  actor_user_id=current_user["id"])

    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS calls_today, "
            "       COUNT(*) FILTER (WHERE disposition = ANY(%s)) AS connects_today "
            "FROM calls WHERE account_id = %s AND user_id = %s "
            "AND direction = 'outbound' AND started_at >= date_trunc('day', NOW())",
            (list(dialer_logic.CONNECT_DISPOSITIONS), account_id, current_user["id"]),
        )
        calls_today, connects_today = cur.fetchone()

    return {
        "items": rows,
        "total": total,
        "masked_count": masked_count,
        "scoring_quota": quota,
        "stats": {"calls_today": calls_today, "connects_today": connects_today},
        "voice_dialing": dialer_configured(),
    }


@router.post("/dialer/dispositions")
def log_disposition(
    payload: DispositionCreate,
    current_user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    """Record the rep's verdict. Browser mode (call_sid set) annotates the
    calls row the outbound webhook created; manual mode (tel: fallback)
    creates a synthetic completed row. Either way the lead's timeline, status,
    DNC flag, callback task, and feedback-loop events all land here — the
    Twilio status callback stays purely mechanical."""
    account_id = current_user["account_id"]
    user_id = current_user["id"]
    d = payload.disposition
    if not dialer_logic.is_valid_disposition(d):
        raise HTTPException(status_code=400, detail=f"Unknown disposition: {d}")
    if payload.phone_choice not in ("primary", "alt"):
        raise HTTPException(status_code=400, detail="phone_choice must be 'primary' or 'alt'")

    with db.cursor() as cur:
        cur.execute(
            "SELECT status, contact_name, owner_name, contact_phone, contact_phone_alt "
            "FROM properties WHERE id = %s AND account_id = %s",
            (payload.lead_id, account_id),
        )
        lead = cur.fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    current_status, contact_name, owner_name, phone, phone_alt = lead
    history_outcome = dialer_logic.history_outcome_for(d)

    task_id = None
    with db.cursor() as cur:
        if payload.call_sid:
            # Browser call: the webhook already inserted the row; attach the
            # verdict. Scoping by account AND lead makes a forged or
            # cross-tenant sid a plain 404.
            cur.execute(
                "UPDATE calls SET disposition = %s, user_id = COALESCE(user_id, %s) "
                "WHERE call_sid = %s AND account_id = %s AND property_id = %s "
                "RETURNING id",
                (d, user_id, payload.call_sid, account_id, payload.lead_id),
            )
            row = cur.fetchone()
            if not row:
                db.rollback()
                raise HTTPException(status_code=404, detail="Call not found for this lead")
            call_id, call_sid = row[0], payload.call_sid
            cur.execute(
                "UPDATE contact_history SET outcome = %s, body = COALESCE(%s, body) "
                "WHERE external_id = %s",
                (history_outcome, payload.notes, call_sid),
            )
        else:
            # Manual (tel:) call — no webhook ever fires, so the whole record
            # is born here, already completed. Synthetic sid keeps
            # calls.call_sid NOT NULL UNIQUE honest.
            call_sid = dialer_logic.manual_call_sid(uuid4().hex)
            outcome = dialer_logic.outcome_for_disposition(d)
            to_number = phone_alt if payload.phone_choice == "alt" else phone
            cur.execute(
                "INSERT INTO calls (account_id, property_id, call_sid, direction, "
                "                   to_number, status, outcome, disposition, user_id, "
                "                   completed_at) "
                "VALUES (%s, %s, %s, 'outbound', %s, 'completed', %s, %s, %s, NOW()) "
                "RETURNING id",
                (account_id, payload.lead_id, call_sid, to_number, outcome, d, user_id),
            )
            call_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO contact_history (property_id, action, outcome, channel, "
                "                             direction, body, external_id, created_by) "
                "VALUES (%s, %s, %s, 'call', 'outbound', %s, %s, %s)",
                (payload.lead_id, call_logic.outbound_history_action_for(outcome, None),
                 history_outcome, payload.notes, call_sid, user_id),
            )

        if d == "do_not_call":
            cur.execute(
                "UPDATE properties SET do_not_call = TRUE WHERE id = %s AND account_id = %s",
                (payload.lead_id, account_id),
            )
        if d == "callback":
            label = (contact_name or owner_name
                     or call_logic.format_phone_display(
                         "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]))
            cur.execute(
                "INSERT INTO tasks (property_id, assigned_to, title, due_date, priority, "
                "                   created_by, account_id) "
                "VALUES (%s, %s, %s, COALESCE(%s, CURRENT_DATE + 1), 'high', %s, %s) "
                "RETURNING id",
                (payload.lead_id, user_id, dialer_logic.callback_task_title(label),
                 payload.callback_due_date, user_id, account_id),
            )
            task_id = cur.fetchone()[0]
        db.commit()

    # Post-commit side effects. apply_status_change commits internally and
    # fires status_change workflow rules, which is why it must not run inside
    # the transaction above.
    new_status = dialer_logic.status_change_for(d, current_status)
    if new_status:
        from api.lead_logic import apply_status_change
        try:
            apply_status_change(db, payload.lead_id, new_status, user_id, account_id)
        except Exception:
            db.rollback()
            log.exception("Disposition status change failed for lead %s", payload.lead_id)
            new_status = None

    emit_event(db, payload.lead_id, account_id, dialer_logic.event_for(d),
               actor_user_id=user_id, channel="call",
               metadata={"call_sid": call_sid, "disposition": d, "direction": "outbound"})
    if d == "do_not_call":
        emit_event(db, payload.lead_id, account_id, "suppressed",
                   actor_user_id=user_id, channel="call",
                   metadata={"reason": "do_not_call"})

    return {
        "ok": True,
        "call_id": call_id,
        "disposition": d,
        "lead_status": new_status or current_status,
        "do_not_call": d == "do_not_call",
        "task_id": task_id,
    }
