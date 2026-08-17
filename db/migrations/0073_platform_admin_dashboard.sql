-- platform_admin_dashboard — cross-tenant super-admin surface (api/routes/admin.py).
--
-- users.is_platform_admin is ORTHOGONAL to the tenant `role` column: role governs
-- power inside one org (require_owner), this flag governs the cross-tenant
-- /api/admin surface (require_platform_admin). It is never carried in the JWT —
-- get_current_user re-reads the row every request, so revocation is immediate.
-- Flag the first admin manually:
--   UPDATE users SET is_platform_admin = TRUE WHERE email = 'you@example.com';
-- or: python scripts/set_platform_admin.py --email you@example.com --grant

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

-- users(account_id) had no index; admin listings and the unverified-signup
-- digest both join/aggregate on it.
CREATE INDEX IF NOT EXISTS idx_users_account ON users(account_id);

-- Login/auth outcomes, success AND failure, for password and OAuth logins
-- (api/auth_events.py). user_id is NULL when the identifier matched nobody;
-- attempted_identifier keeps what was typed. account_id is denormalized so
-- per-org drill-downs don't need a users join for deleted users. failure_reason
-- (unknown_user|bad_password|inactive|oauth_invalid|oauth_unlinked) is stored
-- server-side only — login responses stay generic to avoid account enumeration.
CREATE TABLE IF NOT EXISTS auth_events (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              INTEGER REFERENCES users(id) ON DELETE SET NULL,
    account_id           INTEGER,
    attempted_identifier TEXT,
    method               TEXT NOT NULL DEFAULT 'password',  -- password|google|apple
    success              BOOLEAN NOT NULL,
    failure_reason       TEXT,
    ip                   TEXT,
    user_agent           TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_auth_events_created ON auth_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_events_user    ON auth_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_events_account ON auth_events(account_id, created_at DESC);
-- Serves the security panel's "failed logins in the last 24h grouped by
-- IP / identifier" queries without scanning successes.
CREATE INDEX IF NOT EXISTS idx_auth_events_failed  ON auth_events(created_at DESC)
    WHERE success = FALSE;

-- Every mutation made through the admin surface: who did what to which target.
-- detail carries the diff (changed fields, plan names) — NEVER tokens or
-- passwords (api/admin_audit.py). Written in the same transaction as the
-- mutation so the trail can't drift from the data.
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id             SERIAL PRIMARY KEY,
    admin_user_id  INTEGER NOT NULL REFERENCES users(id),
    action         TEXT NOT NULL,          -- e.g. 'user.update', 'account.plan_set'
    target_type    TEXT,                   -- 'user' | 'account'
    target_id      TEXT,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log(created_at DESC);
