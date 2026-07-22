-- 053_hcad_site_zip5_index.sql — canonical 5-digit ZIP lookups on the HCAD mirror.
--
-- HCAD's site ZIP (real_acct.site_addr_3) is not guaranteed to be a clean 5-digit
-- code — many parcels carry a ZIP+4 ("77008-2317" / "770082317"). The pipeline
-- and the public ZIP-sample teaser therefore match on LEFT(site_zip, 5) so a
-- covered Harris County ZIP isn't reported as unsupported. The plain
-- site_zip index doesn't serve that predicate, so add a functional one to keep
-- coverage checks and per-ZIP seeding scans off a full table scan.

CREATE INDEX IF NOT EXISTS idx_hcad_properties_site_zip5
    ON hcad_properties (LEFT(site_zip, 5));
