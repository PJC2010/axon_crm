-- Migration 029: expanded Versium Demographic Append fields
-- Adds scoring-signal columns (wired into the scorer) and model-feature columns
-- (captured for a future conversion model, not yet scored).

-- Scoring signals
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS refi_date              DATE,
    ADD COLUMN IF NOT EXISTS home_improvement_flag  BOOLEAN,
    ADD COLUMN IF NOT EXISTS credit_rating          TEXT,
    ADD COLUMN IF NOT EXISTS has_children           BOOLEAN,
    ADD COLUMN IF NOT EXISTS gardening_flag         BOOLEAN;

-- Model features (not scored — future ML input vector)
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS age_range              TEXT,
    ADD COLUMN IF NOT EXISTS estimated_net_worth    INT,
    ADD COLUMN IF NOT EXISTS loan_to_value          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS marital_status         TEXT,
    ADD COLUMN IF NOT EXISTS occupation             TEXT,
    ADD COLUMN IF NOT EXISTS senior_in_household    BOOLEAN,
    ADD COLUMN IF NOT EXISTS pets_flag              BOOLEAN,
    ADD COLUMN IF NOT EXISTS decorating_flag        BOOLEAN,
    ADD COLUMN IF NOT EXISTS credit_lines_count     INT,
    ADD COLUMN IF NOT EXISTS mortgage_rate_type     TEXT;
