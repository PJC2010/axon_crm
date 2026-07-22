-- Migration 028: household demographics / life-events columns
-- Stores owner-level demographic data from a pluggable paid provider (e.g. Versium).
-- Used as model features for conversion prediction; not wired into the rule-based scorer.

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS owner_age                   INT,
    ADD COLUMN IF NOT EXISTS length_of_residence_years   INT,
    ADD COLUMN IF NOT EXISTS est_household_income        INT,
    ADD COLUMN IF NOT EXISTS life_stage                  TEXT;
