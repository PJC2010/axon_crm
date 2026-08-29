-- Indexes for the three dashboard reads that returned QueryCanceled 500s.
--
-- On 2026-08-29 /api/pipeline/analytics, /api/pipeline/alerts and
-- /api/property-data/non-residential all died on the same exception:
-- statement_timeout (DB_STATEMENT_TIMEOUT_MS, 30s) cancelling a scan of
-- `properties`. A DDL lock stall during preDeployCommand is what pushed them
-- over on that particular deploy (fixed in db/migrate.py), but they lost that
-- race so easily because none of the three could use an index. This migration
-- is the other half: make the statements cheap enough that a hiccup no longer
-- costs the operator a 500.
--
-- Shapes are chosen per statement, not sprinkled:
--
--   * (account_id, stage_moved_at) WHERE archived_at IS NULL
--     Serves BOTH the analytics win-rate/cycle-time/leads-won filters
--     (`stage_moved_at >= NOW() - INTERVAL 'N days'`, a range scan) and the
--     alerts stuck-deals scan, whose `ORDER BY stage_moved_at ASC LIMIT 50`
--     can now stop at the fiftieth row instead of sorting the account.
--     stage_moved_at appeared in NO index on `properties` before this.
--
--   * (account_id, score_grade, status) WHERE archived_at IS NULL
--     The alerts cooling-leads scan. idx_properties_dialer_queue (0069) leads
--     with the same two columns and looks like it should serve this, but it is
--     partial on `do_not_call = FALSE` — a predicate the alerts query never
--     states, so the planner cannot use it there. Partial on archived_at only,
--     which every one of these reads does state.
--
--   * stage_transitions (transitioned_at)
--     The analytics funnel and per-stage-duration queries filter on
--     transitioned_at alone. idx_transitions_status leads with to_status, so it
--     could not serve either.
--
--   * stage_transitions (property_id, to_status, transitioned_at DESC)
--     The per-stage-duration JOIN LATERAL looks up "this property's most recent
--     transition INTO t1.from_status". idx_transitions_property has only
--     property_id, so each iteration fetched every transition for the property
--     and sorted them. This makes it one descending index probe.
--     It leads with property_id, so it also satisfies 0080's FK-support
--     assertion for stage_transitions.property_id on its own; the older
--     idx_transitions_property is left in place rather than dropped, because
--     removing an index is a separate decision from adding one and 0078 is the
--     place that argument belongs.
--
-- Partial on `archived_at IS NULL` because every one of these reads states it,
-- and because archived rows are the minority that never appears in a dashboard.
-- That also keeps the indexes small on the bulk-seeded tables they cover.

-- Fail fast rather than queueing the live site behind a lock we cannot get:
-- CREATE INDEX takes SHARE (blocks writes), and preDeployCommand runs while the
-- old instances still serve. Every statement here is IF NOT EXISTS, so a
-- migrate.py re-run is the retry. db/migrate.py now sets this for every
-- migration; repeated here so the file is correct read on its own.
-- (CONCURRENTLY is not an option: the runner wraps each migration in a
-- transaction.)
SET LOCAL lock_timeout = '10s';

CREATE INDEX IF NOT EXISTS idx_properties_acct_stage_moved
    ON properties (account_id, stage_moved_at)
    WHERE archived_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_properties_acct_grade_status
    ON properties (account_id, score_grade, status)
    WHERE archived_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_transitions_at
    ON stage_transitions (transitioned_at);

CREATE INDEX IF NOT EXISTS idx_transitions_prop_status_at
    ON stage_transitions (property_id, to_status, transitioned_at DESC);
