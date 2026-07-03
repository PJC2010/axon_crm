# Stripe Connect — online invoice payments

Online card payments via **Stripe Connect Express + direct charges +
`application_fee_amount`, paid through Stripe Checkout Sessions**. This was
deferred for a while; it is now live. The design:

- Each business owner is an Express **connected account**; customers pay into
  the owner's account (owner is merchant of record, pays Stripe fees, owns
  disputes).
- Axon takes a configurable percentage platform fee (`STRIPE_PLATFORM_FEE_PCT`
  → `application_fee_amount`) on each charge. Funds never touch an
  Axon-controlled account (avoids money-transmitter classification).
- Checkout Sessions are created **on the connected account** (`stripe_account=`)
  with `payment_intent_data.application_fee_amount`.

## Where the pieces live

- **`stripe_client.py`** (this folder) — lazy-imported SDK helpers: Express
  account creation, onboarding account links, status refresh, Checkout Session
  creation, webhook signature verification. Gated by `stripe_configured()`.
- **`api/routes/stripe_payments.py`** — all routes:
  - Authenticated (gated on the `invoicing` module): `POST /api/stripe/connect`
    (owner onboarding), `GET /api/stripe/status`,
    `POST /api/invoices/{id}/checkout`.
  - Public (ungated, token-addressed): `GET/POST /api/public/pay/{pay_token}[/checkout]`
    for the hosted pay page, and `POST /api/public/stripe/webhook`.
- **Schema** — `db/migrations/047_stripe_payments.sql`: `stripe_accounts`,
  `stripe_webhook_events` (idempotency log), `pay_token` +
  checkout/PaymentIntent columns on `invoices`, Stripe linkage on
  `invoice_payments` with a partial unique index on the PaymentIntent id
  (payment-level dedupe). `'stripe'` is a `PAYMENT_METHODS` value.
- **Payment reconciliation** — the webhook inserts an `invoice_payments` row and
  calls `_update_invoice_payment_state` (`api/invoice_logic.py`), the same path
  manual payments use, so AR summaries/aging need no special casing.
- **Frontend** — "Payments" card in Settings (Connect/finish-onboarding/ready),
  a pay-link row on the invoice detail, and the public pay page at
  `app/pay/[token]/page.tsx` with post-checkout status polling.
- Invoice delivery (`api/notifications.py`) appends a "Pay online" button/link
  to the email/SMS **only when** the account's connected account has
  `charges_enabled` (see `_pay_url_if_ready` in `api/routes/invoices.py`).

## Configuration

- `STRIPE_SECRET_KEY` — the platform's secret key. Empty ⇒ Stripe endpoints
  return 503 and invoices send with no pay link (fail-soft).
- `STRIPE_WEBHOOK_SECRET` — signing secret of the webhook endpoint. **Must be a
  Connect endpoint** ("Listen to events on Connected accounts" in the Stripe
  dashboard) pointed at `/api/public/stripe/webhook`: direct charges emit
  `checkout.session.completed` / `payment_intent.succeeded` on the *connected*
  account, and `account.updated` (which flips onboarding status) also arrives
  there. Subscribe to those three event types.
- `STRIPE_PLATFORM_FEE_PCT` — Axon's percentage cut per charge (default 2.0).
- `APP_BASE_URL` — frontend origin for pay links (`{APP_BASE_URL}/pay/{token}`).

## Local testing

```sh
stripe listen --forward-connect-to localhost:8000/api/public/stripe/webhook
```

(note `--forward-connect-to`, not `--forward-to` — these are connected-account
events). Put the CLI's `whsec_…` in `STRIPE_WEBHOOK_SECRET`, connect a test
Express account from Settings, then pay an invoice's `/pay/{token}` page with
`4242 4242 4242 4242`.
