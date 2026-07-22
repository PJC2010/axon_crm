-- 051_prospecting.sql — Juncto geo layer, Phase 2 (cluster-seeded prospecting).
--
-- Section 5 of the plan: pull pre-geocoded, pre-enriched prospects from RentCast
-- around a seed (cluster centroid, customer, or dropped pin), dedupe, ingest as
-- leads, and score. This migration adds the cost-control ledger and the free
-- `subdivision` cluster key. Adapted to this repo like 049/050: tenant key is
-- account_id (INT), no PostGIS — the pull center is stored as plain lat/lng.

-- Bonus cluster key (Section 5): RentCast carries a human-readable subdivision
-- that complements DBSCAN and maps onto the HOA/ARC angle. Persisted on ingest.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS subdivision TEXT;
CREATE INDEX IF NOT EXISTS idx_properties_subdivision
    ON properties (account_id, subdivision) WHERE subdivision IS NOT NULL;

-- Every prospect pull is logged, keyed by the H3 cell of its center, so a cell
-- pulled within the last 14 days can be skipped (cost control). api_requests
-- meters usage against the RentCast quota — requests, not records, are the
-- binding constraint (one request returns up to 500 records).
CREATE TABLE IF NOT EXISTS prospect_pulls (
    id               SERIAL PRIMARY KEY,
    account_id       INTEGER NOT NULL REFERENCES accounts(id),
    h3_r8            TEXT,
    center_lat       NUMERIC,
    center_lng       NUMERIC,
    radius_m         INTEGER,
    filters          JSONB,
    records_returned INTEGER NOT NULL DEFAULT 0,
    records_ingested INTEGER NOT NULL DEFAULT 0,
    api_requests     INTEGER NOT NULL DEFAULT 0,
    seed_type        TEXT,                      -- 'cluster' | 'customer' | 'point'
    pulled_by        INTEGER REFERENCES users(id),
    pulled_at        TIMESTAMPTZ DEFAULT NOW()
);
-- The skip-recent-cell check: newest pull for an account's H3 cell.
CREATE INDEX IF NOT EXISTS idx_prospect_pulls_cell
    ON prospect_pulls (account_id, h3_r8, pulled_at DESC);
