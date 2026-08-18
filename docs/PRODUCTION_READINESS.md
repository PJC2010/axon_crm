# Production Readiness — Audit Results & Launch Checklist

_Audit date: 2026-08-18. Five parallel deep-dives (auth/signup, billing/payments,
frontend, config/deployment, tenant isolation across all ~35 route modules) plus
an end-to-end smoke test of the signup → verify → send → reset → billing flow
against a real Postgres with every migration applied._

## What was verified working

- **Test suite**: 2,290+ tests pass; skips are the documented golden vendor-contract
  placeholders awaiting live-recorded baselines.
- **Migrations**: all migrations apply cleanly, in order, on a pristine Postgres 16;
  second run is a no-op; `render.yaml` runs them as `preDeployCommand`.
- **Signup end-to-end**: org + owner + stages + plan row + trial + workflows in one
  transaction; verification/welcome emails fail soft; duplicate email → 409
  (including under concurrency); trial expiry downgrades under an advisory lock.
- **JWT security**: fail-closed startup without `JWT_SECRET_KEY`; role and
  platform-admin flag re-read from the DB per request (never trusted from the JWT).
- **OAuth**: JWKS signature verification, RS256 pinned, audience + issuer + expiry
  checked, provider-verified email required for account linking.
- **Stripe webhooks (both endpoints)**: never accept an unsigned event; per-event
  idempotency ledger; Connect events verified against the connected account on
  file (forged metadata cannot mark invoices paid).
- **Tenant isolation**: no cross-tenant *read* path found anywhere — every SELECT
  on tenant tables is `account_id`-scoped, including sub-resources, JOINs, exports.
  Public quote/invoice/pay tokens are 122-bit UUIDs, looked up by token only.
- **Twilio webhooks**: signature-verified, fail closed when unconfigured.
- **Frontend**: production build passes with zero type errors; module keys and
  terminology in exact sync with the backend; all 158 API calls map to real routes.
- **No secrets in the repo** (only `.env.example` docs and test dummies).

## What this audit fixed

Security / tenancy:
- Cross-tenant **write** hole: appointments/policies/orders accepted a foreign
  `property_id` and wrote into that tenant's `contact_history` timeline. Now
  ownership-checked on create and update (404 on foreign ids), regression-tested.
- HCAD upload/delete mutated the **shared** county tables under a tenant-owner
  gate — any customer could wipe or poison every tenant's enrichment source. Now
  platform-admin only.
- `DELETE /expenses/{id}` and `DELETE /invoices/{id}/payments/{id}` are now
  owner-gated (reps could silently rewrite the books).
- `?token=` query-param auth is now accepted **only** on the CSV/PDF download
  routes that need it, not on every endpoint (URL-borne session tokens leak into
  logs and history).
- Password reset now invalidates every previously issued session (migration 0076
  `users.password_changed_at` + `iat` claim in new JWTs) — a stolen token dies
  the moment the victim resets.
- Cross-instance failed-login lockout: 8 failures per identifier per 15 minutes
  → 429, counted in `auth_events` (survives deploys, covers all instances).
- One-time tokens (verify/reset) are now burned with a single conditional
  UPDATE — no concurrent double-use.
- `POST /api/users` (team members) now enforces the same email/username/password
  rules as signup and pre-checks emails case-insensitively (mixed-case duplicates
  used to make login lookup nondeterministic). Passwords > 72 bytes are rejected
  everywhere (bcrypt truncates silently past that).
- Outbound sends (lead messages, invoice/quote delivery) now require a verified
  email and are rate-limited per account (100/hr) — an unverified bot signup can
  no longer pump spam through the platform's Resend/Twilio identity.

Billing / payments:
- `billing_configured()` now also requires `STRIPE_BILLING_WEBHOOK_SECRET`:
  checkout used to be sellable with the entitlement-granting webhook unconfigured
  — Stripe collected money, the plan was never applied, and the trial-expiry job
  then downgraded the paying account to starter.
- Unresolvable `checkout.session.completed` events are ignored+logged instead of
  500-ing on every redelivery for days (which degrades the endpoint in Stripe).
- A subscription event whose price no longer matches `STRIPE_PRICE_*` can no
  longer overwrite the stored `plan_name` with NULL; active-but-unresolvable
  plans log a warning instead of silently doing nothing.
- Double-charge fix: creating a new invoice Checkout Session now expires the
  previous one, so at most one payable link exists per invoice (sessions stay
  payable ~24h — an emailed link plus a pay-page session were two live charges).
- `charge.refunded` is now handled: refunds insert negative payment rows
  (cumulative-safe for partial refunds) so a refunded invoice no longer stays
  "paid" and AR/aging stops overstating collections.
- The platform billing webhook now has a fake-conn test suite
  (`tests/test_billing_webhook.py`).

Operations:
- **DB connection pool** (`api/deps.py`): bounded per-instance pool with
  keepalives, `connect_timeout`, and a per-statement timeout — previously every
  request opened a fresh connection with no timeout, and 2 instances + the
  in-process scheduler could exhaust a small managed Postgres under burst.
