-- scoring_quota — meter scored-lead reveals per month (positioning plan Phase 3).
--
-- Scoring moves in front of every tier: starter/growth get the prospecting
-- module with a monthly allowance of *revealed* (unmasked) scored leads instead
-- of not having the module at all. Plan defaults live in code
-- (api/entitlements.py PLAN_SCORING_LIMITS: starter 25, growth 100, pro
-- unlimited); this column is the per-account override. NULL = use the plan
-- default (pro's default is unlimited).
ALTER TABLE account_plans ADD COLUMN IF NOT EXISTS scoring_monthly_limit INT;

-- Reveal ledger: which scored leads an account has unmasked, per calendar
-- month. A scored, not-yet-worked lead is "revealed" the first time it renders
-- unmasked in a month; once the month's allowance is spent, further scored
-- leads render masked (api/scoring_quota.py) — the same address-masking
-- contract as the public ZIP-sample teaser. Deliberately separate from
-- lead_events so the ML training log stays pure outcome signal.
CREATE TABLE IF NOT EXISTS scoring_reveals (
    account_id  INT  NOT NULL REFERENCES accounts(id)   ON DELETE CASCADE,
    property_id INT  NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    month       DATE NOT NULL,          -- first day of the calendar month
    revealed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, month, property_id)
);
