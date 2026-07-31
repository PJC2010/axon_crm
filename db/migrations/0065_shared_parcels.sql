-- Shared parcel cache.
--
-- `properties` is per-tenant: uniqueness is (account_id, address, zip), so every
-- account gets its own physical copy of a parcel and re-runs the whole
-- enrichment pipeline for a ZIP another account may already have enriched. On
-- ZIP 77449 (41,334 parcels) the seed step alone measured 8m58s, spent hauling
-- rows out of hcad_properties into Python and writing them back into the same
-- database.
--
-- `parcels` holds the tenant-independent facts about a real-world property —
-- assessor data, coordinates, storm history, neighborhood — once, shared by
-- every account, exactly like the hcad_* reference tables already are. Seeding a
-- ZIP becomes INSERT ... SELECT inside the database.
--
-- Deliberately NOT stored here: anything a tenant paid for or owns. Skip-traced
-- contact details and the demographic append are per-account purchases (sharing
-- them across tenants would hand one account another's paid data, and the
-- providers' terms do not allow redistribution), and CRM state — status,
-- assignment, score, notes — is tenant opinion, not fact about the parcel.
-- Those all stay on `properties`.

-- ── Address normalization ────────────────────────────────────────────────────
-- One definition, in SQL, byte-compatible with pipeline/addr.py::normalize
-- (lowercase, drop punctuation entirely, collapse whitespace).
--
-- The hcad_store queries previously inlined a DIFFERENT rule — punctuation was
-- replaced with a SPACE and runs of whitespace were never collapsed — while
-- pipeline/hcad_enrichment.py looked those keys up using the Python normalizer.
-- The two disagree on any address containing punctuation or a double space
-- ("123 MAIN-ST" -> "123 main st" vs "123 mainst"), so those parcels silently
-- failed to match and were skipped by HCAD enrichment. Everything now calls this
-- one function. IMMUTABLE so it can back a generated column and an index.
CREATE OR REPLACE FUNCTION axon_normalize_address(addr TEXT)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT TRIM(REGEXP_REPLACE(
        REGEXP_REPLACE(LOWER(COALESCE(addr, '')), '[^a-z0-9 ]', '', 'g'),
        '\s+', ' ', 'g'
    ))
$$;


CREATE TABLE IF NOT EXISTS parcels (
    id                     BIGSERIAL PRIMARY KEY,

    -- Identity. address_norm is generated so it can never drift from `address`.
    address                TEXT NOT NULL,
    address_norm           TEXT GENERATED ALWAYS AS (axon_normalize_address(address)) STORED,
    zip                    TEXT NOT NULL,
    city                   TEXT,
    state                  TEXT,

    -- Geo
    latitude               DOUBLE PRECISION,
    longitude              DOUBLE PRECISION,
    geohash                TEXT,
    h3_r8                  TEXT,
    geocode_source         TEXT,
    geocode_confidence     DOUBLE PRECISION,

    -- Assessor / structure
    year_built             INTEGER,
    square_footage         INTEGER,
    lot_size               DOUBLE PRECISION,
    property_type          TEXT,
    garage_spaces          INTEGER,
    garage_type            TEXT,
    has_pool               BOOLEAN,
    has_cracked_slab       BOOLEAN,

    -- Valuation / ownership
    estimated_value        INTEGER,
    estimated_equity       INTEGER,
    last_sale_date         DATE,
    last_sale_price        INTEGER,
    owner_name             TEXT,
    owner_occupied         BOOLEAN,
    ownership_years        INTEGER,
    mailing_address        TEXT,

    -- Area context
    hcad_neighborhood_code TEXT,
    hcad_neighborhood_name TEXT,
    subdivision            TEXT,
    zip_median_income      INTEGER,
    permit_count_24mo      INTEGER,

    -- Storm history (NOAA — public)
    last_storm_date        DATE,
    last_storm_type        TEXT,
    hail_size_in           DOUBLE PRECISION,
    storm_count_24mo       INTEGER,

    -- Provenance: which source filled what, same convention as properties.
    enrichment_flags       JSONB NOT NULL DEFAULT '{}',
    enriched_at            TIMESTAMP,
    created_at             TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

-- The parcel identity, and the conflict target for the cache upserts.
CREATE UNIQUE INDEX IF NOT EXISTS parcels_addr_zip_key
    ON parcels (address_norm, zip);

-- Seeding a tenant reads a whole ZIP at once; this is that access path.
CREATE INDEX IF NOT EXISTS idx_parcels_zip ON parcels (zip);

-- Finds the backlog for the shared geocode pass.
CREATE INDEX IF NOT EXISTS idx_parcels_zip_ungeocoded
    ON parcels (zip) WHERE latitude IS NULL;

CREATE OR REPLACE TRIGGER trg_parcels_updated_at
    BEFORE UPDATE ON parcels
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- Link each tenant row back to the shared parcel. Nullable: leads created by
-- hand, by CSV import, or through the public intake form have no parcel behind
-- them, and must keep working exactly as they do now.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS parcel_id BIGINT REFERENCES parcels(id);
CREATE INDEX IF NOT EXISTS idx_properties_parcel ON properties (parcel_id);

-- The pipeline's dominant access pattern (every step filters on exactly this),
-- which until now had no supporting index — the closest was idx_zip_score on
-- (zip, lead_score).
CREATE INDEX IF NOT EXISTS idx_properties_acct_zip ON properties (account_id, zip);
