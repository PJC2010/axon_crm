-- Per-field verification trail for property data.
--
-- The enrichment pipeline is built around "fill the NULLs cheaply": HCAD runs
-- free and first, RentCast is then asked only about the fields still missing,
-- and upsert_properties writes non-NULL only so nobody's work is clobbered.
-- That design answers "is this row populated?" but never "is what we stored
-- actually right?" — once a field has any value, no source ever looks at it
-- again.
--
-- This table is where that second question gets answered. A verification sweep
-- (pipeline/backfill.py) re-asks RentCast about a property and records what it
-- found per field: a gap it filled, or a value that disagrees with what we
-- already had. Disagreements are recorded rather than applied, because the
-- county appraisal district is the better record for structural facts and
-- estimated_value feeds lead scoring — an automatic overwrite would silently
-- move grades. The operator reads this table and decides.
--
-- One row per (property, field, source): the sweep upserts, so the table holds
-- the current state of each field rather than growing without bound. It is
-- account-scoped like every other CRM-owned table, and rows die with their
-- property.

CREATE TABLE IF NOT EXISTS property_field_audits (
    id           BIGSERIAL PRIMARY KEY,
    account_id   INT  NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    property_id  INT  NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    field        TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'rentcast',
    -- Values are text so one pair of columns holds a year, a price, and a
    -- garage type. This is a report, never an input to scoring.
    stored_value TEXT,
    remote_value TEXT,
    verdict      TEXT NOT NULL,          -- 'fill' | 'mismatch'
    resolution   TEXT NOT NULL,          -- 'filled' | 'refreshed' | 'kept'
    checked_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Upsert key: re-checking a field replaces its previous verdict.
CREATE UNIQUE INDEX IF NOT EXISTS idx_field_audits_unique
    ON property_field_audits (property_id, field, source);

-- The report query: this account's open disagreements, newest first.
CREATE INDEX IF NOT EXISTS idx_field_audits_account
    ON property_field_audits (account_id, verdict, checked_at DESC);
