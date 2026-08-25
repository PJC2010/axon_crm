"""
Self-serve signup + account-recovery flows.

POST /auth/signup                  — company + email + password → new org + owner + JWT
GET  /auth/signup-status           — is self-serve signup enabled? (public, for the UI)
POST /auth/verify-email            — one-time token from the verification email
POST /auth/resend-verification     — authed; re-send the verification email
POST /auth/request-password-reset  — always 200 (no account enumeration); emails a link
POST /auth/reset-password          — one-time token + new password

Provisioning goes through api.accounts.provision_owner — the same defaults as
the CLI bootstrap (scripts/create_user.py), so self-serve and admin-created
accounts are identical. Signup also sends a welcome email to the new owner and
an internal alert to ADMIN_NOTIFICATION_EMAIL. Email sending fails soft: with Resend unconfigured,
signup still succeeds (the token just goes nowhere) and reset returns the same
generic 200 — configure RESEND_API_KEY / RESEND_FROM_EMAIL to activate both.
"""
import logging

import psycopg2.errors
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel

from config import APP_BASE_URL, SELF_SERVE_SIGNUP, TRIAL_DAYS
from api.accounts import provision_owner
from api.business_types import BUSINESS_TYPES, DEFAULT_BUSINESS_TYPE
from api.deps import get_db, get_current_user, dict_fetchone
from api.notifications import (
    admin_alerts_configured, email_configured, send_admin_signup_alert,
    send_email, send_welcome_email,
)
from api.ratelimit import client_ip, signup_limiter, password_reset_limiter
from api.routes.auth import TokenResponse
from api.security import create_access_token, hash_password
from api.signup_logic import (
    derive_username, hash_token, new_token, normalize_email, password_problem,
    token_expiry, validate_signup,
)

log = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    company_name: str
    email: str
    password: str
    username: str | None = None            # optional; derived from email if omitted
    business_type: str | None = None
    # Optional A2P 10DLC opt-in from the signup form's consent checkbox.
    # Stamped on the user row with timestamp + source 'signup' (migration 064).
    sms_consent: bool = False
    # Meta CAPI dedup: the browser generates one event id and fires the browser
    # StartTrial with it, then sends it (plus the _fbp/_fbc pixel cookies, which
    # are first-party to the site and never reach this cross-origin API on their
    # own) so the server StartTrial can share the id and the match keys. All
    # optional — an older client or a curl signup just omits them.
    meta_event_id: str | None = None
    fbp: str | None = None
    fbc: str | None = None


class VerifyEmailRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


# ── Email helpers (fail-soft) ─────────────────────────────────────────────────

def _try_send(to_email: str, subject: str, html: str) -> bool:
    if not email_configured():
        log.info("Email not configured — skipping '%s' to %s", subject, to_email)
        return False
    try:
        send_email(to_email=to_email, subject=subject, html=html)
        return True
    except Exception:
        log.warning("Failed sending '%s' to %s", subject, to_email, exc_info=True)
        return False


def _send_verification_email(to_email: str, raw_token: str) -> bool:
    link = f"{APP_BASE_URL}/verify-email?token={raw_token}"
    return _try_send(
        to_email,
        "Verify your email for Axon",
        f"""
        <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
          <h2 style="margin:0 0 12px">Welcome to Axon</h2>
          <p>Confirm this email address to secure your account.</p>
          <p style="margin:24px 0"><a href="{link}"
             style="background:#1a5a75;color:#fff;text-decoration:none;padding:12px 24px;
                    border-radius:8px;font-weight:600">Verify email</a></p>
          <p style="color:#888;font-size:13px">This link expires in 3 days. If you didn't
          create an Axon account, you can ignore this email.</p>
        </div>
        """,
    )


def _send_reset_email(to_email: str, raw_token: str) -> bool:
    link = f"{APP_BASE_URL}/reset-password?token={raw_token}"
    return _try_send(
        to_email,
        "Reset your Axon password",
        f"""
        <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
          <h2 style="margin:0 0 12px">Reset your password</h2>
          <p>Someone (hopefully you) asked to reset the password for this Axon login.</p>
          <p style="margin:24px 0"><a href="{link}"
             style="background:#1a5a75;color:#fff;text-decoration:none;padding:12px 24px;
                    border-radius:8px;font-weight:600">Choose a new password</a></p>
          <p style="color:#888;font-size:13px">This link expires in 2 hours and works once.
          If you didn't request this, your password is unchanged.</p>
        </div>
        """,
    )


def _issue_token(db: PGConn, user_id: int, purpose: str) -> str:
    """Create a one-time token row and return the raw token (for the email link).

    Older unused tokens for the same purpose are invalidated so only the most
    recent link works — reset links in stale emails shouldn't stay live.
    """
    raw, hashed = new_token()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE user_tokens SET used_at = NOW() "
            "WHERE user_id = %s AND purpose = %s AND used_at IS NULL",
            (user_id, purpose),
        )
        cur.execute(
            "INSERT INTO user_tokens (user_id, purpose, token_hash, expires_at) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, purpose, hashed, token_expiry(purpose)),
        )
    return raw


def _consume_token(db: PGConn, raw_token: str, purpose: str) -> int:
    """Validate + burn a one-time token; return its user_id or raise 400.

    A single conditional UPDATE — the SQL predicates are `token_is_live`
    (api/signup_logic.py) expressed in-row — so two concurrent requests with
    the same token can't both pass a check-then-set race; only one wins.
    """
    with db.cursor() as cur:
        cur.execute(
            "UPDATE user_tokens SET used_at = NOW() "
            "WHERE token_hash = %s AND purpose = %s "
            "  AND used_at IS NULL AND expires_at > NOW() "
            "RETURNING user_id",
            (hash_token(raw_token), purpose),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="This link is invalid or has expired.")
    return row[0]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/auth/signup-status")
