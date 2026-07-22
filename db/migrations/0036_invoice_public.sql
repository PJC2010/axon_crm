-- 036_invoice_public.sql — public invoice PDF links.
--
-- A delivery SMS can't carry a file attachment, so the text points the customer
-- at a tokenized, read-only PDF link (and Twilio fetches the same URL as the MMS
-- media). The token is unguessable and serves only the rendered PDF — no account
-- internals — mirroring the public quote pattern (024_quote_public.sql).

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS public_token TEXT;

-- Backfill existing rows, then enforce presence + uniqueness going forward.
UPDATE invoices SET public_token = gen_random_uuid()::text WHERE public_token IS NULL;

ALTER TABLE invoices ALTER COLUMN public_token SET DEFAULT gen_random_uuid()::text;
ALTER TABLE invoices ALTER COLUMN public_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_public_token ON invoices(public_token);
