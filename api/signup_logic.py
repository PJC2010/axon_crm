"""Pure self-serve-signup logic — validation, username derivation, one-time tokens.

Split out from the routes (api/routes/signup.py) so it unit-tests without a DB
or network, following the same pattern as api/import_logic.py and
api/invoice_logic.py (see tests/test_signup_logic.py).
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

# Lowercase letters/digits plus dot, dash, underscore; 3–32 chars, must start
# alphanumeric. Matches what the team-management create path accepts in spirit
# while keeping derived usernames URL/log-friendly.
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
# Deliberately loose — real validation is the verification email.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD_LEN = 8
# bcrypt silently truncates at 72 bytes, making longer passphrases that differ
# only after byte 72 interchangeable — reject rather than truncate.
MAX_PASSWORD_BYTES = 72
MAX_COMPANY_LEN = 80

VERIFY_EMAIL_TTL = timedelta(days=3)
RESET_PASSWORD_TTL = timedelta(hours=2)
TOKEN_PURPOSES = ("verify_email", "reset_password")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def password_problem(password: str) -> str | None:
    """One shared rule for every path that sets a password (signup, team-member
    creation, reset). Returns a human-readable problem or None."""
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len((password or "").encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password must be {MAX_PASSWORD_BYTES} bytes or fewer."
    return None


def validate_signup(*, company: str, email: str, password: str,
                    username: str | None = None) -> list[str]:
    """Return human-readable problems with a signup request (empty = valid)."""
    problems: list[str] = []
    if not (company or "").strip():
        problems.append("Company or business name is required.")
    elif len(company.strip()) > MAX_COMPANY_LEN:
        problems.append(f"Company name must be {MAX_COMPANY_LEN} characters or fewer.")
    if not EMAIL_RE.match(normalize_email(email)):
        problems.append("A valid email address is required.")
    pw_problem = password_problem(password)
    if pw_problem:
        problems.append(pw_problem)
    if username is not None and not USERNAME_RE.match(username):
        problems.append(
            "Username must be 3–32 characters — lowercase letters, numbers, "
            "dots, dashes or underscores, starting with a letter or number."
        )
    return problems


def derive_username(email: str) -> str:
    """Turn an email's local part into a valid username base.

    'Dan.The-Man+leads@example.com' → 'dan.the-man'. Falls back to 'user' when
    nothing usable survives cleaning; uniqueness is the caller's job (see
    username_candidates).
    """
    local = normalize_email(email).split("@", 1)[0]
    local = local.split("+", 1)[0]                      # strip plus-tags
    local = re.sub(r"[^a-z0-9._-]", "", local)
    local = re.sub(r"^[._-]+", "", local)[:32]          # must start alphanumeric
    if len(local) < 3 or not USERNAME_RE.match(local):
        local = (local + "user")[:32] if local else "user"
        if not USERNAME_RE.match(local):
            local = "user"
    return local


def username_candidates(base: str, attempts: int = 20):
    """Yield `base`, then numbered variants (base2, base3, …) to try on conflict."""
    yield base
    for i in range(2, attempts + 2):
        suffix = str(i)
        yield (base[: 32 - len(suffix)] + suffix)


def new_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex). Only the hash is ever stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def token_expiry(purpose: str, now: datetime | None = None) -> datetime:
    if purpose not in TOKEN_PURPOSES:
        raise ValueError(f"Unknown token purpose: {purpose!r}")
    now = now or datetime.now(timezone.utc)
    ttl = VERIFY_EMAIL_TTL if purpose == "verify_email" else RESET_PASSWORD_TTL
    return now + ttl


def token_is_live(expires_at: datetime, used_at: datetime | None,
                  now: datetime | None = None) -> bool:
    """A token is usable while unexpired and never used (single-use)."""
    if used_at is not None:
        return False
    now = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        # Defensive: TIMESTAMPTZ round-trips aware, but tolerate naive values.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > now
