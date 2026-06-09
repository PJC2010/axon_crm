-- Org/tenant isolation.
--
-- Leads (properties) and all CRM data were global: every user saw every other
-- user's leads because nothing scoped queries by user or org. This migration
-- introduces an `accounts` (organization) table, attaches `account_id` to every
-- CRM-owned table, and backfills all existing rows into a single "Default Org"
-- so current data keeps working. Raw county reference tables (hcad_*) stay shared.
--
-- After this migration the property uniqueness key becomes
-- (account_id, address, zip) so each org gets its own copy of a property when it
-- runs the enrichment pipeline, and pipeline stage keys become unique per org.

-- ── Organizations ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Default org for all pre-existing users and data. Captured as id = 1.
INSERT INTO accounts (name) VALUES ('Default Org')
ON CONFLICT DO NOTHING;

-- ── users.account_id ────────────────────────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE users SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE users ALTER COLUMN account_id SET NOT NULL;

-- ── account_id on every CRM-owned table ──────────────────────────────────────────
-- properties
ALTER TABLE properties ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE properties SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE properties ALTER COLUMN account_id SET NOT NULL;

-- tasks
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE tasks SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE tasks ALTER COLUMN account_id SET NOT NULL;

-- expenses
ALTER TABLE expenses ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE expenses SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE expenses ALTER COLUMN account_id SET NOT NULL;

-- invoices (invoice_number stays globally unique; line_items/payments inherit via FK)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE invoices SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE invoices ALTER COLUMN account_id SET NOT NULL;

-- workflow_rules
ALTER TABLE workflow_rules ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE workflow_rules SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE workflow_rules ALTER COLUMN account_id SET NOT NULL;

-- pipeline_stages
ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE pipeline_stages SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE pipeline_stages ALTER COLUMN account_id SET NOT NULL;

-- pipeline_schedules
ALTER TABLE pipeline_schedules ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE pipeline_schedules SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE pipeline_schedules ALTER COLUMN account_id SET NOT NULL;

-- pipeline_runs
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id);
UPDATE pipeline_runs SET account_id = 1 WHERE account_id IS NULL;
ALTER TABLE pipeline_runs ALTER COLUMN account_id SET NOT NULL;

-- ── Uniqueness swaps ─────────────────────────────────────────────────────────────
-- properties: (address, zip) → (account_id, address, zip) so each org keeps its
-- own copy of a property. Drops the auto-named constraint from 0000_properties.sql.
ALTER TABLE properties DROP CONSTRAINT IF EXISTS properties_address_zip_key;
ALTER TABLE properties ADD CONSTRAINT properties_acct_address_zip_key
    UNIQUE (account_id, address, zip);

-- pipeline_stages: stage key was globally unique; make it per-org.
ALTER TABLE pipeline_stages DROP CONSTRAINT IF EXISTS pipeline_stages_key_key;
ALTER TABLE pipeline_stages ADD CONSTRAINT pipeline_stages_acct_key_key
    UNIQUE (account_id, key);

-- ── Indexes for account-scoped hot paths ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_props_acct_zip_score
    ON properties(account_id, zip, lead_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tasks_account ON tasks(account_id);
CREATE INDEX IF NOT EXISTS idx_runs_account  ON pipeline_runs(account_id);
CREATE INDEX IF NOT EXISTS idx_invoices_account ON invoices(account_id);
CREATE INDEX IF NOT EXISTS idx_expenses_account ON expenses(account_id);
