-- 048_two_way_sms.sql — two-way SMS on the record timeline.
--
-- Inbound Twilio messages (POST /api/public/twilio/sms) land in contact_history
-- alongside the outbound sends that api/routes/messaging.py already logs. The
-- new columns distinguish direction, carry the message text for a threaded
-- conversation view, and dedupe Twilio's webhook retries by MessageSid.
-- Legacy rows keep NULLs and render exactly as before.

ALTER TABLE contact_history ADD COLUMN IF NOT EXISTS channel     TEXT;  -- 'sms' | 'email'
ALTER TABLE contact_history ADD COLUMN IF NOT EXISTS direction   TEXT;  -- 'inbound' | 'outbound'
ALTER TABLE contact_history ADD COLUMN IF NOT EXISTS body        TEXT;
ALTER TABLE contact_history ADD COLUMN IF NOT EXISTS external_id TEXT;  -- Twilio MessageSid

-- Non-partial on purpose: Postgres unique indexes ignore NULLs (all legacy and
-- non-Twilio rows), and a plain index lets the webhook use
-- ON CONFLICT (external_id) DO NOTHING for retry dedupe.
CREATE UNIQUE INDEX IF NOT EXISTS idx_history_external_id ON contact_history(external_id);

-- Inbound matching compares the last 10 digits of the sender's number against
-- the record's contact phone; this expression index covers the primary arm.
CREATE INDEX IF NOT EXISTS idx_properties_phone_digits
    ON properties (RIGHT(regexp_replace(COALESCE(contact_phone,''), '[^0-9]', '', 'g'), 10));
