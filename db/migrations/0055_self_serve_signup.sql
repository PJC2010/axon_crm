-- 0055_self_serve_signup.sql — self-serve signup, email verification, password reset.
--
-- Prospective-user audit P0: users could previously only be created via
-- scripts/create_user.py, so the public funnel converted at 0%. POST /auth/signup
-- and the OAuth provisioning path (api/routes/signup.py, api/routes/oauth.py) now
-- create accounts directly.
--
-- users.email_verified tracks whether the address has been confirmed. Existing
-- users were admin-created — treat them as verified so nothing changes for them.
-- OAuth signups inherit the provider's verification.
--
-- user_tokens stores one-time email-verification / password-reset tokens. Only
-- the SHA-256 hash of a token is stored, never the raw value (a DB leak must not
-- yield working reset links).

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE users SET email_verified = TRUE;

CREATE TABLE IF NOT EXISTS user_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose     TEXT NOT NULL,              -- 'verify_email' | 'reset_password'
    token_hash  TEXT NOT NULL UNIQUE,       -- sha256 hex of the raw token
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_tokens_user_purpose ON user_tokens(user_id, purpose);
