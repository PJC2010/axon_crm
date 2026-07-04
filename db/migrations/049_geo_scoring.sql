-- 049_geo_scoring.sql — Juncto geospatial scoring layer, Phase 1.
--
-- Adds proximity + density + territory scoring on top of the existing property
-- score (see docs/geo_scoring.md and juncto-geospatial-layer-plan.md). Adapted to
-- this repo's real schema:
--   * "leads" ARE the `properties` table (INT ids), tenant key is `account_id`
--     (INT) — not the plan's uuid `leads`/`customers`/`jobs` tables.
--   * "customers" are properties in a won/converted status (WON_STATUSES in
--     pipeline/ml/labels.py). There is no separate customers table.
--   * NO PostGIS. `properties.latitude/longitude` already exist; MVP distance is
--     haversine × a road-circuity factor (Section 4 of the plan), computed in
--     Python. Polygons are stored as GeoJSON in JSONB. This keeps `db/migrate.py`
--     runnable on any Postgres (Render, CI) with no PostGIS extension. The upgrade
--     path to geometry(Point/Polygon,4326) + GIST + ST_ClusterDBSCAN is documented
--     in docs/geo_scoring.md and is a drop-in for Phase 2/3.

-- ── Geo provenance on properties ──────────────────────────────────────────────
-- latitude/longitude/geohash already exist (see db/schema.sql + geocode step).
-- Track WHERE coordinates came from and, for H3 heatmaps in Phase 2, the hex id.
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS geocode_source     TEXT,      -- 'rentcast' | 'census' | 'google'
    ADD COLUMN IF NOT EXISTS geocode_confidence NUMERIC,   -- 0–1, provider-reported
    ADD COLUMN IF NOT EXISTS h3_r8              TEXT;       -- resolution-8 hex (Phase 2)


-- ── Per-vertical geo configuration (Section 3 matrix) ─────────────────────────
-- Platform defaults have account_id NULL; a tenant override is a row with the
-- account's id. All four mechanisms run for every vertical — only the weights
-- differ. prospect_filter_preset holds the RentCast radius-query params used by
-- the Phase 2 prospecting flow.
CREATE TABLE IF NOT EXISTS vertical_geo_config (
    id                     SERIAL PRIMARY KEY,
    vertical               TEXT NOT NULL,
    account_id             INTEGER REFERENCES accounts(id),   -- NULL = platform default
    route_weight           NUMERIC NOT NULL,
    neighbor_weight        NUMERIC NOT NULL,
    geo_blend              NUMERIC NOT NULL DEFAULT 0.35,
    visits_per_year        INTEGER,
    event_trigger_types    TEXT[],
    prospect_filter_preset JSONB,
    created_at             TIMESTAMPTZ DEFAULT NOW(),
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);
-- One platform default per vertical; one override per (vertical, account). Partial
-- indexes because a plain UNIQUE(vertical, account_id) treats NULLs as distinct,
-- which would allow duplicate platform defaults.
CREATE UNIQUE INDEX IF NOT EXISTS uq_vgc_default
    ON vertical_geo_config (vertical) WHERE account_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_vgc_override
    ON vertical_geo_config (vertical, account_id) WHERE account_id IS NOT NULL;

