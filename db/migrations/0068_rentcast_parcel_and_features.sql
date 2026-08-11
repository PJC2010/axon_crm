-- Migration 068: parcel identity + RentCast ride-along feature columns.
--
-- parcel_apn is the county assessor's parcel number — HCAD calls it `acct`,
-- RentCast reports it as `assessorID`. It is the one identifier that *is* the
-- property rather than a description of it, so it becomes the precision check
-- for cross-source matching: the address echo check (pipeline/addr.py
-- same_address) is deliberately lenient, while two records that disagree on the
-- parcel number are talking about different properties no matter how similar
-- their address strings look. Comparison happens only in Python
-- (pipeline/parcel_id.py::same_parcel) — nothing joins on this column — so the
-- stored form is display-faithful (leading zeros kept), just cleaned of
-- punctuation.
--
-- The feature columns are free ride-alongs on RentCast property lookups that
-- were already being paid for (`features.roofType` etc. in the response we
-- previously discarded). None of them triggers a paid lookup on its own — they
-- are deliberately NOT in config.SOURCE_FIELDS — they fill opportunistically,
-- the same way `subdivision` always has. roof_type feeds the roofing vertical,
-- foundation_type complements has_cracked_slab, heating/cooling ready an HVAC
-- vertical, and owner_type ("Individual" | "Organization") is an absentee/
-- investor signal and a future skip-trace cost gate (tracing an LLC is wasted
-- spend).
--
-- Columns exist on BOTH properties and parcels: they are free, objective facts
-- about the parcel, so they qualify for the shared cache (parcels.SHARED_COLS)
-- and compound across tenants like the rest of the assessor data.

ALTER TABLE properties ADD COLUMN IF NOT EXISTS parcel_apn      TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS roof_type       TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS foundation_type TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS heating_type    TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS cooling_type    TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS owner_type      TEXT;

ALTER TABLE parcels ADD COLUMN IF NOT EXISTS parcel_apn      TEXT;
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS roof_type       TEXT;
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS foundation_type TEXT;
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS heating_type    TEXT;
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS cooling_type    TEXT;
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS owner_type      TEXT;
