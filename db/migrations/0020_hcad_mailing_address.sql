-- HCAD owner mailing address.
-- real_acct.txt carries the owner's mailing address (mail_addr_1/city/state/zip),
-- which is distinct from the parcel's site address. Storing it lets the pipeline
-- backfill properties.mailing_address (used for skip-trace and direct mail) and
-- improves owner-occupancy inference. These columns mirror the DuckDB
-- property_summary table built by tools/build_hcad_duckdb.py.

ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS mail_addr  TEXT;
ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS mail_city  TEXT;
ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS mail_state TEXT;
ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS mail_zip   TEXT;
