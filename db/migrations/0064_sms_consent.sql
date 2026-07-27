-- 0064_sms_consent.sql — recorded SMS opt-in for A2P 10DLC / TCPA compliance.
--
-- Axon's own texts to customers (account notifications, Storm Mode territory
-- alerts) may only go to users who opted in. Twilio's campaign registration
-- asks how consent is recorded: sms_consent is the switch, sms_consent_at +
-- sms_consent_source the provenance ('signup' checkbox or 'settings' toggle),
-- and sms_opted_out_at preserves when consent was withdrawn — the history is
-- kept, not deleted, so consent can be demonstrated during a carrier audit.

ALTER TABLE users ADD COLUMN IF NOT EXISTS sms_consent BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sms_consent_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sms_consent_source TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sms_opted_out_at TIMESTAMPTZ;
