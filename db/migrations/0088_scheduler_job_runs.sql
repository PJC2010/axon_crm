-- scheduler_job_runs — one row per execution of a scheduler tick (api/job_runs.py),
-- read by GET /admin/jobs (api/routes/admin_ops.py).
--
-- Ten of the twelve ticks in api/scheduler.py used to be log-only: the
-- trial-expiry downgrade, the workflow rules, the nightly rescores, the digests,
-- the sweeps and the stale-run reconcile each logged a summary and returned. A
-- tick that silently stopped firing — a lock held every night by a wedged
-- sibling instance, a crash, a feature flag left off — was invisible until a
-- customer noticed. Every tick now opens a row here when it starts and closes it
-- with ok / error / skipped when it ends, on the ledger's own connection, so a
-- tick that never connects (a disabled sweep) or dies mid-run still leaves its
-- record. The pipeline run family keeps pipeline_runs as its ledger.
--
-- Platform-level: no account_id and no user_id, so the accounts-CASCADE /
-- users-SET-NULL / FK-index rules of 0074 and 0080 have nothing to bind here,
-- and _assert_account_purged (which derives its table list from account_id
-- columns) is unaffected. Retention is 90 days, pruned by the hourly stale-run
-- reconcile, which also closes rows a redeploy left at `running`. Volume is
-- roughly 12 daily ticks + 24 hourly reconciles per instance.
CREATE TABLE IF NOT EXISTS scheduler_job_runs (
    id          BIGSERIAL PRIMARY KEY,
    job_id      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'ok', 'error', 'skipped')),
    error       TEXT,
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    host        TEXT
);

-- "Newest row per job" (DISTINCT ON job_id … ORDER BY started_at DESC) and one
-- job's history are the reads; the retention sweep scans by started_at.
CREATE INDEX IF NOT EXISTS idx_scheduler_job_runs_job_started
    ON scheduler_job_runs (job_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduler_job_runs_started
    ON scheduler_job_runs (started_at);
