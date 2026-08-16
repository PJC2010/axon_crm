-- Carry HCAD's state class (the county's own land-use classification) through
-- to the CRM, so a parcel can be told apart from a house.
--
-- Axon targets residential homeowners, but the free HCAD seed path takes a whole
-- ZIP off the county roll, and the county roll is every *parcel*: shopping
-- centres, churches, school-district land, warehouses and vacant lots included.
-- The RentCast seed path has always filtered on `propertyType`
-- (config.SEED_PROPERTY_TYPES), but that column is written ONLY by RentCast —
-- pipeline/parcels.py::ensure_from_hcad never sets it — so on an HCAD-seeded
-- account it is NULL on every row and there was nothing left to filter on. A
-- 147,089 sqft shopping mall seeded, scored B/62, and sat in the pipeline as a
-- live lead.
--
-- `real_acct.state_class` is the Texas Comptroller State Category Code and is
-- the authoritative answer: A* single-family, B* multi-family, C* vacant,
-- E* rural-with-improvement, F1/F2 commercial/industrial, J* utility,
-- L* commercial personal property, S* dealer inventory, X* totally exempt
-- (government, church, school). It was read into the DuckDB build all along —
-- tools/build_hcad_duckdb.py reads every column of real_acct.txt — and simply
-- never projected. This adds the column at each hop so it survives to
-- `properties`, where pipeline/residential.py uses it as its strongest signal.
--
-- Nullable and additive everywhere: existing rows keep NULL until the next HCAD
-- load, and pipeline/residential.py treats a NULL class as "no opinion" and
-- falls back to its address/size/owner heuristics. Nothing regresses in the
-- meantime.

-- The county mirror. Populated by tools/load_hcad_to_postgres.py and
-- POST /api/hcad/upload.
ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS state_class TEXT;

-- The shared parcel cache (migration 0065). A free, objective county fact about
-- the parcel, so it belongs in parcels.SHARED_COLS — it is not a tenant
-- purchase and not CRM opinion.
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS state_class TEXT;

-- The per-tenant row, so a lead can be filtered and explained without a join.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS state_class TEXT;

-- Why the system archived a lead, when it was not a person who did.
--
-- `archived_at` (migration 0013) is the right *effect* — it already suppresses a
-- row from the lead list, the map, geo scoring, ML training and the dialer
-- queue, which is exactly "stop showing it and stop spending on it" — but it
-- cannot say *why*, and "a rep archived this" and "the classifier flagged a
-- shopping mall" need telling apart: for undo, for reviewing a rule that turns
-- out to be wrong, and for keeping an automated verdict out of the manual
-- `lead_events` disqualify vocabulary, which is human judgment and feeds ML
-- labels.
--
-- Deliberately NOT `status`: that column is the Kanban sales stage, it is
-- user-editable with per-account custom stage sets, and every funnel metric
-- groups by it. A system verdict written there would be destroyed the moment a
-- rep changed the dropdown, and would corrupt the board counts on the way.
--
-- NULL means "not excluded by the system". Set to a pipeline/residential.py
-- reason key ('commercial_owner', 'oversized_structure', …); cleared on
-- unarchive.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS exclusion_reason TEXT;

-- No index on state_class, deliberately.
--
-- Every consumer wraps it — pipeline/residential.py emits
-- `LEFT(UPPER(TRIM(COALESCE(state_class, ''))), 1) IN ('F','J','L','S')` so that
-- one rule covers the whole prefix family. That expression is not sargable, so
-- a plain btree on the column cannot be used for it and would only add write
-- cost: `parcels` is county-sized and rewritten by every HCAD load. Add an
-- expression index matching the generated predicate if the audit ever shows up
-- in slow queries.