- `/api/health` now does `SELECT 1` (503 when the DB is unreachable) so Render's
  deploy gate and instance health actually reflect reality.
- Stale-run reconcile also sweeps rows orphaned at `queued` (a restart between
  the run INSERT and the in-memory APScheduler job start left phantom pending
  runs forever), and `RUN_MAX_SECONDS=0` no longer turns the sweep into
  "fail every live backfill after 1 second".
- `apscheduler` pinned `<4` (4.x removes `BackgroundScheduler`; Render rebuilds
  deps from scratch each deploy, so the floor alone would eventually brick a
  routine redeploy).
- `render.yaml` now declares all six Stripe env vars as `sync: false`
  placeholders so a fresh deploy prompts for them.
- Doc rot fixed: `.env.example` no longer advertises the unwired Attom provider
  and regained the `DEMO_PROVIDER`/`DEMO_API_KEY` lines; `RENDER_DEPLOYMENT.md`
  now names `JWT_SECRET_KEY` (the variable the code actually reads).

Frontend:
- Failed logins no longer trigger a page reload that wipes the error message
  (401s from `/auth/login` and `/auth/oauth/*` surface to the form; all other
  401s still clear the token and bounce to `/login`).
- A Vercel **production** build now fails loudly if `NEXT_PUBLIC_API_URL` is
  unset (it used to build green and ship every API call pointed at
  `http://127.0.0.1:8000`). Trailing slashes on the var are normalized.
- `middleware.ts` migrated to the Next 16 `proxy.ts` convention (the deprecated
  name would stop working at the next major, silently dropping the noindex
  header that keeps shared quote/pay links out of search engines).
- Dead deep-link on the calls page (`/settings?tab=automation`) now points at
  the real tab.

## Launch checklist (environment, not code)

1. **Stripe (subscriptions)**: set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_STARTER/
   GROWTH/PRO`, `STRIPE_BILLING_WEBHOOK_SECRET`. Create a *platform* webhook
   endpoint → `/api/public/stripe/billing-webhook` subscribed to
   `checkout.session.completed`, `customer.subscription.created/updated/deleted`.
   Verify the Price amounts equal the advertised $49/$129/$249.
2. **Stripe (invoice payments)**: set `STRIPE_WEBHOOK_SECRET` from a *Connect*
   endpoint ("events on connected accounts") → `/api/public/stripe/webhook`,
   subscribed to `checkout.session.completed`, `payment_intent.succeeded`,
   `account.updated`, **and `charge.refunded`** (new — required for refund
   mirroring).
3. **Email**: `RESEND_API_KEY` + `RESEND_FROM_EMAIL` (domain verified in Resend).
4. **Vercel**: `NEXT_PUBLIC_API_URL` set in Production (build now enforces this).
5. **JWT**: confirm the dashboard `JWT_SECRET_KEY` is the live value before any
   blueprint sync (`generateValue` would rotate it and log everyone out).
6. Optional: `TWILIO_*` for SMS/calls, `PUBLIC_SAMPLE_ACCOUNT_ID` for the
   landing-page widget, paid pipeline keys.

## Known gaps deliberately left for follow-up

- **No Stripe reconciliation poller**: a `customer.subscription.deleted` that
  fails delivery for >3 days grants paid access until manually fixed. A daily
  tick comparing `account_billing` rows against Stripe would close it.
- **No event-ordering guard** on subscription webhooks: an errored-then-
  redelivered older `active` event can briefly resurrect a cancelled plan.
  Comparing `event.created` to the row's `updated_at` would close it.
- `apply_plan` resets modules to raw plan defaults, discarding the
  business-type intersection applied at provisioning (a billing event re-enables
  modules a preset ships off, and wipes owner toggles — the latter documented).
- **Inbound SMS on the shared global number** matches senders across all
  accounts (last-10-digits, most-recent-outbound tiebreak) — deliberate, but a
  shared household number can misdeliver a reply into another tenant's timeline.
  Prefer log-and-drop when more than one account matches.
- Rate limiting (other than login lockout) is in-memory per process — effective
  limits double across 2 instances and reset on deploy. Fine for now; move to
  Postgres/Redis if abuse appears.
- `requirements.txt` has floors but no lockfile — deploys are not byte-for-byte
  reproducible. Consider `pip freeze` into a constraints file.
- 48 `react-hooks` lint errors (correctness-class: setState-in-effect, render
  impurity) across ~30 files — none crash today; they will bite under React
  Compiler/StrictMode. `next build` no longer runs ESLint, so they don't block.
- FastAPI `/docs` + `/openapi.json` are public (surface disclosure only);
  CORS allowlist is hardcoded and includes localhost origins in prod.
- Cross-tenant *dangling references* (`assigned_to`, `property_id` on tasks/
  invoices/quotes/expenses) are accepted without validation — downstream reads
  all re-scope so nothing leaks; validate alongside future work.
