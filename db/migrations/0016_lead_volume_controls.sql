-- Lead-volume controls: pre-enrichment Top-N cap + radius-from-address narrowing.
--
-- `enrichment_selected` is set by the new selection step (pipeline/select.py),
-- which runs after the FREE steps (seed/census/geocode/HCAD) and before any PAID
-- enrichment. NULL  = the row never went through a capped/radius selection, so it
-- is enriched as before (legacy + uncapped runs are unaffected). TRUE = picked
-- for paid enrichment. FALSE = excluded by the cap or fell outside the radius.
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS enrichment_selected BOOLEAN;

-- Per-run / per-schedule volume controls. All optional; NULL = old behavior
-- (no cap, no radius → enrich the whole ZIP).
ALTER TABLE pipeline_runs
    ADD COLUMN IF NOT EXISTS top_n          INTEGER,
    ADD COLUMN IF NOT EXISTS center_address TEXT,
    ADD COLUMN IF NOT EXISTS radius_mi      DOUBLE PRECISION;

ALTER TABLE pipeline_schedules
    ADD COLUMN IF NOT EXISTS top_n          INTEGER,
    ADD COLUMN IF NOT EXISTS center_address TEXT,
    ADD COLUMN IF NOT EXISTS radius_mi      DOUBLE PRECISION;
