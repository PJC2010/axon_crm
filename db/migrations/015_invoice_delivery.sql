-- 015_invoice_delivery.sql — track when/how an invoice was sent to the client.
-- Supports the "Send Invoice" feature (email via Resend, SMS via Twilio).
-- (Online card payments / Stripe Connect are deferred — see
--  api/integrations/stripe/README.md.)

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sent_at         TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sent_channels   TEXT[];
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS last_emailed_at TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS last_sms_at     TIMESTAMPTZ;
