-- 047_stripe_payments.sql — Stripe Connect Express online payments.
--
-- Each tenant (account) onboards a Stripe Express connected account; customers
-- pay invoices via Checkout Sessions created ON the connected account (direct
-- charges), with Axon taking a platform fee. The webhook inserts an
-- invoice_payments row and funnels through _update_invoice_payment_state, the
-- same path manual payments use. See api/integrations/stripe/README.md.

-- One connected account per tenant. The owner is merchant of record.
CREATE TABLE IF NOT EXISTS stripe_accounts (
    id                 SERIAL PRIMARY KEY,
    account_id         INTEGER NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE,
    stripe_account_id  TEXT NOT NULL UNIQUE,          -- acct_...
    charges_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    payouts_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    details_submitted  BOOLEAN NOT NULL DEFAULT FALSE,
    created_by         INTEGER REFERENCES users(id),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- Pay-page token on invoices (mirrors 036_invoice_public.sql). Kept separate
-- from public_token so a circulating PDF link is not also a payment-initiation
-- credential.
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS pay_token TEXT;
UPDATE invoices SET pay_token = gen_random_uuid()::text WHERE pay_token IS NULL;
ALTER TABLE invoices ALTER COLUMN pay_token SET DEFAULT gen_random_uuid()::text;
ALTER TABLE invoices ALTER COLUMN pay_token SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_pay_token ON invoices(pay_token);

-- Checkout linkage + the platform fee charged on the (latest) checkout.
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stripe_checkout_session_id TEXT;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS stripe_payment_intent_id   TEXT;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS platform_fee_amount        NUMERIC(10,2);

-- Webhook idempotency log. Stripe event ids are globally unique; a duplicate
-- delivery (Stripe retries non-2xx) hits the UNIQUE constraint and is skipped.
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    id                 SERIAL PRIMARY KEY,
    event_id           TEXT NOT NULL UNIQUE,          -- evt_...
    event_type         TEXT NOT NULL,
    stripe_account_id  TEXT,                          -- event.account (Connect events)
    payload            JSONB,
    status             TEXT NOT NULL DEFAULT 'received',  -- received|processed|ignored|error
    error              TEXT,
    received_at        TIMESTAMPTZ DEFAULT NOW(),
    processed_at       TIMESTAMPTZ
);

-- Stripe linkage on payments. The partial unique index is the payment-level
-- dedupe: checkout.session.completed and payment_intent.succeeded both try to
-- record the same PaymentIntent, and only one insert wins.
ALTER TABLE invoice_payments ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT;
ALTER TABLE invoice_payments ADD COLUMN IF NOT EXISTS stripe_charge_id         TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_stripe_pi
    ON invoice_payments(stripe_payment_intent_id)
    WHERE stripe_payment_intent_id IS NOT NULL;
