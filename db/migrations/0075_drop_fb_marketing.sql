-- Migration 075: remove the Facebook/Meta marketing component.
-- The Meta connections framework (032) and imported social data store (033)
-- are gone from the application — connectors, the /api/connections and
-- /api/insights routes, the `marketing` module, and the Meta Pixel/CAPI ad
-- tracking were all removed. Drop their tables; children first so no FK is
-- left dangling (social_* all reference connections). Indexes and the
-- connections_updated_at trigger drop with their tables; the shared
-- set_updated_at() function stays — other tables use it.

DROP TABLE IF EXISTS social_posts;
DROP TABLE IF EXISTS social_metrics;
DROP TABLE IF EXISTS social_imports;
DROP TABLE IF EXISTS connections;
