-- HCAD situs city, and repair of the mailing-city pollution.
--
-- real_acct.txt carries the parcel's own city in site_addr_2 (see
-- docs/hcad_real_property_mapping.md), but the DuckDB build dropped it, so
-- neither property_summary nor this mirror ever had a situs city. The seed
-- paths (pipeline/seed.py::_normalize_hcad and
-- pipeline/parcels.py::ensure_from_hcad) papered over the gap by writing the
-- OWNER'S mailing city (mail_city, migration 0020 — added for skip-trace and
-- direct mail) into properties.city / parcels.city. mail_city is a fact about
-- the owner, not the parcel: an absentee owner who gets mail in Lake Dallas
-- made a Houston lead (ZIP 77073) display as "LAKE DALLAS, TX", fed that city
-- to the Census geocoder (pipeline/geocode.py, pipeline/county_build.py), and
-- printed it on quote/invoice client-address prefills.
ALTER TABLE hcad_properties ADD COLUMN IF NOT EXISTS site_city TEXT;

-- Repair the polluted copies. Two facts bound the cohort precisely:
--
--   * When the owner LIVES at the parcel (owner_occupied), the mailing city IS
--     the situs city, so those rows are correct and keep their city.
--   * The seed wrote city and mailing_address from the same HCAD row, so a
--     mail-city-derived city always appears verbatim inside the row's own
--     mailing_address. A city a tenant typed in by hand does not (unless they
--     typed the owner's mailing city — equally untrustworthy), so tenant
--     edits survive.
--
-- Absentee-owner rows whose city matches their mailing address are therefore
-- unverifiable-at-best and wrong-at-worst. NULL is honest — every display
-- path joins address parts with filter(Boolean), so the card reads
-- "ADDRESS, TX" — and it heals: once site_city is loaded here (rebuild the
-- DuckDB with tools/build_hcad_duckdb.py, then tools/load_hcad_to_postgres.py
-- or per-ZIP re-upload), ensure_from_hcad's gap-fill writes the real situs
-- city into parcels on each ZIP's next seed, and seed_account/sync fan it out
-- to every tenant row left NULL here. RentCast lookups (reconcile.map_record,
-- city policy fill_only) are a second, independent healing path.
UPDATE properties p SET city = NULL
WHERE p.enrichment_flags->>'seed' = 'hcad'
  AND p.owner_occupied IS NOT TRUE
  AND p.city IS NOT NULL
  AND p.mailing_address IS NOT NULL
  AND POSITION(UPPER(p.city) IN UPPER(p.mailing_address)) > 0;

UPDATE parcels pc SET city = NULL
WHERE pc.enrichment_flags->>'seed' = 'hcad'
  AND pc.owner_occupied IS NOT TRUE
  AND pc.city IS NOT NULL
  AND pc.mailing_address IS NOT NULL
  AND POSITION(UPPER(pc.city) IN UPPER(pc.mailing_address)) > 0;
