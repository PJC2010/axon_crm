-- parcels.non_residential — the stored verdict of pipeline/residential.py.
--
-- seed_account(residential_only=True) used to inline sql_non_residential()
-- into every tenant seed: a ~12KB predicate with 76 strpos() calls, each
-- re-normalizing owner_name from scratch. Measured on ZIP 77433 (47,531
-- parcels) that filter alone cost 4.1s per seed, re-paid by every tenant on
-- every seed of the ZIP. The verdict is a fact about the parcel, not about
-- the tenant, so it belongs in the shared cache — computed when the parcel's
-- data (or the rule) changes, read as a boolean at seed time.
--
-- Polarity and NULL semantics follow the tiering in pipeline/residential.py:
-- TRUE means "carries an EXCLUDE-tier reason — structurally impossible for a
-- dwelling"; FALSE means "looks like a home, or we cannot tell"; NULL means
-- "never classified" and is treated as seedable (the seed filter reads
-- NOT COALESCE(non_residential, FALSE)), because a false positive here
-- excludes a paying customer while a false negative leaves a visible bad row.
--
-- DELIBERATELY NO BACKFILL. Two earlier drafts backfilled here with a
-- point-in-time snapshot of the rule, and both halves of that were wrong:
--   * the snapshot bakes in this repo's default config, so a deployment that
--     overrides NONRESIDENTIAL_MIN_SQFT got verdicts derived from someone
--     else's threshold;
--   * a full-table UPDATE (~5 min at 894k parcels, measured) runs inside this
--     migration's single transaction while ADD COLUMN's ACCESS EXCLUSIVE lock
--     is held — Render runs migrations in preDeployCommand with the old
--     instances still serving, so every parcels access on the live site
--     queues behind it for the duration.
-- Instead, classification happens per ZIP at the next touch, with the LIVE
-- rule: pipeline/parcels.py::ensure_from_hcad classifies whenever the ZIP's
-- rule stamp (below) is missing or stale — and every production seed path
-- runs ensure_from_hcad before seed_account materializes rows, so the filter
-- is never applied to an unclassified ZIP.
--
-- parcel_rule_stamps records which build of the rule last classified each
-- ZIP, keyed by a hash of the generated SQL expression — so editing
-- pipeline/residential.py's token lists, or overriding a threshold in the
-- environment, re-derives every ZIP's verdicts on its next seed instead of
-- going silently stale. Shared/unscoped like parcels itself (no account_id):
-- the verdict is tenant-independent, and the admin hard-delete's purge
-- assertion ignores tables without an account_id column by design.

-- Fail fast instead of queueing the live site behind a lock we cannot get:
-- migrate.py re-runs are the retry path, and every statement here is
-- idempotent. Transaction-scoped (migrate.py runs each file in one txn).
SET LOCAL lock_timeout = '10s';

ALTER TABLE parcels ADD COLUMN IF NOT EXISTS non_residential BOOLEAN;

-- Finds unclassified backlog for the self-heal probe in parcels.py, the same
-- pattern as idx_parcels_zip_ungeocoded (0065). Shrinks toward empty as ZIPs
-- classify, so it costs nothing to maintain and makes the per-seed "any NULL
-- verdicts left?" probe an index-only glance.
CREATE INDEX IF NOT EXISTS idx_parcels_zip_unclassified
    ON parcels (zip) WHERE non_residential IS NULL;

CREATE TABLE IF NOT EXISTS parcel_rule_stamps (
    zip           TEXT PRIMARY KEY,
    rule_hash     TEXT NOT NULL,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
