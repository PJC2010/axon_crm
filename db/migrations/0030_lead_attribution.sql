-- Migration 030: lead attribution — rep ownership + acquisition source.
-- Powers the performance analytics breakdown (win-rate / revenue by rep and by
-- source) and the per-lead assignee selector. Both are additive and nullable.

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS assigned_to INT REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS lead_source TEXT;

-- Backfill the source from the JSON the pipeline / importer already records, so
-- existing leads attribute correctly without a re-import.
UPDATE properties
   SET lead_source = enrichment_flags->>'source'
 WHERE lead_source IS NULL
   AND enrichment_flags ? 'source';

CREATE INDEX IF NOT EXISTS idx_properties_assigned ON properties(account_id, assigned_to);
CREATE INDEX IF NOT EXISTS idx_properties_source   ON properties(account_id, lead_source);
