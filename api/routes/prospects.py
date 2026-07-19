"""
POST /api/public/prospect — email capture from the public landing / preview
pages ("get a walkthrough" forms).

Unauthenticated and browser-facing (unlike public_intake's shared-secret,
server-to-server flow), so it is rate-limited per IP and stores nothing but
what the visitor typed. Rows land in the platform-level prospect_signups
table (no account_id — these are prospects for Axon itself, not tenant data)
and an internal alert goes to ADMIN_NOTIFICATION_EMAIL, fail-soft.

Always returns the same 200 for valid input, including repeat submissions,
so the endpoint can't be used to probe which emails are already known.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from api.deps import get_db
from api.notifications import admin_alerts_configured, send_admin_prospect_alert
from api.ratelimit import client_ip, prospect_limiter
from api.signup_logic import EMAIL_RE, normalize_email

log = logging.getLogger(__name__)
public_router = APIRouter()

ALLOWED_SOURCES = {"landing", "preview"}


class ProspectCreate(BaseModel):
    email: str
    name: str | None = None
    source: str | None = None


@public_router.post("/public/prospect", status_code=200)
def create_prospect(body: ProspectCreate, request: Request, db: PGConn = Depends(get_db)):
    prospect_limiter.check(client_ip(request))

    email = normalize_email(body.email)
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    name = (body.name or "").strip()[:200] or None
    source = body.source if body.source in ALLOWED_SOURCES else "landing"

    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prospect_signups (email, name, source)
            VALUES (%s, %s, %s)
            ON CONFLICT (lower(email)) DO UPDATE
                SET name = COALESCE(EXCLUDED.name, prospect_signups.name),
                    source = EXCLUDED.source,
                    updated_at = NOW()
            RETURNING (created_at = updated_at) AS is_new
            """,
            (email, name, source),
        )
        is_new = cur.fetchone()[0]
    db.commit()

    # Alert the platform owner on first contact only; repeats just refresh the row.
    if is_new and admin_alerts_configured():
        try:
            send_admin_prospect_alert(email=email, name=name, source=source)
        except Exception:
            log.warning("Failed sending prospect alert for %s", email, exc_info=True)

    return {"ok": True, "detail": "Thanks — we'll be in touch shortly."}
