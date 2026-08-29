-- Indexes for the leads-list sorts that returned QueryCanceled 500s.
--
-- On 2026-08-29 (21:17 and 21:48 UTC) GET /api/leads died repeatedly on
-- statement_timeout (DB_STATEMENT_TIMEOUT_MS, 30s) at api/routes/leads.py's
-- page query — first during the 0082/0083 deploy window, then again with no
-- deploy in sight, three minutes after a rescore rewrote every row in a ZIP
-- and the dashboard fired its ~20-request burst. Those only supplied the
-- shove. The query was standing on the edge because its default sort has no
-- order-serving index: the list runs WHERE account_id = %s AND archived_at
-- IS NULL ORDER BY lead_score DESC NULLS LAST LIMIT n, and the only score
-- index, idx_props_acct_zip_score (0017), keys (account_id, zip, lead_score)
-- — zip in the middle means it yields score order only under a zip equality.
-- The logs split exactly there: every timed-out request lacked zip; every
-- surviving one had zip (0017's index) or status (0021's). Without an index
-- the no-zip request gathers the account's whole unarchived book and top-N
-- sorts it — twice, counting the COUNT(*) that precedes the page query. Same
-- failure 0082 fixed for the three dashboard endpoints; /api/leads was not
-- one of the three, so it kept losing the same race. Shapes per statement,
-- 0082's rule:
--
--   * account_id + lead_score, partial on unarchived
--     The list's default sort (`score` — also what every unrecognized sort
--     value falls back to) becomes an ordered walk that stops at the
--     page_size'th row, and the COUNT(*) an index-only scan. The DESC NULLS
--     LAST spelling must stay byte-matched to SORT_MAP's expression: a
--     mismatch does not error, the planner just quietly goes back to sorting
--     the account (tests/test_leads_sort_indexes.py pins the pair).
--
--   * account_id + updated_at, partial on unarchived
--     The dashboard's recent-leads panel requests sort=updated_at on every
--     load. That key was missing from SORT_MAP entirely, so it silently fell
--     back to the score sort — the panel was not recency-sorted AND ran the
--     most expensive sort in the app. SORT_MAP now carries it; honoring it
--     without an index would just mint a new unindexed account-wide sort,
--     which is why the index lands in the same change.
--
-- Partial on archived_at IS NULL for 0082's two reasons: every consumer
-- states it (_build_filters appends it unless include_archived is passed,
-- which the list and CSV export never do), and it keeps the indexes small on
-- a bulk-seeded table. The write cost is conscious: 0078 measured index
-- maintenance at 94% of a bulk seed's write cost and pruned this table to
-- reachable indexes only. These two are reachable from the hottest read in
-- the product — the list page's default sort and every dashboard load — and
-- both columns churn (lead_score on every rescore, updated_at on every
-- UPDATE via trg_properties_updated_at), which the partial predicate at
-- least bounds to live rows.
--
-- Fail fast rather than queueing the live site behind a lock we cannot get:
-- CREATE INDEX takes SHARE (blocks writes), and preDeployCommand runs while
-- the old instances still serve. Every statement is IF NOT EXISTS, so a
-- migrate.py re-run is the retry. db/migrate.py now sets this for every
-- migration; repeated here so the file is correct read on its own.
-- (CONCURRENTLY is not an option: the runner wraps each migration in a
-- transaction.)
SET LOCAL lock_timeout = '10s';

CREATE INDEX IF NOT EXISTS idx_properties_acct_score
    ON properties (account_id, lead_score DESC NULLS LAST)
    WHERE archived_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_properties_acct_updated
    ON properties (account_id, updated_at DESC NULLS LAST)
    WHERE archived_at IS NULL;
