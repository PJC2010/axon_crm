-- Machine-learning predictive lead scoring foundations.
--
-- Three additions, all additive (no existing column changes):
--   1. lead_feature_snapshots — point-in-time feature vectors captured when a lead
--      is first scored, so training never sees enrichment filled in *after* the
--      lead converted (target-leakage guard). Outcome columns are backfilled later.
--   2. model_versions — serialized model artifacts + holdout metrics, one active
--      version per scope ('global' or 'account:<id>'), for champion/challenger.
--   3. properties.ml_conversion_prob / ml_model_version — the learned score shown
--      alongside the deterministic lead_score (populated in shadow or learned mode).

-- ── 1. Point-in-time feature snapshots ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_feature_snapshots (
    id            SERIAL PRIMARY KEY,
    property_id   INT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    account_id    INT REFERENCES accounts(id),
    vertical      TEXT,
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Raw property fields the model cares about (JSON), NOT the engineered vector,
    -- so feature engineering can evolve without re-snapshotting.
    features      JSONB NOT NULL DEFAULT '{}',
    -- Outcome label, backfilled from pipeline status / quotes / invoices.
    -- 1 = converted (won), 0 = lost or aged-out, NULL = still in flight (censored).
    outcome       SMALLINT,
    outcome_at    TIMESTAMPTZ,
    job_value     NUMERIC(12,2),
    -- One snapshot per property: keep the FIRST (creation-time) feature state.
    UNIQUE (property_id)
);

CREATE INDEX IF NOT EXISTS idx_lfs_account_outcome
    ON lead_feature_snapshots (account_id, outcome);
CREATE INDEX IF NOT EXISTS idx_lfs_captured
    ON lead_feature_snapshots (captured_at);

-- ── 2. Model registry ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_versions (
    id            SERIAL PRIMARY KEY,
    -- 'global' (pooled across all accounts, PII-free) or 'account:<id>'.
    scope         TEXT NOT NULL DEFAULT 'global',
    account_id    INT REFERENCES accounts(id),   -- NULL for global
    algo          TEXT NOT NULL DEFAULT 'logreg',
    artifact      JSONB NOT NULL,                -- serialized model (weights + scaler)
    metrics       JSONB NOT NULL DEFAULT '{}',   -- {roc_auc, lift_decile, brier, ...}
    n_train       INT,
    n_test        INT,
    trained_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active     BOOLEAN NOT NULL DEFAULT FALSE
);

-- At most one active version per scope (champion). Partial unique index.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_model_per_scope
    ON model_versions (scope) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_model_versions_scope
    ON model_versions (scope, trained_at DESC);

-- ── 3. Learned score on the lead row ─────────────────────────────────────────
ALTER TABLE properties ADD COLUMN IF NOT EXISTS ml_conversion_prob DOUBLE PRECISION;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS ml_model_version    INT;
