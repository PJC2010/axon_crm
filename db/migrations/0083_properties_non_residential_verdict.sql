-- properties.non_residential_reasons — the stored verdict of pipeline/residential.py.
--
-- The same move migration 0077 made for `parcels`, for the other half of the
-- problem. 0077 stopped the seed re-deriving the rule per tenant; the audit
-- endpoint (/api/property-data/non-residential) still re-derived it per page
-- load. That endpoint interpolates 11,678 bytes of predicate across 9 reasons
-- and evaluates all of it PER ROW, three times over (totals, samples, and the
-- optional per-ZIP pass), for every live lead in the account. On 2026-08-29 it
-- returned QueryCanceled — statement_timeout, 30s — to the data-quality page,
-- which is precisely the regression pipeline/property_audit.py's own header
-- warns about.
--
-- Why an ARRAY and not the boolean 0077 used
-- ──────────────────────────────────────────
-- parcels.non_residential answers one question: may the seed skip this parcel?
-- One EXCLUDE-tier boolean is the whole answer. The audit asks a different
-- question — it reports a count for EVERY reason in BOTH tiers, and shows the
-- operator which reasons each sample row tripped, so they can judge the rule
-- before acting on it. A boolean cannot carry that, and nine booleans would put
-- the reason list in the schema, where adding a REVIEW reason becomes a
-- migration. The array holds whatever the rule currently names.
--
-- NULL means "never classified" and is NOT the same as {}. {} is a row the rule
-- has looked at and cleared; NULL is a row it has not reached yet. The audit
-- reports the NULL count as `unclassified` rather than folding it into
-- "residential", because silently reporting an unexamined row as clean is how
-- an audit stops being one.
--
-- DELIBERATELY NO BACKFILL, for both of 0077's reasons: a backfill here bakes
-- this repo's default thresholds into rows belonging to deployments that
-- override NONRESIDENTIAL_MIN_SQFT, and a full-table UPDATE inside this
-- migration's single transaction would hold ADD COLUMN's ACCESS EXCLUSIVE lock
-- on `properties` for its whole duration — with preDeployCommand running while
-- the old instances still serve, that is the exact stall this migration exists
-- to stop causing. Classification happens afterwards, from the live rule:
-- nightly in api/scheduler.py, or on demand via
-- POST /property-data/non-residential/refresh.
--
-- ARCHIVE IS NOT CHANGED. pipeline/property_audit.py::archive still evaluates
-- the live rule in its own UPDATE, on purpose — it stamps each row with what is
-- true of it *now*, so a row that changed since the audit ran is not archived
-- on a stale verdict. The audit is the page load that has to be fast; the
-- archive is a deliberate owner-only action that has to be right.

-- Fail fast rather than queueing the live site behind a lock we cannot get.
-- Every statement is idempotent, so a migrate.py re-run is the retry.
-- db/migrate.py now applies this to every migration; repeated here so the file
-- reads correctly on its own.
SET LOCAL lock_timeout = '10s';

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS non_residential_reasons TEXT[];

-- Finds the unclassified backlog for the nightly sweep and for the audit's
-- `unclassified` count — the same shape as idx_parcels_zip_unclassified (0077).
-- Shrinks toward empty as accounts classify, so it costs almost nothing to
-- maintain and makes "how much is left?" an index-only glance.
CREATE INDEX IF NOT EXISTS idx_properties_unclassified
    ON properties (account_id)
    WHERE non_residential_reasons IS NULL;

-- Which build of the rule last classified each account, keyed by a hash of the
-- generated SQL. Editing pipeline/residential.py's token lists, or overriding a
-- threshold in the environment, changes the hash, stales every stamp and
-- re-derives verdicts on the next sweep. Without it a rule change would never
-- reach already-classified rows: the IS DISTINCT FROM change guard makes a
-- re-run write nothing, so nothing else would ever trigger reclassification,
-- and a token removed from the rule (a discovered surname collision) would keep
-- flagging real homeowners forever. Same argument as parcel_rule_stamps (0077),
-- scoped per account because `properties` is per-tenant.
CREATE TABLE IF NOT EXISTS property_rule_stamps (
    account_id    INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    rule_hash     TEXT NOT NULL,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Assertions for the new table, per 0074 and 0080 ──────────────────────────
-- accounts cascade (an account IS its data) and every FK child column carries a
-- leading-column index (or DELETE /admin/accounts/{id} sequentially scans it).
-- The PRIMARY KEY above supplies the index; this fails the deploy if either
-- property is ever lost to a later edit.
DO $$
DECLARE bad TEXT;
BEGIN
    SELECT string_agg(c.conname, ', ') INTO bad
      FROM pg_constraint c
      JOIN pg_class src ON src.oid = c.conrelid
     WHERE src.relname = 'property_rule_stamps'
       AND c.contype = 'f'
       AND c.confdeltype <> 'c';
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'property_rule_stamps FK(s) not ON DELETE CASCADE: %', bad;
    END IF;

    SELECT string_agg(c.conname, ', ') INTO bad
      FROM pg_constraint c
      JOIN pg_class src ON src.oid = c.conrelid
     WHERE src.relname = 'property_rule_stamps'
       AND c.contype = 'f'
       AND NOT EXISTS (
         SELECT 1 FROM pg_index i
          WHERE i.indrelid = c.conrelid
            AND i.indislive AND i.indisvalid
            AND (i.indkey::int2[])[0:array_length(c.conkey, 1) - 1] = c.conkey
       );
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'property_rule_stamps FK child column(s) unindexed: %', bad;
    END IF;
END $$;
