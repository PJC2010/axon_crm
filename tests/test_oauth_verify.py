"""Unit tests for OIDC ID-token verification (api/oauth_verify.py).

Pure/no-network: we generate a throwaway RSA key, expose its public half as a
JWKS (monkeypatched in place of the real Google/Apple fetch), and sign tokens
with the private half — exercising the real signature/issuer/audience checks
without touching the network. Same no-DB style as test_import.py.
"""
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose import jwk as jose_jwk

from api import oauth_verify
from api.oauth_verify import (
    OAuthConfigError,
    OAuthVerifyError,
    verify_apple_id_token,
    verify_google_id_token,
)

KID = "test-kid"
GOOGLE_AUD = "google-client-id.apps.googleusercontent.com"
APPLE_AUD = "com.axon.crm.service"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    pub_jwk = jose_jwk.construct(public_pem, "RS256").to_dict()
    pub_jwk["kid"] = KID
    return private_pem, {"keys": [pub_jwk]}


@pytest.fixture(autouse=True)
def configured(monkeypatch, keypair):
    """Set client ids and short-circuit the JWKS fetch to our local public key."""
    private_pem, jwks = keypair
    monkeypatch.setattr(oauth_verify, "GOOGLE_OAUTH_CLIENT_ID", GOOGLE_AUD)
    monkeypatch.setattr(oauth_verify, "APPLE_CLIENT_ID", APPLE_AUD)
    monkeypatch.setattr(oauth_verify, "_get_jwks", lambda url: jwks)


def _make_token(keypair, *, iss, aud, claims=None, exp_offset=3600):
    private_pem, _ = keypair
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": "subject-123",
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
        "email": "user@example.com",
        "email_verified": True,
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": KID})


# ── Google ────────────────────────────────────────────────────────────────────

def test_google_valid_token(keypair):
    token = _make_token(keypair, iss="https://accounts.google.com", aud=GOOGLE_AUD)
    identity = verify_google_id_token(token)
    assert identity.provider == "google"
    assert identity.sub == "subject-123"
    assert identity.email == "user@example.com"
    assert identity.email_verified is True


def test_google_accepts_bare_issuer(keypair):
    token = _make_token(keypair, iss="accounts.google.com", aud=GOOGLE_AUD)
    assert verify_google_id_token(token).sub == "subject-123"


def test_google_rejects_wrong_audience(keypair):
    token = _make_token(keypair, iss="https://accounts.google.com", aud="some-other-app")
    with pytest.raises(OAuthVerifyError):
        verify_google_id_token(token)


def test_google_rejects_wrong_issuer(keypair):
    token = _make_token(keypair, iss="https://evil.example.com", aud=GOOGLE_AUD)
    with pytest.raises(OAuthVerifyError):
        verify_google_id_token(token)


def test_google_rejects_expired(keypair):
    token = _make_token(keypair, iss="https://accounts.google.com", aud=GOOGLE_AUD, exp_offset=-10)
    with pytest.raises(OAuthVerifyError):
        verify_google_id_token(token)


def test_google_handles_string_email_verified(keypair):
    token = _make_token(
        keypair, iss="https://accounts.google.com", aud=GOOGLE_AUD,
        claims={"email_verified": "true"},
    )
    assert verify_google_id_token(token).email_verified is True


def test_google_unconfigured_raises(keypair, monkeypatch):
    monkeypatch.setattr(oauth_verify, "GOOGLE_OAUTH_CLIENT_ID", "")
    token = _make_token(keypair, iss="https://accounts.google.com", aud=GOOGLE_AUD)
    with pytest.raises(OAuthConfigError):
        verify_google_id_token(token)


# ── Apple ──────────────────────────────────────────────────────────────────────

def test_apple_valid_token(keypair):
    token = _make_token(keypair, iss="https://appleid.apple.com", aud=APPLE_AUD)
    identity = verify_apple_id_token(token)
    assert identity.provider == "apple"
    assert identity.sub == "subject-123"
    assert identity.email == "user@example.com"


def test_apple_rejects_google_audience(keypair):
    token = _make_token(keypair, iss="https://appleid.apple.com", aud=GOOGLE_AUD)
    with pytest.raises(OAuthVerifyError):
        verify_apple_id_token(token)


def test_apple_unconfigured_raises(keypair, monkeypatch):
    monkeypatch.setattr(oauth_verify, "APPLE_CLIENT_ID", "")
    token = _make_token(keypair, iss="https://appleid.apple.com", aud=APPLE_AUD)
    with pytest.raises(OAuthConfigError):
        verify_apple_id_token(token)
