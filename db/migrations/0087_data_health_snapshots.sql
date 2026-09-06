-- data_health_snapshots — the nightly platform data-health report
-- (api/data_health.py), read by GET /admin/data-health.
--
-- The numbers an operator wants about the shared data layer — parcel-cache
-- coverage per ZIP, the APN→centroid match rate, classification backlog,
-- RentCast disagreement rates, the 0079 mail-city tripwire — are full scans of
-- ~1.5M-row tables (parcels, hcad_properties) and of every tenant's properties.
-- Computing them on a page load is exactly what returned QueryCanceled to the
-- data-quality page before migration 0083, so a scheduler tick computes them
-- once a night (and on demand) into one JSONB row, and the endpoint reads the
-- newest usable row plus a few index-only live figures.
--
-- Platform-level: no account_id and no user_id, so the accounts-CASCADE /
-- users-SET-NULL / FK-index rules of 0074 and 0080 have nothing to bind here,
-- and _assert_account_purged (which derives its table list from account_id
-- columns) is unaffected. Retention is 30 rows, pruned by the tick itself.
CREATE TABLE IF NOT EXISTS data_health_snapshots (
    id           BIGSERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'ok', 'partial', 'error')),
    triggered_by TEXT NOT NULL DEFAULT 'schedule',   -- schedule | admin
    host         TEXT,
    report       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error        TEXT
);

-- "Newest row" is the only read: the endpoint wants the latest usable
-- snapshot and the latest row of any status (to show a refresh in progress).
CREATE INDEX IF NOT EXISTS idx_data_health_snapshots_started
    ON data_health_snapshots (started_at DESC);
