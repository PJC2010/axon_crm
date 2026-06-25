"""
Social login (Sign in with Google / Apple) — authentication only.

POST /api/auth/oauth/google  — body {id_token} → JWT (same shape as password login)
POST /api/auth/oauth/apple   — body {id_token} → JWT

The frontend obtains an OIDC ID token from Google Identity Services / Sign in
with Apple JS and posts it here. We verify the token (api/oauth_verify.py),
match an EXISTING active user by the provider's stable subject id (or, on first
use, by verified email), record the identity link, and issue our own JWT via the
same create_access_token used by password login. No new account/org is ever
created — this preserves the invite-only model (a user must already exist).
Data sync (contacts/documents/calendars) is a separate, later phase that reuses
the connections framework (migration 032), not this route.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn

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
from api.security import create_access_token

log = logging.getLogger(__name__)
router = APIRouter()

# Human-readable provider names for the invite-only error message.
_PROVIDER_LABEL = {"google": "Google", "apple": "Apple"}


def _login_with_identity(identity: OAuthIdentity, db: PGConn) -> TokenResponse:
    """Resolve a verified social identity to an existing user and mint a JWT.

    Matching order: (1) a previously-linked (provider, sub); (2) on first use, an
    existing user by verified email — which then records the link. An unknown
    identity is rejected (403) rather than provisioning a new account.
    """
    label = _PROVIDER_LABEL.get(identity.provider, identity.provider)

    with db.cursor() as cur:
        # 1. Already linked? Match on the provider's stable subject id.
        cur.execute(
            "SELECT u.id, u.username, u.role, u.is_active "
            "FROM oauth_identities oi JOIN users u ON u.id = oi.user_id "
            "WHERE oi.provider = %s AND oi.provider_sub = %s",
            (identity.provider, identity.sub),
        )
        user = dict_fetchone(cur)

        # 2. First use: match an existing invited user by verified email, then link.
        if user is None:
            if not identity.email or not identity.email_verified:
                raise HTTPException(
                    status_code=403,
                    detail=f"Your {label} account did not provide a verified email.",
                )
            cur.execute(
                "SELECT id, username, role, is_active FROM users "
                "WHERE lower(email) = lower(%s)",
                (identity.email,),
            )
            user = dict_fetchone(cur)
            if user is None:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"No Axon account is linked to this {label} address. "
                        "Ask your administrator to invite you first."
                    ),
                )
            if not user["is_active"]:
                raise HTTPException(status_code=403, detail="Account disabled")
            cur.execute(
                "INSERT INTO oauth_identities (user_id, provider, provider_sub, email) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (provider, provider_sub) DO NOTHING",
                (user["id"], identity.provider, identity.sub, identity.email),
            )
            db.commit()

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token(user["id"], user["username"], user["role"])
    return TokenResponse(access_token=token)


@router.post("/auth/oauth/google", response_model=TokenResponse)
def login_google(body: IdTokenRequest, request: Request, db: PGConn = Depends(get_db)):
    login_limiter.check(client_ip(request))
    try:
        identity = verify_google_id_token(body.id_token)
    except OAuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OAuthVerifyError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {exc}")
    return _login_with_identity(identity, db)


@router.post("/auth/oauth/apple", response_model=TokenResponse)
def login_apple(body: IdTokenRequest, request: Request, db: PGConn = Depends(get_db)):
    login_limiter.check(client_ip(request))
    try:
        identity = verify_apple_id_token(body.id_token)
    except OAuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OAuthVerifyError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Apple token: {exc}")
    return _login_with_identity(identity, db)
