-- session_hardening
--
-- 1) users.password_changed_at — set whenever a password is reset/changed.
--    api/deps.py rejects JWTs issued (iat) before this timestamp, so a stolen
--    session dies the moment the victim resets their password instead of
--    living out its remaining 8 hours. NULL = never changed = no extra check.
--
-- 2) Failed-login lookup index — api/routes/auth.py counts recent failures
--    per attempted_identifier (cross-instance lockout; the in-memory IP
--    limiter is per-process). Partial on success = FALSE to stay tiny.

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_auth_events_identifier_failed
    ON auth_events (attempted_identifier, created_at DESC)
    WHERE success = FALSE;
