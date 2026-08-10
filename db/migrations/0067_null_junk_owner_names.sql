-- Null out assessor placeholder owner names so the paid gap-fill can run.
--
-- County rolls stamp parcels whose owner is unrecorded or masked with
-- placeholders — HCAD's is "CURRENT OWNER" (423 of ~20k parcels in ZIP 77396
-- alone). A stored placeholder is worse than a NULL: owner_name is one of
-- SOURCE_FIELDS["rentcast"], so only a NULL queues the row for the RentCast
-- fill, and the skip-trace step would pay to look up "Current Owner" as if it
-- were a person. Ingestion now nulls these (pipeline/owner.py, applied in
-- hcad_store / parcels.ensure_from_hcad / seed / reconcile / prospecting);
-- this migration cleans what earlier runs already stored.
--
-- The list below is JUNK_OWNER_NAMES from pipeline/owner.py, normalized by
-- axon_normalize_address() (migration 0065) — the same lowercase/strip/collapse
-- rule pipeline/addr.py::normalize implements, so SQL and Python agree on what
-- a name normalizes to. Whole-string matches only: "OWENS CURRENT" or
-- "OWNER FINANCE LLC" must survive.
--
-- hcad_properties is deliberately untouched: it is the raw shared county
-- mirror, and every path reading owner_name out of it now applies the guard.

-- Tenant rows. Also drop the rentcast_checked stamp on rows we null, so they
-- are eligible for the next fill run immediately instead of waiting out
-- PROPERTY_RECHECK_DAYS with a gap this cleanup just created.
UPDATE properties
SET owner_name = NULL,
    enrichment_flags = COALESCE(enrichment_flags, '{}'::jsonb) - 'rentcast_checked'
WHERE owner_name IS NOT NULL
  AND axon_normalize_address(owner_name) IN (
    'confidential', 'current occupant', 'current owner',
    'current property owner', 'current resident', 'home owner', 'homeowner',
    'na', 'name withheld', 'none', 'not available', 'null', 'occupant',
    'owner', 'owner current', 'owner of record', 'owner unknown',
    'property owner', 'resident', 'taxpayer', 'unknown', 'unknown owner',
    'withheld'
  );

-- contact_name falls back to owner_name when a skip-trace answers without a
-- name (pipeline/contact.py), so the same placeholders leaked there too.
UPDATE properties
SET contact_name = NULL
WHERE contact_name IS NOT NULL
  AND axon_normalize_address(contact_name) IN (
    'confidential', 'current occupant', 'current owner',
    'current property owner', 'current resident', 'home owner', 'homeowner',
    'na', 'name withheld', 'none', 'not available', 'null', 'occupant',
    'owner', 'owner current', 'owner of record', 'owner unknown',
    'property owner', 'resident', 'taxpayer', 'unknown', 'unknown owner',
    'withheld'
  );

-- Shared parcel cache — same rule; promote() may have shared a tenant's junk.
UPDATE parcels
SET owner_name = NULL
WHERE owner_name IS NOT NULL
  AND axon_normalize_address(owner_name) IN (
    'confidential', 'current occupant', 'current owner',
    'current property owner', 'current resident', 'home owner', 'homeowner',
    'na', 'name withheld', 'none', 'not available', 'null', 'occupant',
    'owner', 'owner current', 'owner of record', 'owner unknown',
    'property owner', 'resident', 'taxpayer', 'unknown', 'unknown owner',
    'withheld'
  );
