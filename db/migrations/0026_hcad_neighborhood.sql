-- HCAD neighborhood code and subdivision name on properties.
--
-- Sourced from real_acct.txt (Neighborhood_Code / Neighborhood_Grp) joined to
-- real_neighborhood_code.txt during the DuckDB build step and backfilled by
-- pipeline/hcad_enrichment.py. Used as a middle fallback tier in
-- pipeline/neighborhood.py (cell → hcad_neighborhood → zip).
ALTER TABLE properties ADD COLUMN IF NOT EXISTS hcad_neighborhood_code TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS hcad_neighborhood_name TEXT;

-- Powers the hcad_neighborhood fallback in neighborhood.py
CREATE INDEX IF NOT EXISTS idx_hcad_nbhd_code
  ON properties (account_id, hcad_neighborhood_code);

-- Mirror columns on hcad_properties so the Postgres fallback path can carry
-- neighborhood data if that table is ever populated from the DuckDB export.
ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS neighborhood_code TEXT;
ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS neighborhood_name TEXT;
