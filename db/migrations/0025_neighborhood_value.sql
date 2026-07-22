-- Neighborhood-relative value benchmark.
--
-- ZIP is too coarse to judge a home's value — prices vary widely within one ZIP.
-- These columns position each home against its immediate neighborhood (geohash-6
-- cell, ~1.2km, the same "block" unit used by api/neighbors.py), using
-- value-per-sqft. Populated account-wide by pipeline/neighborhood.py
-- (recompute_neighborhood_values); read by the scorer's neighborhood signal and
-- by the leads list filters/sort.
--
--   neighborhood_value_ratio  — home value/sqft ÷ neighborhood median (1.0 = at median)
--   neighborhood_value_pctile — percent_rank 0–1 within the neighborhood (0.8 = top 20%)
--   neighborhood_value_basis  — 'cell' (enough neighbors) | 'zip' (sparse fallback) | NULL
ALTER TABLE properties ADD COLUMN IF NOT EXISTS neighborhood_value_ratio  DOUBLE PRECISION;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS neighborhood_value_pctile DOUBLE PRECISION;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS neighborhood_value_basis  TEXT;

-- Expression index on the geohash-6 cell: powers the recompute's grouping, the
-- /neighborhoods endpoint, and the neighborhood filter.
CREATE INDEX IF NOT EXISTS idx_geohash6
  ON properties (account_id, LEFT(geohash, 6));

-- Powers "top value % in neighborhood" filtering and sorting.
CREATE INDEX IF NOT EXISTS idx_neighborhood_pctile
  ON properties (account_id, neighborhood_value_pctile DESC NULLS LAST);
