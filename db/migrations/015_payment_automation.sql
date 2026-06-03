-- 015_payment_automation.sql — Stripe Connect + invoice delivery/payment automation
-- Adds connected-account onboarding, hosted pay-page tokens, Stripe linkage on
-- invoices/payments, platform-fee auditing, and a webhook idempotency log.

-- 1. Connected Stripe accounts (one per owner; keyed by user for easy multi-tenant later)
CREATE TABLE IF NOT EXISTS stripe_accounts (
  id                  SERIAL PRIMARY KEY,
  user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  stripe_account_id   TEXT NOT NULL UNIQUE,             -- acct_xxx
  account_type        TEXT NOT NULL DEFAULT 'express',
  charges_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
  payouts_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
  details_submitted   BOOLEAN NOT NULL DEFAULT FALSE,
  onboarding_status   TEXT NOT NULL DEFAULT 'pending',  -- pending|active|restricted
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stripe_accounts_user ON stripe_accounts(user_id);

DROP TRIGGER IF EXISTS stripe_accounts_updated_at ON stripe_accounts;
CREATE TRIGGER stripe_accounts_updated_at
  BEFORE UPDATE ON stripe_accounts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 2. Invoice columns: hosted pay-page token, Stripe linkage, delivery + fee audit
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS pay_token                  TEXT UNIQUE;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stripe_checkout_session_id TEXT;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stripe_payment_intent_id   TEXT;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS platform_fee_amount        NUMERIC(10,2) DEFAULT 0;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sent_at                    TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sent_channels              TEXT[];
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS last_emailed_at            TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS last_sms_at                TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_invoices_pay_token ON invoices(pay_token);
CREATE INDEX IF NOT EXISTS idx_invoices_checkout  ON invoices(stripe_checkout_session_id);

-- 3. Webhook idempotency log (Stripe retries events; prevents double-recording)
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
  id           SERIAL PRIMARY KEY,
  event_id     TEXT NOT NULL UNIQUE,   -- evt_xxx
  event_type   TEXT NOT NULL,
  received_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Link an invoice_payment back to its Stripe objects (audit trail)
ALTER TABLE invoice_payments ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT;
ALTER TABLE invoice_payments ADD COLUMN IF NOT EXISTS stripe_charge_id         TEXT;
