-- Per-account pricing plans and feature-module entitlements.
--
-- Until now every feature was always-on for every account. This migration adds an
-- `account_plans` table that records which optional modules an account may use, so
-- pricing tiers can bundle features (map, "pipeline refresh"/prospecting, invoicing,
-- etc.) and the API/UI can gate them per account.
--
-- `core` features (leads, Kanban board view, tasks, notes, history, export) are
-- always enabled and are NOT represented as a flag here — only optional, gateable
-- modules live in `modules`. The set of valid module keys is the single source of
-- truth in api/entitlements.py (MODULE_KEYS); this migration just seeds storage.
--
-- SAFETY: gating must be additive. Every existing account is backfilled to the full
-- 'pro' module set so no current user loses access. New keys added to the catalog
-- later default to enabled via get_account_modules() unless a plan turns them off.

CREATE TABLE IF NOT EXISTS account_plans (
    account_id  INT PRIMARY KEY REFERENCES accounts(id),
    plan_name   TEXT NOT NULL DEFAULT 'pro',
    modules     JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- Backfill: every pre-existing account gets the full module set.
INSERT INTO account_plans (account_id, plan_name, modules)
SELECT id, 'pro', '{
    "prospecting": true,
    "map": true,
    "invoicing": true,
    "bookkeeping": true,
    "quotes": true,
    "marketing": true,
    "automation": true
}'::jsonb
FROM accounts
ON CONFLICT (account_id) DO NOTHING;
