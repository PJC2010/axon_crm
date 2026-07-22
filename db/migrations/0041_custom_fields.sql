-- Account-defined custom fields on records (leads).
--
-- Phase 3 of the generalization work: let any business model its own lead data
-- without the property-specific schema. Rather than replace the `properties`
-- record store (which the whole app + pipeline depend on), this adds a generic,
-- additive layer on top:
--   * record_field_defs — per-account custom field definitions (the "schema"),
--   * properties.custom_fields — a JSONB bag of values keyed by field def `key`.
-- Home-services accounts that define no custom fields are completely unaffected.

CREATE TABLE IF NOT EXISTS record_field_defs (
    id          SERIAL PRIMARY KEY,
    account_id  INT NOT NULL REFERENCES accounts(id),
    key         TEXT NOT NULL,                 -- stable slug used as the JSONB key
    label       TEXT NOT NULL,                 -- human label shown in the UI
    field_type  TEXT NOT NULL DEFAULT 'text',  -- text | number | date | boolean | select
    options     JSONB NOT NULL DEFAULT '[]',   -- choices for field_type = 'select'
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (account_id, key)
);

CREATE INDEX IF NOT EXISTS idx_record_field_defs_account ON record_field_defs(account_id);

-- Values live with the record. JSONB so the set of fields is per-account dynamic.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS custom_fields JSONB NOT NULL DEFAULT '{}';
