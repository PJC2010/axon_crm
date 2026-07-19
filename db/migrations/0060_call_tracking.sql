-- 0060_call_tracking.sql — inbound call tracking (the `calls` module).
--
-- Each account can own a Twilio "tracking number" that forwards to its real
-- business phone (POST /api/public/twilio/voice answers, logs, then <Dial>s).
-- Callers are matched to a record by phone digits scoped to the account; an
-- unknown caller becomes a new lead. Every call gets one `calls` row keyed by
-- Twilio's CallSid (webhook-retry idempotency + first-class duration/outcome
-- for the call log page) plus a contact_history row so it threads into the
-- record timeline like SMS does.

-- Per-account Twilio tracking numbers. The webhook resolves the tenant from
-- the call's To number, so an active number can belong to only one account.
CREATE TABLE IF NOT EXISTS tracking_numbers (
    id             SERIAL PRIMARY KEY,
    account_id     INT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    phone_number   TEXT NOT NULL,               -- E.164 as purchased (+18325550100)
    phone_digits   TEXT NOT NULL,               -- last-10 normalized (webhook lookup key)
    twilio_sid     TEXT NOT NULL,               -- IncomingPhoneNumber SID (PN...)
    forward_to     TEXT,                        -- the business's real phone
    friendly_name  TEXT,
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released')),
    voice_settings JSONB NOT NULL DEFAULT '{}'::jsonb,  -- future: dial timeout, whisper, ...
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at    TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_numbers_digits_active
    ON tracking_numbers (phone_digits) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_tracking_numbers_account ON tracking_numbers (account_id);

-- One row per inbound call. call_sid UNIQUE is the idempotency anchor: the
-- voice webhook inserts with ON CONFLICT DO NOTHING, so a Twilio retry skips
-- lead creation / history side effects and just re-returns the Dial TwiML.
CREATE TABLE IF NOT EXISTS calls (
    id                 SERIAL PRIMARY KEY,
    account_id         INT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    property_id        INT REFERENCES properties(id) ON DELETE SET NULL,
    tracking_number_id INT REFERENCES tracking_numbers(id) ON DELETE SET NULL,
    call_sid           TEXT NOT NULL UNIQUE,    -- Twilio CallSid (CA...)
    direction          TEXT NOT NULL DEFAULT 'inbound',
    from_number        TEXT,
    from_digits        TEXT,
    to_number          TEXT,
    caller_name        TEXT,                    -- CNAM when Twilio provides it
    status             TEXT NOT NULL DEFAULT 'in-progress'
                       CHECK (status IN ('in-progress', 'completed')),
    outcome            TEXT CHECK (outcome IN ('answered', 'missed', 'busy')),
    duration_seconds   INT,
    lead_created       BOOLEAN NOT NULL DEFAULT FALSE,  -- this call created the lead
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_calls_account_started ON calls (account_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_property ON calls (property_id);

-- Account-scoped caller lookup. 048's idx_properties_phone_digits is unscoped
-- (the single global SMS number matches cross-account) and covers only
-- contact_phone; per-account tracking numbers let calls scope the match.
CREATE INDEX IF NOT EXISTS idx_properties_acct_phone_digits ON properties
    (account_id, RIGHT(regexp_replace(COALESCE(contact_phone, ''), '[^0-9]', '', 'g'), 10));
CREATE INDEX IF NOT EXISTS idx_properties_acct_phone_alt_digits ON properties
    (account_id, RIGHT(regexp_replace(COALESCE(contact_phone_alt, ''), '[^0-9]', '', 'g'), 10));
