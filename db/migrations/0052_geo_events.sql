-- 052_geo_events.sql — Juncto geo layer, Phase 4 (event layers).
--
-- Some demand is created by events that hit whole polygons at once: hail swaths
-- (roofing), new-construction phases (lawn/pest/pools), HOA enforcement sweeps,
-- heat waves (HVAC). A lead inside an active event polygon gets an additive geo
-- bonus, named in its component breakdown (Section 2.3 of the plan).
--
-- Adapted like the rest of the layer: tenant key is account_id (INT), no PostGIS
-- — the polygon is GeoJSON in JSONB and point-in-polygon runs in Python. MVP
-- ingestion is manual (an admin uploads a polygon via POST /geo/events);
-- NOAA/storm-data automation waits until a roofing tenant exists.

CREATE TABLE IF NOT EXISTS geo_events (
    id          SERIAL PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    event_type  TEXT NOT NULL,      -- 'hail_swath' | 'storm' | 'new_construction' | 'hoa_sweep' | 'heat_wave'
    name        TEXT,               -- human label, e.g. "May 12 hail — NW Houston"
    polygon     JSONB NOT NULL,     -- GeoJSON Polygon {"type":"Polygon","coordinates":[[[lng,lat],...]]}
    bonus       NUMERIC,            -- optional per-event override of the type default (config.GEO_EVENT_BONUS)
    starts_at   TIMESTAMPTZ,        -- NULL = open-ended (active from creation)
    ends_at     TIMESTAMPTZ,        -- NULL = open-ended (never expires)
    metadata    JSONB,              -- e.g. {"hail_size_in": 1.75, "source": "manual"}
    created_by  INTEGER REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- The active-events scan during scoring: an account's events whose window covers
-- "now" (NULL bounds are open on that side).
CREATE INDEX IF NOT EXISTS idx_geo_events_account_window
    ON geo_events (account_id, starts_at, ends_at);
