"""
Social login (Sign in with Google / Apple).

POST /api/auth/oauth/google  — body {id_token} → JWT (same shape as password login)
POST /api/auth/oauth/apple   — body {id_token} → JWT

The frontend obtains an OIDC ID token from Google Identity Services / Sign in
with Apple JS and posts it here. We verify the token (api/oauth_verify.py),
match a user by the provider's stable subject id (or, on first use, by verified
email), record the identity link, and issue our own JWT via the same
create_access_token used by password login.

An identity that matches no user PROVISIONS a fresh org + owner (same defaults
as POST /auth/signup, via api.accounts.provision_owner) when SELF_SERVE_SIGNUP
is on; with it off the old invite-only 403 applies. Data sync
(contacts/documents/calendars) is a separate, later phase that reuses the
connections framework (migration 032), not this route.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn

from config import SELF_SERVE_SIGNUP
from api.accounts import provision_owner
from api.auth_events import record_auth_event
from api.deps import dict_fetchone, get_db
from api.oauth_verify import (
    OAuthConfigError,
    OAuthIdentity,
    OAuthVerifyError,
    verify_apple_id_token,
    verify_google_id_token,
)
from api.ratelimit import client_ip, login_limiter
from api.routes.auth import IdTokenRequest, TokenResponse
from api.security import create_access_token, hash_password
from api.signup_logic import derive_username, new_token

log = logging.getLogger(__name__)
router = APIRouter()

# Human-readable provider names for error messages.
_PROVIDER_LABEL = {"google": "Google", "apple": "Apple"}


def _provision_from_identity(identity: OAuthIdentity, db: PGConn) -> dict:
    """First-ever login with this identity: create a fresh org + owner user.

    The org is named after the person (they rename it in onboarding/settings);
    the unusable random password means the login works only via OAuth until the
    owner sets one through the reset flow. Email arrives provider-verified.
    """
    company = (identity.name or derive_username(identity.email)).strip() or "My business"
    created = provision_owner(
        db,
        company=company,
        email=identity.email.lower(),
        username_base=derive_username(identity.email),
        hashed_pw=hash_password(new_token()[0]),
        email_verified=True,
    )
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO oauth_identities (user_id, provider, provider_sub, email) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (provider, provider_sub) DO NOTHING",
            (created["user_id"], identity.provider, identity.sub, identity.email),
        )
    db.commit()
    log.info("Provisioned account %d via %s signup for %s",
             created["account_id"], identity.provider, identity.email)
    return {"id": created["user_id"], "username": created["username"],
            "role": "owner", "is_active": True, "account_id": created["account_id"]}


def _login_with_identity(identity: OAuthIdentity, db: PGConn, request: Request) -> TokenResponse:
    """Resolve a verified social identity to a user (provisioning one on first
    use when self-serve signup is enabled) and mint a JWT.

    Matching order: (1) a previously-linked (provider, sub); (2) on first use,
    an existing user by verified email — which then records the link;
    (3) nobody → provision a fresh org + owner (or 403 in invite-only mode).
    Outcomes are recorded to auth_events (api/auth_events.py); error responses
    stay as they were.
    """
    label = _PROVIDER_LABEL.get(identity.provider, identity.provider)
    ip, ua = client_ip(request), request.headers.get("user-agent")

    def _record_failure(reason: str, user_row: dict | None = None) -> None:
        record_auth_event(db, success=False, method=identity.provider,
                          identifier=identity.email or None, failure_reason=reason,
                          user_id=user_row["id"] if user_row else None,
                          account_id=(user_row or {}).get("account_id"),
                          ip=ip, user_agent=ua)

    with db.cursor() as cur:
        # 1. Already linked? Match on the provider's stable subject id.
        cur.execute(
            "SELECT u.id, u.username, u.role, u.is_active, u.account_id "
            "FROM oauth_identities oi JOIN users u ON u.id = oi.user_id "
            "WHERE oi.provider = %s AND oi.provider_sub = %s",
            (identity.provider, identity.sub),
        )
        user = dict_fetchone(cur)

        # 2. First use: match an existing user by verified email, then link.
        if user is None:
            if not identity.email or not identity.email_verified:
                _record_failure("oauth_unlinked")
                raise HTTPException(
                    status_code=403,
                    detail=f"Your {label} account did not provide a verified email.",
                )
            cur.execute(
                "SELECT id, username, role, is_active, account_id FROM users "
                "WHERE lower(email) = lower(%s)",
                (identity.email,),
            )
            user = dict_fetchone(cur)
            if user is not None:
                if not user["is_active"]:
                    _record_failure("inactive", user)
                    raise HTTPException(status_code=403, detail="Account disabled")
                cur.execute(
                    "INSERT INTO oauth_identities (user_id, provider, provider_sub, email) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (provider, provider_sub) DO NOTHING",
                    (user["id"], identity.provider, identity.sub, identity.email),
                )
                db.commit()

    # 3. Genuinely new: self-serve provisioning (or invite-only rejection).
    if user is None:
        if not SELF_SERVE_SIGNUP:
            _record_failure("oauth_unlinked")
            raise HTTPException(
                status_code=403,
                detail=(
                    f"No Axon account is linked to this {label} address. "
                    "Ask your administrator to invite you first."
                ),
            )
        try:
            user = _provision_from_identity(identity, db)
        except Exception:
            db.rollback()
            log.exception("OAuth provisioning failed for %s via %s",
                          identity.email, identity.provider)
            raise HTTPException(status_code=500,
                                detail="Could not create your account — try again.")

    if not user["is_active"]:
        _record_failure("inactive", user)
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token(user["id"], user["username"], user["role"])
    record_auth_event(db, success=True, method=identity.provider,
                      identifier=identity.email or user["username"],
                      user_id=user["id"], account_id=user.get("account_id"),
                      ip=ip, user_agent=ua)
    return TokenResponse(access_token=token)


@router.post("/auth/oauth/google", response_model=TokenResponse)
def login_google(body: IdTokenRequest, request: Request, db: PGConn = Depends(get_db)):
    login_limiter.check(client_ip(request))
    try:
        identity = verify_google_id_token(body.id_token)
    except OAuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OAuthVerifyError as exc:
        record_auth_event(db, success=False, method="google",
                          failure_reason="oauth_invalid", ip=client_ip(request),
                          user_agent=request.headers.get("user-agent"))
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {exc}")
    return _login_with_identity(identity, db, request)


@router.post("/auth/oauth/apple", response_model=TokenResponse)
def login_apple(body: IdTokenRequest, request: Request, db: PGConn = Depends(get_db)):
    login_limiter.check(client_ip(request))
    try:
        identity = verify_apple_id_token(body.id_token)
    except OAuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OAuthVerifyError as exc:
        record_auth_event(db, success=False, method="apple",
                          failure_reason="oauth_invalid", ip=client_ip(request),
                          user_agent=request.headers.get("user-agent"))
        raise HTTPException(status_code=401, detail=f"Invalid Apple token: {exc}")
    return _login_with_identity(identity, db, request)
