"""
Tests for the pure self-serve-signup logic (api/signup_logic.py): request
validation, username derivation from emails, and one-time-token lifecycle
helpers. No DB or network — same pattern as test_import.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from api import signup_logic as sl


# ── validate_signup ───────────────────────────────────────────────────────────

def test_valid_signup_has_no_problems():
    assert sl.validate_signup(company="Spring Exterior Services",
                              email="danny@example.com",
                              password="longenough1") == []


def test_each_field_reports_its_own_problem():
    problems = sl.validate_signup(company="", email="not-an-email", password="short")
    assert len(problems) == 3
    joined = " ".join(problems)
    assert "Company" in joined and "email" in joined and "Password" in joined


def test_company_length_capped():
    problems = sl.validate_signup(company="X" * (sl.MAX_COMPANY_LEN + 1),
                                  email="a@b.co", password="longenough1")
    assert len(problems) == 1


def test_explicit_username_validated():
    ok = sl.validate_signup(company="A", email="a@b.co", password="longenough1",
                            username="danny.h-77")
    assert ok == []
    bad = sl.validate_signup(company="A", email="a@b.co", password="longenough1",
                             username="-starts-with-dash")
    assert len(bad) == 1


def test_email_is_normalized_before_validation():
    assert sl.validate_signup(company="A", email="  Danny@Example.COM ",
                              password="longenough1") == []
    assert sl.normalize_email("  Danny@Example.COM ") == "danny@example.com"


# ── derive_username / username_candidates ─────────────────────────────────────

def test_derive_username_cleans_local_part():
    assert sl.derive_username("Dan.The-Man+leads@example.com") == "dan.the-man"


def test_derive_username_strips_leading_punctuation_and_falls_back():
    assert sl.derive_username("__x@example.com").startswith("x")
    assert sl.derive_username("!!@example.com") == "user"
    # Every derivation must satisfy the username rule.
    for email in ("a@b.co", "-.-@b.co", "very.long." + "x" * 60 + "@b.co", "毛@b.co"):
        assert sl.USERNAME_RE.match(sl.derive_username(email)), email


def test_username_candidates_orders_and_respects_length():
    cands = list(sl.username_candidates("danny", attempts=3))
    assert cands[0] == "danny"
    assert cands[1] == "danny2"
    long_base = "x" * 32
    for cand in sl.username_candidates(long_base, attempts=12):
        assert len(cand) <= 32


# ── one-time tokens ───────────────────────────────────────────────────────────

def test_new_token_hash_roundtrip_and_uniqueness():
    raw1, hashed1 = sl.new_token()
    raw2, hashed2 = sl.new_token()
    assert raw1 != raw2
    assert sl.hash_token(raw1) == hashed1
    assert hashed1 != hashed2
    # Only the hash is meant to be stored — it must not contain the raw token.
    assert raw1 not in hashed1


def test_token_expiry_per_purpose():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    assert sl.token_expiry("verify_email", now) == now + sl.VERIFY_EMAIL_TTL
    assert sl.token_expiry("reset_password", now) == now + sl.RESET_PASSWORD_TTL
    with pytest.raises(ValueError):
        sl.token_expiry("bogus", now)


def test_token_is_live_rules():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    future = now + timedelta(hours=1)
    past = now - timedelta(hours=1)
    assert sl.token_is_live(future, None, now) is True
    assert sl.token_is_live(past, None, now) is False          # expired
    assert sl.token_is_live(future, past, now) is False        # single-use
    # Naive timestamps (defensive path) are treated as UTC.
    assert sl.token_is_live(future.replace(tzinfo=None), None, now) is True
