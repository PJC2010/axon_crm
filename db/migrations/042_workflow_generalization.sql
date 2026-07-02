-- Phase 4 of the multi-vertical generalization (docs/GENERALIZATION_ROADMAP.md §4):
-- scheduled workflow triggers and saved segments.
--
-- workflow_rule_firings is the idempotency ledger for the daily workflow tick
-- (date_offset / inactivity trigger types). fire_key is the anchor that made the
-- rule eligible — the target date's value for date_offset rules, the last-touch
-- date (or 'never') for inactivity rules. The engine claims a firing with
-- INSERT ... ON CONFLICT DO NOTHING RETURNING id and only runs the action when a
-- row comes back, so re-running the tick (or a second worker) can never double-
-- fire, while a changed anchor (e.g. a renewed policy's new expiration date)
-- legitimately re-arms the rule.

CREATE TABLE IF NOT EXISTS workflow_rule_firings (
  id          SERIAL PRIMARY KEY,
  rule_id     INTEGER NOT NULL REFERENCES workflow_rules(id) ON DELETE CASCADE,
  account_id  INTEGER NOT NULL REFERENCES accounts(id),
  -- 'property' today; child objects (policy/order/appointment) in later phases.
  target_type TEXT NOT NULL DEFAULT 'property',
  target_id   INTEGER NOT NULL,
  fire_key    TEXT NOT NULL,
  fired_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (rule_id, target_type, target_id, fire_key)
);

CREATE INDEX IF NOT EXISTS idx_wrf_account ON workflow_rule_firings(account_id);

-- Saved segments: named, shareable lead-list filter sets. filters is the same
-- shape the GET /api/leads querystring accepts (see ALLOWED_FILTER_KEYS in
-- api/routes/segments.py, which mirrors _build_filters in api/routes/leads.py).

CREATE TABLE IF NOT EXISTS segments (
  id         SERIAL PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  name       TEXT NOT NULL,
  filters    JSONB NOT NULL DEFAULT '{}',
  created_by INTEGER REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (account_id, name)
);

CREATE INDEX IF NOT EXISTS idx_segments_account ON segments(account_id);

CREATE TRIGGER segments_updated_at
  BEFORE UPDATE ON segments
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
