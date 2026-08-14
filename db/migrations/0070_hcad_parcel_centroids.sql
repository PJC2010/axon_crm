-- hcad_parcel_centroids
--
-- County-wide parcel centroids from Harris County's public ArcGIS parcels
-- layer (~1.53M features; see config.HCAD_PARCELS_ARCGIS_URL). The assessor
-- mirror (hcad_properties) carries no coordinates — this table is the free
-- geocoding source that fills that gap, once, for every tenant.
--
-- Shared/unscoped like every hcad_* table (0017): raw county reference data,
-- deliberately no account_id. Loaded by tools/load_parcel_centroids.py as an
-- atomic TRUNCATE + reload, so nothing else may write rows here (Census
-- fallback results go to `parcels`, not this mirror). No FK to
-- hcad_properties: the two loaders must be runnable in either order.
--
-- `acct` is stored in the SAME normalized form as parcels.parcel_apn — both
-- sides are produced by pipeline/parcel_id.py::sql_normalize_apn (alnum-only,
-- uppercased, leading zeros kept, all-zero dropped) — which is what lets
-- pipeline/parcels.py::fill_coords_from_centroids join on plain equality.
-- The PK is the only index the fill needs: it drives from
-- idx_parcels_zip_ungeocoded (0065) into this PK, per ZIP.
--
-- The CHECKs are an SR tripwire, not geography pedantry: the layer's native
-- spatial reference is Texas State Plane FEET (EPSG 2278), and a load that
-- forgot outSR=4326 — or swapped lat/lon — would otherwise silently poison
-- geocoding county-wide. Bounds are generous around Harris County
-- (~29.5–30.2 N, ~94.8–96.0 W) so every real parcel passes.

CREATE TABLE IF NOT EXISTS hcad_parcel_centroids (
    acct       TEXT PRIMARY KEY,
    latitude   DOUBLE PRECISION NOT NULL,
    longitude  DOUBLE PRECISION NOT NULL,
    source     TEXT NOT NULL DEFAULT 'hcad_arcgis',
    loaded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hcad_centroid_lat_sane CHECK (latitude  BETWEEN 25 AND 34),
    CONSTRAINT hcad_centroid_lon_sane CHECK (longitude BETWEEN -100 AND -90)
);
