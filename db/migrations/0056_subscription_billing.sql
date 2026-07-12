-- 0056_subscription_billing.sql — Stripe subscription billing for Axon plans.
--
-- Prospective-user audit P0: there was no way to pay for Axon itself. This is
-- distinct from Stripe Connect (047_stripe_payments.sql), where an account's
-- CUSTOMERS pay that account's invoices — here the ACCOUNT pays Axon.
--
-- One row per account. Plan entitlements remain in account_plans (the single
-- source api/entitlements.py resolves from); the billing webhook writes
-- plan_name there, and this table records the subscription state behind it.
--
-- Self-serve signups start on a local trial: status='trialing' with
-- trial_ends_at set and no Stripe ids. The scheduler downgrades expired trials
-- with no subscription to the starter plan (core stays usable — never a lockout).

CREATE TABLE IF NOT EXISTS account_billing (
    account_id             INT PRIMARY KEY REFERENCES accounts(id),
    stripe_customer_id     TEXT UNIQUE,
    stripe_subscription_id TEXT,
    plan_name              TEXT,
    -- 'trialing' / 'trial_expired' are local (pre-Stripe) states; once a
    -- subscription exists this mirrors Stripe's status (active, past_due, …).
    status                 TEXT,
    cancel_at_period_end   BOOLEAN NOT NULL DEFAULT FALSE,
    current_period_end     TIMESTAMPTZ,
    trial_ends_at          TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);
