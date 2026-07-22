-- Migration 027: storm event enrichment columns
-- Stores per-property storm/hail history from NOAA/IEM for scoring and timing signals.

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS last_storm_date       DATE,
    ADD COLUMN IF NOT EXISTS last_storm_type       TEXT,
    ADD COLUMN IF NOT EXISTS hail_size_in          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS storm_count_24mo      INT;
