-- Timing-signal events detected by the pipeline (just_sold, new_permit).
-- Each row records that a time-sensitive field changed between two pipeline
-- runs for a lead — the moment a static property becomes a hot prospect.
CREATE TABLE IF NOT EXISTS signal_events (
    id          SERIAL PRIMARY KEY,
    property_id INT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    account_id  INT NOT NULL REFERENCES accounts(id),
    signal_type TEXT NOT NULL,                    -- just_sold | new_permit
    details     JSONB NOT NULL DEFAULT '{}',      -- {summary, prev, new}
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_events_property ON signal_events(property_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_events_account  ON signal_events(account_id, detected_at DESC);
