-- Drop the properties indexes no query can reach.
--
-- properties carries ~30 indexes (297MB of index against 163MB of table on a
-- 219k-row database), and index maintenance measured as 94% of a bulk seed's
-- write cost — 47,531 rows inserted in 0.21s with no indexes vs 3.69s with all
-- of them. It is also why almost no UPDATE on the table is HOT. Every index
-- dropped here was shown UNREACHABLE from the query shapes in the codebase —
-- not merely unused-so-far — so no plan can regress:
--
-- * The five 0038 trigram indexes (idx_props_trgm_name/_owner/_address/_email/
--   _phone, 73MB together, ~32% of insert index maintenance) were built for
--   /api/leads/search, but that query ORs in two arms Postgres cannot serve
--   with any of them (account_number ILIKE has no trigram index, and the phone
--   arm wraps contact_phone in COALESCE while the index expression does not).
--   A multi-arm OR is only index-served when EVERY arm is indexable (BitmapOr),
--   so the planner provably never touches them: EXPLAIN with enable_seqscan=off
--   still walks an account-scoped index and filters. Search behavior is
--   IDENTICAL before and after this migration. If per-account fuzzy search
--   ever needs indexes, rebuild them alongside a query rewritten so each arm
--   is indexable (per-arm UNION, COALESCE-matched expressions, and a trigram
--   index on account_number) — dropping them costs nothing until then.
--
-- * idx_properties_subdivision (0051) indexes a column that is only ever
--   written and projected — never filtered, grouped, or sorted on anywhere in
--   api/, pipeline/, scripts/, tools/. idx_hcad_nbhd_code (0026) indexes a
--   column that IS grouped on (pipeline/neighborhood.py's nbhd_stats /
--   PARTITION BY), but only over CTE output already scanned via account/zip
--   predicates — a bare-column btree can never serve a GROUP BY on a filtered
--   intermediate result, so no plan can pick it.
--
-- Deliberately KEPT, with reasons, so nobody "finishes the job" blindly:
--   idx_zip_score            — tools/visualize_pipeline.py + audit tooling
--                              filter zip without account_id.
--   idx_geo                  — the map viewport bbox can win on a zoomed-in
--                              view of a large account.
--   idx_vertical             — marginal, but (vertical, grade) may beat the
--                              account index on rare-vertical filters.
--   idx_properties_assigned  — awaiting a filter-by-rep feature; archive()'s
--                              unworked-only path matches its columns.
--   idx_properties_parcel    — FK-support on properties.parcel_id; a future
--                              parcels delete would seq-scan properties per
--                              row without it.
--   idx_properties_acct_zip  — prefix-duplicates idx_props_acct_zip_score,
--                              but is 8x smaller (no lead_score churn) and is
--                              the pipeline's hottest access path.
--
-- pg_trgm (the extension) stays: nothing else depends on it today, but
-- extensions are cheap to keep and expensive to chase across environments.

-- DROP INDEX takes ACCESS EXCLUSIVE on properties — instant once granted, but
-- the REQUEST queues behind any in-flight statement, and every new properties
-- query then queues behind the request. Fail fast instead: migrate.py re-runs
-- are the retry path and every DROP is IF EXISTS. Transaction-scoped.
SET LOCAL lock_timeout = '10s';

DROP INDEX IF EXISTS idx_props_trgm_name;
DROP INDEX IF EXISTS idx_props_trgm_owner;
DROP INDEX IF EXISTS idx_props_trgm_address;
DROP INDEX IF EXISTS idx_props_trgm_email;
DROP INDEX IF EXISTS idx_props_trgm_phone;
DROP INDEX IF EXISTS idx_hcad_nbhd_code;
DROP INDEX IF EXISTS idx_properties_subdivision;
