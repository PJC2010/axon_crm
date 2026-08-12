-- 0069_auto_dialer.sql — outbound power dialer (the `calls` module grows an
-- outbound half: api/routes/dialer.py + the outbound webhooks in
-- api/routes/twilio_voice.py).
--
-- Outbound calls reuse the calls table (direction='outbound'): the outbound
-- TwiML webhook inserts the row, the <Dial action> callback completes the
-- mechanical outcome, and the rep's human verdict lands in the new
-- `disposition` column — the two writers never overwrite each other.

-- Widen the mechanical-outcome vocabulary for outbound dial results. 0060
-- defined the CHECK inline, so Postgres auto-named it calls_outcome_check.
-- Inbound keeps its answered/missed/busy triad; outbound adds Twilio's
-- DialCallStatus verdicts (api/call_logic.py::map_outbound_dial_status).
ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_outcome_check;
ALTER TABLE calls ADD CONSTRAINT calls_outcome_check
    CHECK (outcome IN ('answered', 'missed', 'busy', 'no_answer', 'failed', 'canceled'));

-- Who placed the outbound call (NULL for inbound/historical rows).
ALTER TABLE calls ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE SET NULL;

-- The rep's verdict after the call, separate from Twilio's mechanical outcome
-- so a late status callback can never clobber human judgment (or vice versa).
ALTER TABLE calls ADD COLUMN IF NOT EXISTS disposition TEXT
    CHECK (disposition IN ('no_answer', 'voicemail', 'interested', 'not_interested',
                           'callback', 'wrong_number', 'do_not_call'));

-- Lead-level do-not-call flag, enforced by the dialer queue AND re-checked by
-- the outbound TwiML webhook at dial time (defense in depth). Set by the
-- 'do_not_call' disposition; clearable via the lead contact PATCH.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS do_not_call BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill from the BatchData skip-trace compliance signals already stored in
-- enrichment_flags.phone_append_meta (api/phone_append_logic.py) but never
-- read back until now. #>> renders JSON booleans as 'true'; the IN list also
-- tolerates stringy provider values.
UPDATE properties SET do_not_call = TRUE
WHERE do_not_call = FALSE
  AND (COALESCE(LOWER(enrichment_flags #>> '{phone_append_meta,phone_dnc}'), '')
           IN ('true', 't', '1', 'yes', 'y')
    OR COALESCE(LOWER(enrichment_flags #>> '{phone_append_meta,litigator}'), '')
           IN ('true', 't', '1', 'yes', 'y'));

-- Queue-covering index: grade ASC puts A first, score DESC ranks within the
-- grade — the dialer queue's exact ORDER BY (api/routes/dialer.py).
CREATE INDEX IF NOT EXISTS idx_properties_dialer_queue
    ON properties (account_id, score_grade ASC, lead_score DESC)
    WHERE archived_at IS NULL AND do_not_call = FALSE;

-- Covers the queue's "no outbound call in the cooldown window" NOT EXISTS and
-- its last-call LATERAL join.
CREATE INDEX IF NOT EXISTS idx_calls_property_outbound
    ON calls (property_id, started_at DESC) WHERE direction = 'outbound';