CREATE TRIGGER vertical_geo_config_updated_at
    BEFORE UPDATE ON vertical_geo_config
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ── Computed geo scores, one row per scored lead ──────────────────────────────
-- components JSONB stores the breakdown ({proximity, density, neighbor,
-- territory_gate, ...}) so the UI can say WHY. final_score is the blend of the
-- property score and geo_score and is what the leads list sorts on.
CREATE TABLE IF NOT EXISTS lead_geo_scores (
    property_id            INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    account_id             INTEGER NOT NULL REFERENCES accounts(id),
    geo_score              NUMERIC NOT NULL,
    final_score            NUMERIC,
    components             JSONB NOT NULL,
    nearest_customer_m     NUMERIC,
    customers_within_1600m INTEGER,
    cluster_id             INTEGER,                 -- populated in Phase 2 (DBSCAN)
    scored_at              TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lead_geo_scores_account
    ON lead_geo_scores (account_id);
CREATE INDEX IF NOT EXISTS idx_lead_geo_scores_final
    ON lead_geo_scores (account_id, final_score DESC NULLS LAST);


-- ── Service areas (territory gate) ────────────────────────────────────────────
-- One area per account at Phase 1 (no branch concept in the schema — see the
-- Section 11 answers in docs/geo_scoring.md). Polygon is GeoJSON in JSONB:
-- {"type":"Polygon","coordinates":[[[lng,lat],...]]}. 'derived' areas are the
-- customer convex hull (a 2km buffer is applied at membership time); 'user_drawn'
-- areas are matched strictly.
CREATE TABLE IF NOT EXISTS service_areas (
    id          SERIAL PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    polygon     JSONB NOT NULL,
    source      TEXT NOT NULL DEFAULT 'derived',   -- 'derived' | 'user_drawn'
    computed_at TIMESTAMPTZ DEFAULT NOW()
);
-- At most one active area per account for now; enforced by the store layer's
-- delete-then-insert, indexed for the per-account lookup.
CREATE INDEX IF NOT EXISTS idx_service_areas_account ON service_areas (account_id);


-- ── Asynchronous geocoding queue ──────────────────────────────────────────────
-- Never geocode in a request path. Tenant-entered customer addresses missing
-- coordinates are enqueued here and drained by a background job through the
-- provider interface (Census by default). RentCast leads arrive pre-geocoded and
-- never enter this queue.
CREATE TABLE IF NOT EXISTS geocode_queue (
    id           SERIAL PRIMARY KEY,
    property_id  INTEGER NOT NULL UNIQUE REFERENCES properties(id) ON DELETE CASCADE,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    status       TEXT NOT NULL DEFAULT 'queued',   -- queued | done | failed
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    queued_at    TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_geocode_queue_status ON geocode_queue (status, queued_at);


-- ── Seed the Section 3 vertical matrix as platform defaults ───────────────────
-- Weights are starting points for tuning. Recurring services lean on geo more
-- (geo_blend 0.35); one-time project work leans on the property score (0.25).
-- Verticals cover both the plan's canonical names and this repo's existing
-- config.VERTICAL_WEIGHTS keys, so geo scoring resolves for current leads; any
-- unlisted vertical falls back to config.GEO_DEFAULT_CONFIG in code.
INSERT INTO vertical_geo_config
    (vertical, account_id, route_weight, neighbor_weight, geo_blend, visits_per_year, event_trigger_types, prospect_filter_preset)
VALUES
    -- Recurring, route-dominant
    ('lawn_care',            NULL, 0.90, 0.50, 0.35, 37, ARRAY['hoa_violation','new_construction'], '{"propertyType":"Single Family","lotSize":"7000:15000"}'),
    ('pool_service',         NULL, 0.90, 0.30, 0.35, 46, ARRAY['pool_permit','new_construction'],    '{"propertyType":"Single Family"}'),
    ('pool_maintenance',     NULL, 0.90, 0.30, 0.35, 46, ARRAY['pool_permit','new_construction'],    '{"propertyType":"Single Family"}'),
    ('residential_cleaning', NULL, 0.80, 0.30, 0.35, 19, ARRAY['new_mover'],                          '{"propertyType":"Single Family"}'),
    ('pest_control',         NULL, 0.70, 0.20, 0.35,  8, ARRAY['new_construction','seasonal'],        '{"propertyType":"Single Family"}'),
    ('hvac',                 NULL, 0.40, 0.20, 0.35,  2, ARRAY['system_age','permit','heat_wave'],    '{"propertyType":"Single Family"}'),
    -- One-time / project, neighbor-dominant
    ('landscaping',          NULL, 0.30, 0.80, 0.25,  0, ARRAY['home_sale','permit'],                 '{"propertyType":"Single Family"}'),
    ('epoxy_coatings',       NULL, 0.20, 0.80, 0.25,  0, ARRAY['home_sale','garage_permit'],          '{"propertyType":"Single Family"}'),
    ('epoxy_flooring',       NULL, 0.20, 0.80, 0.25,  0, ARRAY['home_sale','garage_permit'],          '{"propertyType":"Single Family"}'),
    ('roofing',              NULL, 0.20, 0.90, 0.25,  0, ARRAY['hail_swath','storm','roof_age'],       '{"propertyType":"Single Family"}'),
    -- Additional repo verticals (sensible defaults; tunable later)
    ('solar',                NULL, 0.20, 0.60, 0.25,  0, ARRAY['home_sale','permit'],                 '{"propertyType":"Single Family"}'),
    ('fencing',              NULL, 0.30, 0.70, 0.25,  0, ARRAY['home_sale','storm'],                  '{"propertyType":"Single Family"}'),
    ('pressure_washing',     NULL, 0.40, 0.70, 0.30, 12, ARRAY['home_sale'],                          '{"propertyType":"Single Family"}')
ON CONFLICT DO NOTHING;
