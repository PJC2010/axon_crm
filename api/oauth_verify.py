"""Verify Google / Apple OpenID Connect ID tokens for social login.

Both "Sign in with Google" and "Sign in with Apple" hand the frontend a signed
OIDC **ID token** (a JWT). This module verifies that token's signature against
the provider's published JWKS and checks its issuer/audience/expiry, then
returns the claims we trust (stable subject id + email). It does NOT mint our
own session token — the auth route does that via api.security.create_access_token.

Kept free of FastAPI/DB concerns (network only, to fetch JWKS) so it can be
unit-tested directly, in the same spirit as api/calendar_ics.py. Reuses the
already-installed python-jose[cryptography] for RS256 + JWKS verification.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests
from jose import jwt
from jose.exceptions import JWTError

from config import APPLE_CLIENT_ID, GOOGLE_OAUTH_CLIENT_ID

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

# Providers' signing keys rotate slowly; cache them per-process to avoid a
# network round trip on every login. Short TTL so rotation is picked up.
_JWKS_TTL_SECONDS = 3600


@dataclass
class OAuthIdentity:
    """The trusted claims extracted from a verified ID token."""
    provider: str          # 'google' | 'apple'
    sub: str               # stable subject id (the IdP's user id)
    email: str | None
    email_verified: bool
    name: str | None = None


class OAuthConfigError(RuntimeError):
    """Raised when an OAuth provider is called but isn't configured."""


class OAuthVerifyError(ValueError):
    """Raised when an ID token fails verification."""


# ── JWKS fetching (cached) ─────────────────────────────────────────────────────

_jwks_cache: dict[str, tuple[float, dict]] = {}
_jwks_lock = threading.Lock()


def _get_jwks(url: str) -> dict:
    """Fetch and cache a provider's JWKS document. Falls back to a stale cache
    entry if a refresh fails, so a transient network blip doesn't block login."""
    now = time.monotonic()
    with _jwks_lock:
        cached = _jwks_cache.get(url)
        if cached and now - cached[0] < _JWKS_TTL_SECONDS:
            return cached[1]
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        jwks = resp.json()
    except Exception as exc:  # network / parse failure
        with _jwks_lock:
            cached = _jwks_cache.get(url)
        if cached:
            return cached[1]
        raise OAuthVerifyError(f"Could not fetch signing keys: {exc}") from exc
    with _jwks_lock:
        _jwks_cache[url] = (now, jwks)
    return jwks


def _verify(token: str, jwks_url: str, issuers: set[str], audience: str) -> dict:
    """Verify an RS256 ID token against a JWKS and return its claims."""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise OAuthVerifyError(f"Malformed token: {exc}") from exc

    jwks = _get_jwks(jwks_url)
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        # Key id not in the cache — force one refresh in case keys just rotated.
        with _jwks_lock:
            _jwks_cache.pop(jwks_url, None)
        jwks = _get_jwks(jwks_url)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise OAuthVerifyError("Token signed with an unknown key")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise OAuthVerifyError(f"Token verification failed: {exc}") from exc

    if claims.get("iss") not in issuers:
        raise OAuthVerifyError("Unexpected token issuer")
    return claims


# ── Public API ──────────────────────────────────────────────────────────────

def verify_google_id_token(token: str) -> OAuthIdentity:
    if not GOOGLE_OAUTH_CLIENT_ID:
        raise OAuthConfigError("Google sign-in is not configured (GOOGLE_OAUTH_CLIENT_ID)")
    claims = _verify(token, GOOGLE_JWKS_URL, GOOGLE_ISSUERS, GOOGLE_OAUTH_CLIENT_ID)
    return OAuthIdentity(
        provider="google",
        sub=claims["sub"],
        email=claims.get("email"),
        # Google sends email_verified as a bool or the string "true".
        email_verified=str(claims.get("email_verified", "")).lower() == "true"
        or claims.get("email_verified") is True,
        name=claims.get("name"),
    )


def verify_apple_id_token(token: str) -> OAuthIdentity:
    if not APPLE_CLIENT_ID:
        raise OAuthConfigError("Apple sign-in is not configured (APPLE_CLIENT_ID)")
    claims = _verify(token, APPLE_JWKS_URL, {APPLE_ISSUER}, APPLE_CLIENT_ID)
    return OAuthIdentity(
        provider="apple",
        sub=claims["sub"],
        email=claims.get("email"),
        # Apple sends email_verified as a bool or the string "true".
        email_verified=str(claims.get("email_verified", "")).lower() == "true"
        or claims.get("email_verified") is True,
        name=None,  # Apple only sends the name on the very first authorization.
    )
