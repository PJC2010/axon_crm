-- Read-only post-deploy verification for the county-wide parcel cache
-- (migration 0070 + tools/load_parcel_centroids.py + parcels.fill_coords_from_centroids).
--
-- Nothing here writes. Safe to run against production.
--
--   psql "$DATABASE_URL" -f tools/verify_parcel_cache.sql
--
-- or paste the whole file into Render's psql shell (Dashboard → your Postgres →
-- "Connect" → PSQL Command, or the web shell). Every result set leads with a
-- `check` label column so the output is readable pasted back into a chat.

\pset pager off

-- 1 ── Did migration 0070 actually apply on this database?
--      Expect 0070_hcad_parcel_centroids.sql in the list.
SELECT 'migrations_applied' AS check_name, filename, applied_at
FROM schema_migrations
ORDER BY filename DESC
LIMIT 6;

-- 2 ── Is the centroid mirror loaded, and is it sane?
--      Expect ~1.53M rows. lat ~29.5–30.2, lon ~ -94.8 to -96.0 (Harris County).
--      A row count of 0 means migration ran but the loader never did.
--      Coordinates outside those bands would mean the outSR=4326 reprojection
--      was skipped (the CHECK constraints should have blocked that outright).
SELECT 'centroid_mirror'          AS check_name,
       COUNT(*)                   AS rows,
       ROUND(MIN(latitude)::numeric,  4) AS lat_min,
       ROUND(MAX(latitude)::numeric,  4) AS lat_max,
       ROUND(MIN(longitude)::numeric, 4) AS lon_min,
       ROUND(MAX(longitude)::numeric, 4) AS lon_max,
       MIN(loaded_at)             AS loaded_at
FROM hcad_parcel_centroids;

-- 3 ── Shared cache coverage: how much of `parcels` is geocoded, and by what.
--      'hcad_centroid' rows are the free fills this commit introduced.
--      Seeing 'google' or another paid source growing after this deploy would
--      mean the free pass is being bypassed.
SELECT 'parcels_by_geocode_source' AS check_name,
       COALESCE(geocode_source, '(none — ungeocoded)') AS geocode_source,
       COUNT(*) AS parcels
FROM parcels
GROUP BY 1, 2
ORDER BY parcels DESC;

-- 4 ── Join health: of the parcels still missing coordinates, how many COULD be
--      filled from the mirror right now? A large `fillable` number means the
--      centroid pass simply has not run for those ZIPs yet (expected — it runs
--      per-ZIP inside a seed). A large `no_apn_match` alongside a loaded mirror
--      is the real failure signal: the two normalized APN forms disagree.
SELECT 'ungeocoded_join_health' AS check_name,
       COUNT(*)                                                  AS ungeocoded,
       COUNT(*) FILTER (WHERE p.parcel_apn IS NULL)               AS no_apn_on_parcel,
       COUNT(*) FILTER (WHERE c.acct IS NOT NULL)                 AS fillable_from_mirror,
       COUNT(*) FILTER (WHERE p.parcel_apn IS NOT NULL
                          AND c.acct IS NULL)                     AS no_apn_match
FROM parcels p
LEFT JOIN hcad_parcel_centroids c ON c.acct = p.parcel_apn
WHERE p.latitude IS NULL;

-- 5 ── Per-ZIP detail for the ZIPs you have actually cached, newest first.
--      This is the one to eyeball after running a seed: `centroid_filled`
--      should account for most of `geocoded` on a freshly built ZIP.
SELECT 'per_zip' AS check_name,
       zip,
       COUNT(*)                                                        AS parcels,
       COUNT(latitude)                                                 AS geocoded,
       COUNT(*) FILTER (WHERE geocode_source = 'hcad_centroid')        AS centroid_filled,
       ROUND(100.0 * COUNT(latitude) / NULLIF(COUNT(*), 0), 1)         AS pct_geocoded,
       MAX(enriched_at)                                                AS last_enriched
FROM parcels
GROUP BY 1, 2
ORDER BY last_enriched DESC NULLS LAST
LIMIT 20;