def signup_status():
    """Lets the frontend hide/show self-serve signup without hardcoding it."""
    return {"enabled": SELF_SERVE_SIGNUP}


@router.post("/auth/signup", response_model=TokenResponse, status_code=201)
def signup(body: SignupRequest, request: Request, db: PGConn = Depends(get_db)):
    if not SELF_SERVE_SIGNUP:
        raise HTTPException(status_code=403, detail="Self-serve signup is disabled.")
    signup_limiter.check(client_ip(request))

    problems = validate_signup(company=body.company_name, email=body.email,
                               password=body.password, username=body.username)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    business_type = body.business_type or DEFAULT_BUSINESS_TYPE
    if business_type not in BUSINESS_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown business type: {business_type}")

    email = normalize_email(body.email)
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE lower(email) = %s", (email,))
        if cur.fetchone():
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Try signing in instead.",
            )

    try:
        created = provision_owner(
            db,
            company=body.company_name.strip(),
            email=email,
            username_base=body.username or derive_username(email),
            hashed_pw=hash_password(body.password),
            business_type=business_type,
            sms_consent=body.sms_consent,
        )
        raw_token = _issue_token(db, created["user_id"], "verify_email")
        db.commit()
    except HTTPException:
        raise
    except psycopg2.errors.UniqueViolation:
        # Two concurrent signups for the same email both passed the pre-check;
        # the UNIQUE constraint caught the loser — a 409, not a server error.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Try signing in instead.",
        )
    except Exception:
        db.rollback()
        log.exception("Signup provisioning failed for %s", email)
        raise HTTPException(status_code=500, detail="Could not create your account — try again.")

    # Post-commit emails, all fail-soft — a mail hiccup must never fail signup.
    _send_verification_email(email, raw_token)
    if email_configured():
        try:
            send_welcome_email(to_email=email, company_name=body.company_name.strip(),
                               trial_days=TRIAL_DAYS)
        except Exception:
            log.warning("Failed sending welcome email to %s", email, exc_info=True)
    if admin_alerts_configured():
        try:
            send_admin_signup_alert(company_name=body.company_name.strip(), email=email,
                                    business_type=business_type,
                                    username=created["username"])
        except Exception:
            log.warning("Failed sending admin signup alert for %s", email, exc_info=True)

    # Server-side StartTrial (Meta CAPI). Best-effort — a tracking failure must
    # never fail a signup that already committed. external_id is the account id so
    # this trial links to its later paid Subscribe (api/routes/billing.py). The
    # event_id mirrors the browser StartTrial for dedup; if the client didn't send
    # one, fall back to a deterministic id so the server event still lands cleanly.
    try:
        from api import meta_capi
        meta_capi.track_start_trial(
            email=email,
            external_id=str(created["account_id"]),
            event_id=body.meta_event_id or f"trial_{created['account_id']}",
            fbp=body.fbp,
            fbc=body.fbc,
            client_ip=client_ip(request),
            client_ua=request.headers.get("user-agent"),
            event_source_url=request.headers.get("referer") or f"{APP_BASE_URL}/signup",
        )
    except Exception:
        log.warning("Meta CAPI StartTrial emit failed for %s", email, exc_info=True)

    token = create_access_token(created["user_id"], created["username"], "owner")
    return TokenResponse(access_token=token)


@router.post("/auth/verify-email")
def verify_email(body: VerifyEmailRequest, db: PGConn = Depends(get_db)):
    user_id = _consume_token(db, body.token, "verify_email")
    with db.cursor() as cur:
        cur.execute("UPDATE users SET email_verified = TRUE WHERE id = %s", (user_id,))
        db.commit()
    return {"ok": True}


@router.post("/auth/resend-verification")
def resend_verification(current_user: dict = Depends(get_current_user),
                        db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT email, email_verified FROM users WHERE id = %s",
                    (current_user["id"],))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if row["email_verified"]:
        return {"ok": True, "sent": False, "already_verified": True}
    raw_token = _issue_token(db, current_user["id"], "verify_email")
    db.commit()
    sent = _send_verification_email(row["email"], raw_token)
    return {"ok": True, "sent": sent}


@router.post("/auth/request-password-reset")
def request_password_reset(body: PasswordResetRequest, request: Request,
                           db: PGConn = Depends(get_db)):
    """Always returns the same 200 so responses can't enumerate accounts."""
    password_reset_limiter.check(client_ip(request))
    email = normalize_email(body.email)
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE lower(email) = %s AND is_active = TRUE",
            (email,),
        )
        row = cur.fetchone()
    if row:
        raw_token = _issue_token(db, row[0], "reset_password")
        db.commit()
        _send_reset_email(email, raw_token)
    return {"ok": True, "detail": "If that email has an account, a reset link is on its way."}


@router.post("/auth/reset-password")
def reset_password(body: PasswordResetConfirm, db: PGConn = Depends(get_db)):
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    user_id = _consume_token(db, body.token, "reset_password")
    with db.cursor() as cur:
        # Coming from an emailed link, so the address is confirmed as a side
        # effect. password_changed_at invalidates every JWT issued before this
        # moment (api/deps.py) — resetting is what a compromised user does, so
        # a stolen session must not outlive it.
        cur.execute(
            "UPDATE users SET hashed_pw = %s, email_verified = TRUE, "
            "password_changed_at = NOW() WHERE id = %s",
            (hash_password(body.new_password), user_id),
        )
        db.commit()
    return {"ok": True}
