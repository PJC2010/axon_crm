-- Migration 033: imported social / digital-presence data store.
-- Populated today from uploaded Meta exports (Business Suite CSV, Ads Manager
-- CSV, "Download Your Information" JSON) and in future from live OAuth sync —
-- both write the SAME rows, distinguished only by the `source` column. Powers the
-- Marketing Insights engine (api/marketing_insights.py).

-- One audit row per upload (or future sync run).
CREATE TABLE IF NOT EXISTS social_imports (
    id            SERIAL PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,                       -- denormalized for convenience
    source        TEXT NOT NULL DEFAULT 'file',        -- file | oauth
    export_kind   TEXT,                                -- business_suite_csv | ads_manager_csv | dyi_json
    file_name     TEXT,
    rows_imported INTEGER DEFAULT 0,
    period_start  DATE,                                -- min date observed in the batch
    period_end    DATE,                                -- max date observed in the batch
    status        TEXT NOT NULL DEFAULT 'completed',   -- completed | failed | partial
    errors        JSONB,                               -- list of row-level error strings
    created_by    INTEGER REFERENCES users(id),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_social_imports_conn ON social_imports(account_id, connection_id);

-- Account / profile-level daily metrics (page reach, impressions, followers,
-- ad spend...). One row per (connection, metric_date, campaign) — re-imports upsert.
CREATE TABLE IF NOT EXISTS social_metrics (
    id             SERIAL PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    connection_id  INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    import_id      INTEGER REFERENCES social_imports(id) ON DELETE SET NULL,
    provider       TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'file',
    metric_date    DATE NOT NULL,
    -- Organic presence
    reach          INTEGER,
    impressions    INTEGER,
    profile_views  INTEGER,
    followers      INTEGER,          -- running total at metric_date
    follower_delta INTEGER,          -- net change that day (if the export provides it)
    engagements    INTEGER,          -- likes + comments + shares + saves
    link_clicks    INTEGER,
    -- Paid (Ads Manager) — nullable; only present on ad-export rows
    ad_spend       NUMERIC(12,2),
    ad_impressions INTEGER,
    ad_clicks      INTEGER,
    ad_cpc         NUMERIC(12,4),
    ad_cpa         NUMERIC(12,4),    -- cost per result / acquisition
    ad_roas        NUMERIC(12,4),
    ad_results     INTEGER,          -- conversions / leads / messages
    campaign_name  TEXT,             -- set when the row is per-campaign
    raw            JSONB,            -- untouched source row for forward-compat
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS social_metrics_uq
    ON social_metrics(connection_id, metric_date, COALESCE(campaign_name, ''));
CREATE INDEX IF NOT EXISTS idx_social_metrics_acct_date
    ON social_metrics(account_id, provider, metric_date);

-- Post-level performance (content type, posted time, per-post engagement).
CREATE TABLE IF NOT EXISTS social_posts (
    id            SERIAL PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    import_id     INTEGER REFERENCES social_imports(id) ON DELETE SET NULL,
    provider      TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'file',
    external_id   TEXT,              -- post / permalink id from the export (dedup key)
    posted_at     TIMESTAMPTZ,
    content_type  TEXT,              -- photo | video | reel | carousel | text | story | link
    caption       TEXT,
    permalink     TEXT,
    reach         INTEGER,
    impressions   INTEGER,
    likes         INTEGER,
    comments      INTEGER,
    shares        INTEGER,
    saves         INTEGER,
    engagements   INTEGER,           -- precomputed sum when the source gives it
    link_clicks   INTEGER,
    raw           JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS social_posts_uq
    ON social_posts(connection_id, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_social_posts_acct_time
    ON social_posts(account_id, provider, posted_at);
