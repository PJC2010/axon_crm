# Stripe Connect — Deferred (placeholder)

Online card payments via **Stripe Connect** were scoped and prototyped, then
pulled out of the active product. This folder marks where the integration code
would live when we pick it back up. **Nothing here is wired into the app today.**

## What stays in the app right now
- **Invoice delivery** (email via Resend, SMS via Twilio) — see
  `api/notifications.py` and the `POST /api/invoices/{id}/send` route in
  `api/routes/invoices.py`. This sends a plain invoice summary with no pay link.
- Invoice delivery tracking columns on `invoices`: `sent_at`, `sent_channels`,
  `last_emailed_at`, `last_sms_at` (migration `db/migrations/015_invoice_delivery.sql`).

## The deferred design (so we don't lose it)
Recommended approach: **Stripe Connect Express + direct charges +
`application_fee_amount`, paid via Stripe Checkout Sessions.**

- Each business owner is an Express **connected account**; customers pay into the
  owner's account (owner is merchant of record, pays Stripe fees, owns disputes).
- Axon takes a configurable percentage platform fee (`application_fee_amount`)
  on each charge → Axon's revenue share. Funds never touch an Axon-controlled
  account (avoids money-transmitter classification).
- Checkout Sessions are created **on the connected account** (`stripe_account=`)
  with `payment_intent_data.application_fee_amount`.

### To re-enable, we'd add back:
1. **Deps / config**: `stripe>=9.0` in `requirements.txt`; `STRIPE_SECRET_KEY`,
   `STRIPE_WEBHOOK_SECRET`, `STRIPE_PLATFORM_FEE_PCT`, and a `PUBLIC_APP_URL`
   (for hosted pay links) in `config.py`.
2. **Schema** (new migration): a `stripe_accounts` table (per-owner connected
   account + onboarding status); `pay_token`, `stripe_checkout_session_id`,
   `stripe_payment_intent_id`, `platform_fee_amount` columns on `invoices`; a
   `stripe_webhook_events` idempotency log; `stripe_payment_intent_id` /
   `stripe_charge_id` on `invoice_payments`; and a `'stripe'` value in
   `PAYMENT_METHODS`.
3. **Backend**: a `stripe_client.py` helper (Express onboarding, account links,
   Checkout Sessions); authenticated onboarding/status/checkout routes; an
   unauthenticated **public router** for the tokenized pay page + a
   signature-verified, idempotent webhook that inserts an `invoice_payments` row
   and calls `_update_invoice_payment_state` (`api/invoice_logic.py`) — the same
   path manual payments already use, so AR/aging "just work".
4. **Frontend**: a "Connect Stripe" card in Settings; a "Pay Now" button; a
   public `app/pay/[token]/page.tsx` hosted pay page with payment-status polling.

The original implementation is recoverable from git history
(commit "Add invoice payment automation (Phase 1 MVP)") if we want to restore it.
