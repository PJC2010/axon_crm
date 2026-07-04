-- 050_geo_clusters.sql — Juncto geo layer, Phase 2 (clustering + heatmap data).
--
-- Customer clusters (nightly DBSCAN) and their hulls, for the "prospect this
-- area" flow (Phase 2 prospecting) and the cluster overlay on the map. Adapted to
-- this repo like migration 049: tenant key is account_id (INT), no PostGIS — the
-- hull is stored as GeoJSON in JSONB and DBSCAN runs in Python
-- (pipeline/geo_clustering.py). docs/geo_scoring.md documents the
-- ST_ClusterDBSCAN + geometry(Polygon,4326) upgrade path.
--
-- H3 heatmap aggregation reuses properties.h3_r8 (added in 049); it is populated
-- by the nightly job through the optional `h3` package. lead_geo_scores.cluster_id
-- (also added in 049) records each lead's cluster membership.

CREATE TABLE IF NOT EXISTS customer_clusters (
    id             SERIAL PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    cluster_label  INTEGER NOT NULL,          -- 0-based, unique within an account run
    hull           JSONB,                     -- GeoJSON Polygon (NULL for <3-point clusters)
    centroid_lat   NUMERIC,
    centroid_lng   NUMERIC,
    customer_count INTEGER NOT NULL DEFAULT 0,
    computed_at    TIMESTAMPTZ DEFAULT NOW()
);
-- One row per (account, label) per run; the store rewrites an account's clusters
-- as a set (delete-then-insert), so this also guards against duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_clusters_account_label
    ON customer_clusters (account_id, cluster_label);
CREATE INDEX IF NOT EXISTS idx_customer_clusters_account
    ON customer_clusters (account_id);

-- Heatmap aggregation and cluster-membership lookups hit these hot paths.
CREATE INDEX IF NOT EXISTS idx_properties_h3_r8
    ON properties (account_id, h3_r8) WHERE h3_r8 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lead_geo_scores_cluster
    ON lead_geo_scores (account_id, cluster_id) WHERE cluster_id IS NOT NULL;
