-- Scoring feedback loop — Phase 1 foundation (outcome tracking + model registry).
--
-- Four additive tables; no existing table changes. Adapted from the build plan's
-- DDL to this repo's conventions: the tenant column is account_id (not org_id),
-- leads are rows of `properties` (so lead FKs are property_id), and the registry
-- is named scoring_model_versions because migration 034 already uses
-- `model_versions` for the separate pipeline/ml predictive subsystem.
--
--   1. scoring_model_versions — registry of lead-scoring model versions. The
--      hand-set heuristic is seeded below as 'v0-heuristic' and marked active,
--      so every score snapshot carries a model-version FK from day one and
--      heuristic-era data stays usable as a training baseline forever.
--   2. lead_score_snapshots — feature + score snapshot written EVERY time a lead
--      is scored (unlike lead_feature_snapshots from 034, which keeps only the
--      first-score state). Training reads features from here — the values the
--      model actually saw — never from re-enriched live rows.
--   3. lead_events — append-only outcome event log (surfaced → viewed →
--      contacted → quote_sent → won/lost/…). Lead state is derived from events;
--      rows are never UPDATEd or DELETEd.
--   4. training_labels — derived labels, written only by the nightly labeling
--      job (Phase 3), rebuilt idempotently.

-- ── 1. Model registry ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scoring_model_versions (
    id                  SERIAL PRIMARY KEY,
    version_tag         TEXT UNIQUE NOT NULL,           -- 'v0-heuristic', 'v1-logreg-2026-08'
    algorithm           TEXT NOT NULL,                  -- 'heuristic_weights' | 'logistic_regression'
    feature_list        TEXT[] NOT NULL,                -- raw property fields the model consumes
    coefficients        JSONB,                          -- v0: factor-keyed weights (config.DEFAULT_WEIGHTS);
                                                        -- ML: {"home_age": 0.42, ..., "_intercept": -1.1}
    scaler_params       JSONB,                          -- {"means": {...}, "stds": {...}}
    calibration         JSONB,                          -- Platt/isotonic params; NULL for v0
    grade_bands         JSONB NOT NULL,                 -- v0: {"A":75,"B":55,"C":35} on the 0-100 score;
                                                        -- ML: thresholds on calibrated probability
    hyperparams         JSONB,
    metrics             JSONB,                          -- {"auc":, "log_loss":, "brier":, "test_rows":, ...}
    training_rows       INT,
    training_positives  INT,
    status              TEXT NOT NULL DEFAULT 'shadow'
                        CHECK (status IN ('shadow','active','retired')),
    trained_at          TIMESTAMPTZ,
    promoted_at         TIMESTAMPTZ,
    notes               TEXT
);

-- Exactly one active model at a time (promotion demotes the previous active).
CREATE UNIQUE INDEX IF NOT EXISTS one_active_scoring_model
    ON scoring_model_versions (status) WHERE status = 'active';

-- ── 2. Feature + score snapshots (written on every scoring pass) ──────────────
CREATE TABLE IF NOT EXISTS lead_score_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    property_id         INT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    account_id          INT NOT NULL REFERENCES accounts(id),
    model_version_id    INT NOT NULL REFERENCES scoring_model_versions(id),
    features            JSONB NOT NULL,                 -- exact raw factor values at scoring time (PII-free:
                                                        -- never owner names, phones, emails, or addresses)
    raw_score           NUMERIC(8,4) NOT NULL,          -- 0-100 heuristic score, or logit for ML models
    calibrated_prob     NUMERIC(6,5),                   -- NULL for v0-heuristic
    grade               CHAR(1) NOT NULL,
    scored_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_snapshots_lead  ON lead_score_snapshots (property_id, scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_model ON lead_score_snapshots (model_version_id);

-- ── 3. Append-only outcome events ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_events (
    id              BIGSERIAL PRIMARY KEY,
    property_id     INT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    account_id      INT NOT NULL REFERENCES accounts(id),
    event_type      TEXT NOT NULL CHECK (event_type IN (
                        'surfaced',          -- lead shown/delivered to contractor
                        'viewed',
                        'contact_attempted',
                        'contacted',         -- reached a human
                        'quote_sent',
                        'won',
                        'lost',
                        'disqualified',      -- bad data, wrong property type, etc.
                        'suppressed'         -- renter, DNC, already-serviced
                    )),
    channel         TEXT,                    -- 'call','sms','email','door','mail'
    actor_user_id   INT REFERENCES users(id),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB                    -- {"quote_amount": 8500, "loss_reason": "price"}
);
CREATE INDEX IF NOT EXISTS idx_events_lead     ON lead_events (property_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_org_type ON lead_events (account_id, event_type, occurred_at);

-- ── 4. Derived training labels (labeling job only; rebuilt idempotently) ──────
CREATE TABLE IF NOT EXISTS training_labels (
    id                  BIGSERIAL PRIMARY KEY,
    property_id         INT NOT NULL,
    snapshot_id         BIGINT NOT NULL REFERENCES lead_score_snapshots(id) ON DELETE CASCADE,
    label               SMALLINT NOT NULL,              -- 1 / 0
    label_type          TEXT NOT NULL,                  -- 'won_90d' | 'quote_30d' (early proxy)
    attribution_days    INT NOT NULL,
    matured_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_id, label_type)
);

-- ── Seed: register the current hand-set heuristic as v0, active ───────────────
-- Coefficients freeze config.DEFAULT_WEIGHTS as of this migration, keyed by the
-- same factor keys the scorer consumes (config.FACTOR_META maps each key to the
-- raw property field in feature_list). Grade bands mirror config.GRADE_BANDS.
-- Scoring math is untouched — the live scorer still reads config.py; this row
-- exists so snapshots have a version to reference and v0 is auditable later.
INSERT INTO scoring_model_versions
    (version_tag, algorithm, feature_list, coefficients, grade_bands,
     status, trained_at, promoted_at, notes)
VALUES (
    'v0-heuristic',
    'heuristic_weights',
    ARRAY['year_built', 'last_sale_date', 'estimated_equity', 'garage_spaces',
          'zip_median_income', 'neighborhood_value_ratio', 'permit_count_24mo'],
    '{"age": 0.25, "sale": 0.22, "equity": 0.18, "garage": 0.15,
      "income": 0.06, "neighborhood": 0.06, "permit": 0.08}',
    '{"A": 75, "B": 55, "C": 35}',
    'active',
    NOW(),
    NOW(),
    'Hand-set default heuristic weights (config.DEFAULT_WEIGHTS) registered as the '
    'baseline model. Vertical-weight overrides (config.VERTICAL_WEIGHTS) run under '
    'this same version; the vertical is captured per-snapshot in features.vertical.'
)
ON CONFLICT (version_tag) DO NOTHING;
