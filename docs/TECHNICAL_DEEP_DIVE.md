# Axon CRM — Technical Deep Dive

> A ground-up, implementation-level reference for how this application actually
> works: every subsystem, the data that flows between them, the exact math and
> SQL that drive scoring and automation, and the design decisions baked into the
> code. This complements the top-level [`README.md`](../README.md) (product-level
> overview) and the focused docs in this folder; where the README says *what*,
> this document says *how* and *why*, down to the function.

---

## Table of Contents

1. [System Shape & Runtime Topology](#1-system-shape--runtime-topology)
2. [The Central Data Model](#2-the-central-data-model)
3. [Configuration & Environment](#3-configuration--environment)
4. [Authentication & Authorization](#4-authentication--authorization)
5. [Multi-Tenancy: Accounts, Plans, Modules, Business Types](#5-multi-tenancy-accounts-plans-modules-business-types)
6. [The Data Acquisition Pipeline](#6-the-data-acquisition-pipeline)
7. [The Rule-Based Scoring Engine](#7-the-rule-based-scoring-engine)
8. [Predictive Scoring (ML Subsystem)](#8-predictive-scoring-ml-subsystem)
9. [The Geo Layer ("Juncto")](#9-the-geo-layer-juncto)
10. [Workflow Automation Engine](#10-workflow-automation-engine)
11. [The Background Scheduler](#11-the-background-scheduler)
12. [Money: Quotes, Invoices, Payments, Bookkeeping](#12-money-quotes-invoices-payments-bookkeeping)
13. [Vertical Child Objects](#13-vertical-child-objects)
14. [Messaging, Notifications & Two-Way SMS](#14-messaging-notifications--two-way-sms)
15. [Marketing Connectors & Insights](#15-marketing-connectors--insights)
16. [Import / Export](#16-import--export)
17. [The Frontend](#17-the-frontend)
18. [The HTTP API Surface](#18-the-http-api-surface)
19. [Cross-Cutting Concerns](#19-cross-cutting-concerns)
20. [Deployment & Operations](#20-deployment--operations)
21. [Testing](#21-testing)
22. [Glossary of Non-Obvious Design Decisions](#22-glossary-of-non-obvious-design-decisions)

---

## 1. System Shape & Runtime Topology

Axon is a **two-process, one-database** application plus a set of offline CLIs.

```
┌──────────────────────────┐      HTTPS/JSON        ┌───────────────────────────┐
│  Next.js frontend         │  ───────────────────▶  │  FastAPI backend (Uvicorn) │
│  (React 19, TS, Tailwind) │  ◀───────────────────  │  api/main.py               │
│  Vercel                   │   Bearer JWT           │  Render / Railway          │
└──────────────────────────┘                        └────────────┬──────────────┘
                                                                  │ psycopg2 (raw SQL)
                                                     ┌────────────▼──────────────┐
                                                     │  PostgreSQL (system of     │
                                                     │  record, per-account rows) │
                                                     └────────────┬──────────────┘
                                                                  │ optional
                                          ┌───────────────────────▼────────────────────┐
                                          │ DuckDB harris_county.duckdb (HCAD, free)     │
                                          └──────────────────────────────────────────────┘

  In-process, inside the FastAPI worker:
    • APScheduler BackgroundScheduler (pipeline runs, nightly ML retrain,
      workflow tick, account rescore, recurring invoices, geo rescore)

  External services (all optional, feature-gated by presence of keys):
    RentCast · Google Geocoding · US Census ACS · NOAA/IEM storm reports ·
    BatchData / Versium (skip-trace + demographics) · Stripe Connect ·
    Resend (email) · Twilio (SMS, inbound + outbound) · Anthropic Claude (OCR)
```

Key architectural facts:

- **No ORM.** All database access is raw SQL through `psycopg2`. Rows come back
  as dicts via the `dict_fetchall`/`dict_fetchone` helpers in `api/deps.py` or a
  `RealDictCursor`. This is a deliberate simplicity choice — the SQL is visible
  at every call site.
- **The backend is a monolith** with a clean internal split: `api/routes/*`
  (thin HTTP handlers), `api/*.py` (shared pure logic — messaging, invoice
  state, lead status transitions, entitlements), and `pipeline/*` (data
  acquisition and scoring, runnable entirely offline via `run_pipeline.py`).
- **Scoring math is DB-free and pure** (`pipeline/scoring.py`,
  `pipeline/geo_scoring.py`, `pipeline/job_value.py`, `pipeline/equity.py`,
  `pipeline/ml/features.py`, `api/messaging.py`). This is what makes the test
  suite fast and deterministic, and it's a recurring pattern: *side-effect-free
  math is separated from the SQL/IO that feeds it.*
- **The scheduler runs inside the web process.** There is no separate worker
  service, no Celery, no Redis. `BackgroundScheduler` runs jobs in a thread pool
  in the same Python process as Uvicorn. Multi-worker safety is achieved with
  **Postgres advisory locks**, not a broker (see §11).
- **The frontend is fully client-rendered behind auth.** The JWT lives in
  `localStorage`; there is no server-side session. Next.js is used mostly as a
  React app shell + routing + public marketing pages.

### The FastAPI entry point (`api/main.py`)

The app is created with a `lifespan` async context manager that, on startup:

1. `scheduler.start()`
2. `load_active_schedules()` — restores every `pipeline_schedules` row with
   `is_active = TRUE` into APScheduler.
3. Registers five recurring cron jobs: nightly ML retrain, daily workflow tick,
   daily account rescore, daily recurring-invoice generation, nightly geo
   rescore.
4. `_check_hcad_source()` — logs a loud (non-fatal) warning if
   `SEED_SOURCE=hcad` but no HCAD data is loaded, so a misconfigured Render
   deploy doesn't silently seed 0 rows.

On shutdown it calls `scheduler.shutdown(wait=False)`.

**CORS** origins are a hardcoded allowlist (localhost dev ports +
`axon-crm-sigma.vercel.app`). Adding a new frontend domain requires editing this
list — it is intentionally *not* env-configurable.

**Router registration** encodes the entitlement model directly:

- Core routers (`auth`, `oauth`, `leads`, `record_fields`, `segments`,
  `messaging`, `notes`, `history`, `export`, `tasks`, `pipeline`) are mounted
  ungated.
- Feature routers are wrapped in a `require_module(...)` dependency at mount
  time: `expenses`/`bookkeeping` → `bookkeeping`, `invoices` → `invoicing`,
  `quotes` → `quotes`, `stripe_payments` → `invoicing`, `policies`/`orders`/
  `appointments` → their own module, `hcad`/`imports`/`ml` → `prospecting`,
  `workflows` → `automation`, `insights` → `marketing`, `map` → `map`.
- **Public routers** (`invoices.public_router`, `quotes.public_router`,
  `stripe_payments.public_router`, `twilio_inbound.public_router`,
  `public_intake.public_router`) are always ungated — they serve customers,
  Stripe/Twilio webhooks, and the insurance website, none of which have a seller
  login. Gating them would also collide the `?token=` param with
  `get_current_user`'s query-param fallback.
- `pipeline.py` is **mixed-concern**: the Kanban read endpoints are core, but
  its data-acquisition endpoints gate per-endpoint on `prospecting`.
- `objects.py` and `connections.py` are ungated at the router but check
  `account_has_module` internally per aggregate block.

---

## 2. The Central Data Model

The schema is defined by **53 numbered migrations** in `db/migrations/`, run in
filename order by `db/migrate.py`, which tracks applied files in a
`schema_migrations` table. **`db/schema.sql` is NOT authoritative** — it predates
the migration system and only mirrors migration `0000`.

### The `properties` table is the spine of everything

Despite the name, `properties` is the **universal lead/record table**. A "lead,"
a "policyholder," a "retail customer," and a "B2B deal" are all rows in
`properties` — the business type just changes the vocabulary and which columns
matter. Its columns accreted across migrations:

| Group | Columns (representative) | Source migration |
|---|---|---|
| Identity/location | `address, city, state, zip, latitude, longitude, geohash` | 0000 |
| Property facts | `year_built, square_footage, garage_spaces, garage_type, lot_size, property_type, estimated_value, estimated_equity, last_sale_date, last_sale_price` | 0000, later |
| Owner | `owner_name, owner_occupied, ownership_years, mailing_address` | 0000, 020 |
| Enrichment | `zip_median_income, permit_count_24mo, has_pool, has_cracked_slab, hcad_neighborhood_code/name` | 007, 014, 026, 028 |
| Contact | `contact_name, contact_phone, contact_email` | 008, 018, 019 |
| Scoring | `lead_score, score_grade, vertical, score_updated_at, enrichment_flags (JSONB)` | 0000 |
| Storm | `last_storm_date, last_storm_type, hail_size_in, storm_count_24mo` | 027 |
| Demographics/Versium | `owner_age, length_of_residence_years, est_household_income, life_stage, refi_date, home_improvement_flag, credit_rating, has_children, gardening_flag, estimated_net_worth, loan_to_value, marital_status, occupation, senior_in_household, pets_flag, decorating_flag, credit_lines_count, mortgage_rate_type` | 028, 029 |
| Neighborhood | `neighborhood_value_ratio, neighborhood_value_pctile` | 025 |
| Pipeline/CRM | `status, stage_moved_at, assigned_to, lead_source, estimated_job_value, archived_at` | 003, 004, 013, 016, 030 |
| Geo | `geocode_source, geocode_confidence, h3_r8, subdivision, cluster_id` | 049, 050, 051 |
| Tenancy | `account_id` | 017 |

The full writable column allowlist lives in `pipeline/db.py::ALL_COLS`; it doubles
as an **injection guard** — any dynamic column reference (e.g.
`fetch_missing_any`) validates against it before interpolation.

### The NULL-only upsert (`pipeline/db.py::upsert_properties`)

This is the single most important invariant in the pipeline. When enrichment
writes back to `properties`:

```sql
INSERT INTO properties (account_id, <non-null cols>)
VALUES (...)
ON CONFLICT (account_id, address, zip) DO UPDATE SET <col = EXCLUDED.col ...>
```

with two rules:

1. **Only non-`None` values are included in the write.** A partial enrichment
   step (say, storm data) never clobbers fields a prior step (say, RentCast) set.
2. **`enrichment_flags` is *merged*, not overwritten:**
   `enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags`.

The conflict key `(account_id, address, zip)` means each account keeps its own
copy of a property — two agencies working the same street have independent rows.
`address` and `zip` are excluded from the `DO UPDATE SET` (they *are* the key).

`fetch_missing_field` / `fetch_missing_any` are the cost-control queries: a paid
step only pulls rows where its target columns are still `NULL`, so money is spent
only on genuine gaps. With `selected_only=True` they further restrict to rows the
selection step flagged `enrichment_selected = TRUE`.

### Complete table inventory

| Table | Purpose | Migration |
|---|---|---|
| `properties` | Universal lead/record spine | 0000 |
| `contact_notes` | Free-text notes on a lead | 0000 |
| `contact_history` | Activity log (calls, messages, automations); carries `channel/direction/body` for two-way SMS | 0000, 048 |
| `users` | Team members (role, is_active, account_id) | 0001 |
| `accounts` | Tenants (name, business_type, plan) | 017 |
| `oauth_identities` | Google/Apple identity → user linkage | 035 |
| `tasks` | To-dos, optionally linked to a lead | 0002 |
| `pipeline_stages` | Per-account custom Kanban columns (`is_terminal`, `is_default`) | 011 |
| `stage_transitions` | Audit of every status change (cycle-time analytics) | 010 |
| `pipeline_schedules` | Recurring pipeline-run definitions | 0004 |
| `pipeline_runs` | Pipeline execution history + `result_json` | 0004 |
| `signal_events` | Timing signals detected by the pipeline | 022 |
| `workflow_rules` | Automation rules | 009, generalized in 042 |
| `workflow_rule_firings` | Idempotency ledger for scheduled rules | 042 |
| `segments` | Saved named filter sets | 042 |
| `record_field_defs` | Account-defined custom fields | 041 |
| `message_templates` | Reusable email/SMS templates | 044 |
| `expenses` | Expense log | 005 |
| `invoices`, `invoice_line_items`, `invoice_payments` | Invoicing/AR | 006, recurrence 045, public token 036 |
| `quotes`, `quote_line_items` | Quote builder | 023, public token 024 |
| `stripe_accounts`, `stripe_webhook_events` | Connect accounts + webhook idempotency | 047 |
| `policies`, `orders`, `appointments` | Vertical child objects | 043 (031 created & 037 dropped an earlier appointments table) |
| `account_plans` | Plan name + per-module override map (JSONB) | 039 |
| `connections`, `social_imports`, `social_metrics`, `social_posts` | Marketing connectors | 032, 033 |
| `lead_feature_snapshots`, `model_versions` | ML training data + model registry | 034 |
| `vertical_geo_config`, `lead_geo_scores`, `service_areas`, `geocode_queue` | Geo layer | 049 |
| `customer_clusters` | DBSCAN cluster output | 050 |
| `prospect_pulls` | Prospecting cost-control ledger | 051 |
| `geo_events` | Event polygons (hail swaths, HOA sweeps) | 052 |
| `hcad_properties`, `hcad_permits`, `hcad_extra_features` | Postgres mirror of HCAD data | 007, 014 |

Migration `017_org_isolation.sql` is the pivotal one: it introduced `accounts`
and backfilled `account_id` onto every pre-existing table. From that point,
**every query filters by `account_id`** — this is the tenancy boundary, enforced
in application SQL rather than Postgres RLS.

---

## 3. Configuration & Environment

`config.py` is the single, heavily-commented source of truth for tunables. It
loads `.env` via `python-dotenv`. Everything is `os.getenv` with a default, so
the app boots with almost nothing set and features **degrade gracefully** (a
missing key means that step no-ops or the endpoint returns 503). Notable groups:

- **Core:** `DATABASE_URL`, `JWT_SECRET_KEY` (hard-required unless
  `ALLOW_INSECURE_DEV_JWT=true`).
- **Property data:** `RENTCAST_API_KEY`, `GOOGLE_GEOCODE_KEY`, `CENSUS_API_KEY`,
  `PERMIT_DB_PATH` (DuckDB), `SEED_SOURCE` (`rentcast` | `hcad`),
  `SEED_PROPERTY_TYPES` (filter to Single Family/Condo/Townhouse/Manufactured),
  `PROPERTY_FIELD_SOURCES`.
- **Enrichment providers:** `CONTACT_PROVIDER`/`DEMO_PROVIDER` (+ keys, base
  URLs, per-ZIP row caps, and optional `*_MIN_GRADE` gates so you only pay to
  skip-trace A/B leads).
- **Scoring:** `DEFAULT_WEIGHTS`, `VERTICAL_WEIGHTS` (8 verticals), `FACTOR_META`
  (labels/descriptions/field mapping), signal thresholds
  (`AGE_SWEET_SPOT_MIN/MAX`, `EQUITY_TARGET`, `NEIGHBORHOOD_RATIO_TARGET`, …),
  `GRADE_BANDS`.
- **ML:** `SCORER_MODE` (`rules`/`shadow`/`learned`), `ML_MIN_TRAINING_LABELS`,
  `ML_STALE_OPEN_DAYS`, `ML_L2/LR/EPOCHS`, `ML_RETRAIN_HOUR`.
- **Geo:** road-circuity factor, proximity decay, density radius/cap, neighbor
  freshness windows, territory gate penalty, blast radius, cluster eps/min-points,
  H3 resolution, prospecting caps, event bonuses.
- **Money/messaging:** Stripe keys + `STRIPE_PLATFORM_FEE_PCT`, Resend, Twilio,
  `APP_BASE_URL` (used to build customer-facing links).
- **AI:** `ANTHROPIC_API_KEY`, `RECEIPT_SCAN_MODEL` (default `claude-haiku-4-5`).
- **Public intake:** `PUBLIC_INTAKE_API_KEY` + `PUBLIC_INTAKE_ACCOUNT_ID` (pins
  every website lead to one agency).

The `.env.example` file documents all of these grouped by concern.

---

## 4. Authentication & Authorization

### Password auth (`api/security.py`, `api/routes/auth.py`)

- Passwords hashed with **bcrypt** via `passlib`'s `CryptContext`.
- JWT signed **HS256** with `JWT_SECRET_KEY`. The module raises `RuntimeError` at
  import time if the key is unset (unless `ALLOW_INSECURE_DEV_JWT=true`, which
  substitutes a well-known dev secret) — a publicly known key would let anyone
  forge owner tokens.
- Token payload: `{sub: str(user_id), username, role, exp}`. **Expiry is 8
  hours** (`ACCESS_TOKEN_EXPIRE_HOURS`). There are no refresh tokens; the user
  re-logs in.
- Login is rate-limited (`api/ratelimit.py`, in-process) to slow brute force.

### Request authentication (`api/deps.py::get_current_user`)

The dependency accepts the token **either** from the `Authorization: Bearer`
header **or** a `?token=` query param. The query-param path exists specifically
for `<a download>` CSV export links, where custom headers can't be set. It
decodes the JWT, loads the `users` row, and 401s if missing/invalid/expired,
403s if `is_active` is false.

`require_owner` narrows to `role in (owner, admin)` for privileged writes (create
users, delete records, edit stages/fields/templates/workflows).

### Social login (`api/oauth_verify.py`, `api/routes/oauth.py`)

Sign in with Google/Apple is **invite-only**: the OIDC ID token is verified
(audience checked against `GOOGLE_OAUTH_CLIENT_ID`/`APPLE_CLIENT_ID`, signature
against the provider's JWKS), then the verified email is matched to an existing
`users` row. It **links, it does not self-register** — a stranger with a Google
account cannot create a tenant. Endpoints return 503 until the client IDs are
set. `oauth_identities` records the provider linkage.

### Frontend auth (`frontend/lib/auth.ts`, `components/AuthGuard.tsx`)

- Token stored in `localStorage` under `axon_token`.
- `<AuthGuard>` wraps protected pages; if `getToken()` is empty it
  `router.replace('/login')` before rendering.
- The API client (`lib/api.ts`) intercepts **any 401**, clears the token, and
  hard-redirects to `/login` — so an expired token anywhere logs you out cleanly.

---

## 5. Multi-Tenancy: Accounts, Plans, Modules, Business Types

### Entitlements (`api/entitlements.py`)

Optional features are grouped into **modules** (`MODULE_KEYS`): `prospecting`,
`map`, `invoicing`, `bookkeeping`, `quotes`, `marketing`, `automation`,
`policies`, `orders`, `appointments`. **Core features are deliberately not
modules** — leads, Kanban, tasks, notes, history, export, custom fields,
segments, and messaging are always on.

Plans bundle modules (`PLAN_CATALOG`):
- `starter` → core only (empty set)
- `growth` → `invoicing, bookkeeping, quotes, automation, appointments`
- `pro` → everything

**Resolution is permissive by design** (`get_account_modules`): start from the
plan's defaults, then apply per-account overrides from `account_plans.modules`
(JSONB). Critically, **an account with no `account_plans` row gets the full
set** — gating can never silently strip access from an un-provisioned account.
Plans *tighten* by explicitly listing a module as `false`.

`require_module(key)` is the FastAPI dependency factory. On failure it returns a
**403 with a structured body** `{detail, module, upgrade: true}` so the frontend
can render an "Upgrade to unlock" prompt instead of a generic error.

### Business types (`api/business_types.py`)

A `BusinessType` preset (frozen dataclass) bundles, per vertical:
- `terminology_overrides` — merged over `BASE_TERMINOLOGY` (lead↔deal↔policy↔
  customer, property↔record↔account, jobValue↔premium↔order value, …). Missing
  keys fall back to the home-services base, which the frontend also ships as a
  final fallback.
- `categories` — the picklist that "verticals" become (service lines, lines of
  business, channels).
- `property_based` — whether the property pipeline/map/property UI apply.
- `default_modules` — provisioning defaults.
- **Provisioning pack (Phase 6):** `default_stages`, `default_fields`,
  `default_workflows`, `default_templates`, `kpis`, `objects`, `list_columns`.

Five presets ship: `home_services` (base, property-based), `general_sales`,
`professional_services`, `insurance_agency`, `retail`. The insurance preset is
the richest — it seeds a prospect→quoted→bound→renewal→lost stage set, custom
fields (`current_carrier`, `x_date`, `household_size`), the full **X-date renewal
automation suite** (`_INSURANCE_WORKFLOWS`: date-offset rules at −90/−30/−7 days
plus a client-facing renewal reminder template with SMS→email fallback), and
policy/appointment child objects.

Switching business type (`PATCH /api/account/business-type` with
`apply_defaults=true`) seeds the missing pieces of the provisioning pack. This is
how one codebase becomes a different product without a fork.

The frontend mirrors all this: `useEntitlements` caches the module map + plan and
exposes `hasModule()`; `useTerminology` resolves the per-account vocabulary/KPI/
column config; `nav.ts` hides nav items whose module isn't enabled.

---

## 6. The Data Acquisition Pipeline

`run_pipeline.py` (CLI) and `api/scheduler.py::_run_pipeline` (in-app) run the
**same ordered enrichment sequence** for a ZIP (or a fanned-out HCAD region).
Each step is a module under `pipeline/`. The canonical order, with the exact
step numbering used in the scheduler's logs:

| # | Module | What it does | Cost |
|---|---|---|---|
| 1 | `seed.py` | Seed addresses: RentCast `/properties` scan (default), local HCAD mirror (`--seed-source hcad`), or CSV. Filters to `SEED_PROPERTY_TYPES`. Can auto-expand the search radius when a ZIP returns < `SEED_EXPAND_THRESHOLD` rows (`geo_expand.py`). | paid/free |
| 2 | `census.py` | Median household income per ZIP from Census ACS (`B19013_001E`). | free |
| 3 | `geocode.py` | Address → lat/lng via Google Geocoding. | paid |
| 4 | `hcad_enrichment.py` | **Free backfill first**: property/owner/mailing fields from HCAD DuckDB (or Postgres mirror), so paid steps only fill genuine gaps. | free |
| 4.5 | `select.py` | *(capped runs only)* Top-N / radius trim **after free steps, before paid ones** — marks `enrichment_selected`. | — |
| 5 | `property.py` | RentCast paid enrichment — only fills columns still NULL after HCAD. | paid |
| 6 | `permits.py` | 24-month permit counts from HCAD. | free |
| 6.5 | `storm.py` | Match NOAA/IEM hail/wind/tornado history to geocoded points within `STORM_MATCH_RADIUS_MI`. | free |
| 6.75 | `neighborhood.py` | Recompute value-per-sqft ratios vs. each geohash block (account-wide; must precede scoring). | free |
| 7 | `scorer.py` | Score 0–100 + grade A–D; also backfills `estimated_equity` and `estimated_job_value`; captures ML feature snapshots. | free |
| 7.5 | `select.py::trim_to_top_n` | *(capped runs)* Precision cut to exact top-N using real scores, before paid skip-trace. | — |
| 8 | `contact.py` | Skip-trace contact enrichment (BatchData/Versium), optionally grade-gated. | paid |
| 8.5 | `demographics.py` | Household demographics/life-events append, optionally grade-gated. | paid |
| 9 | `signals.py` | Diff sale/permit/storm vs. previous run baseline, record `signal_events`, fire `signal_event` workflow rules. | free |

Then a `coverage.py::fill_rates` snapshot is written into the run's
`result_json` for the frontend.

### The provenance strategy

The ordering is not arbitrary — it's a **cost-optimization strategy**
([`docs/COST_OPTIMIZATION.md`](COST_OPTIMIZATION.md)): free HCAD data runs before
paid RentCast; selection/trim happen between free and paid tiers; skip-trace and
demographics (the most expensive per-row calls) run last and can be gated to only
A/B leads. Combined with NULL-only upsert, the pipeline spends money only where
free sources left a gap **and** the lead cleared the grade bar.

### Cancellation & region fan-out

`_run_pipeline` checks `is_cancelled(run_id)` between every step (cancel flags are
an in-process `set`; `DELETE /api/pipeline/runs/{id}` sets one). A **region run**
(`region_id`, an HCAD named neighborhood) resolves to every ZIP the region
touches and runs the full sequence per ZIP, seeding each from free HCAD data;
results are collected under `by_zip`. A plain ZIP run is just a single-element
list, and preserves the original single-ZIP `result_json` shape for the UI.

### HTTP robustness

All outbound provider calls go through `pipeline/http.py`, which retries
`HTTP_RETRIES` times with exponential backoff (`HTTP_BACKOFF`). Providers are
pluggable: `contact.py`, `demographics.py`, `property_provider.py`, and
`geocode_provider.py` each expose a `PROVIDERS` registry keyed by env var.

---

## 7. The Rule-Based Scoring Engine

The deterministic scorer is the product's core IP. All math lives in
`pipeline/scoring.py` (pure, DB-free); `pipeline/scorer.py` is the DB wrapper.

### How a score is computed

`_compute_score(row, weights)` is a **weighted sum of normalized signals**:

```python
score = sum(weight * signal_fn(row[field]) for key, weight in weights.items()
            if weight) * 100
```

Each `signal_fn` returns a float in **[0.0, 1.0]**; each weight is a fraction;
**weights must sum to 1.0 per vertical**, so the score lands in **[0, 100]**.
Zero-weight factors are skipped (numerically identical to including them, but
cheaper and cleaner in the explanation). The grade comes from `GRADE_BANDS`:
A ≥ 75, B ≥ 55, C ≥ 35, else D.

### The signals (`_SIGNAL_FNS`)

Every signal is a small, testable function. The shapes:

- **`_age_signal`** — 1.0 in the 15–30-year renovation sweet spot; ramps up
  below it (`age / 15`); decays above it (`1 − (age−30)/20`, floored at 0).
- **`_sale_signal` / `_storm_signal` / `_refi_signal`** — linear recency decay:
  1.0 today → 0.0 at the window edge (24 mo for sale/storm, 36 mo for refi).
- **`_equity_signal` / `_garage_signal` / `_income_signal` / `_permit_signal` /
  `_tenure_signal`** — linear ramp to a target, capped at 1.0
  (`min(1, value/target)`).
- **`_neighborhood_signal`** — `(ratio − 1) / (1.3 − 1)`, clamped [0,1]. A home
  at its block median scores 0; 30%+ above scores 1.0. A **finer-grained locality
  signal than ZIP income**, computed per geohash cell (falling back to ZIP median
  for cells with fewer than `NEIGHBORHOOD_MIN_MEMBERS` homes).
- **Binary flags** — `_pool_signal`, `_slab_signal`, `_home_improvement_signal`,
  `_children_signal`, `_gardening_signal` → 1.0 if present.
- **`_absentee_signal`** — 1.0 only when `owner_occupied is False`; **unknown
  scores 0** (missing is not assumed absentee).
- **Ordinal lookups** — `_credit_signal` (A=1.0, B=0.75, C=0.40, D=0.10),
  `_life_stage_signal` (new_mover=1.0, retiree=0.6, established=0.4, other=0.1).

### Per-vertical weight profiles (`config.VERTICAL_WEIGHTS`)

Each of the 8 built-in verticals has a hand-tuned weight profile summing to 1.0,
using `weights.get()` so a profile only carries the signals that matter for it.
Examples that show the domain logic:
- **roofing** leans on `storm` (0.20) and `age` (0.20) — storm damage is the most
  direct demand driver.
- **epoxy_flooring** weights `garage` (0.20, the work surface) and `slab` (0.15,
  a confirmed job from HCAD).
- **pool_maintenance** requires `pool` (0.20) and `children` (0.10).
- **landscaping** front-loads `sale` (0.25, new owners re-landscape) and
  `neighborhood` (0.15, high-value blocks invest in curb appeal).

An unknown/None vertical falls back to `DEFAULT_WEIGHTS`. **Adding a vertical is
adding a dict key** — no code change.

### Explainability (`explain_score`)

`GET /api/leads/{id}/score-explanation` reuses the **exact same signal
functions** to produce a per-factor breakdown: each factor's normalized signal
(0–1), its weighted point contribution (`weight × signal × 100`), a
human-readable label/description from `FACTOR_META`, the top-3 drivers, and a
one-line plain-language summary. Because it calls the production functions, the
breakdown **can never drift from the actual score** — this parity is pinned by
`tests/test_scoring.py`. `describe_vertical` similarly derives a vertical's
profile description purely from its weights.

### Derived-value backfills

During scoring, `scorer.score_zip` also:
- Backfills `estimated_equity` via `pipeline/equity.py::estimate_equity` (uses
  value − mortgage/sale data, or `EQUITY_FALLBACK_PCT` × value = 60%) — **only
  when NULL**, never overwriting an enriched/manual value, and before scoring so
  the equity signal reads it.
- Backfills `estimated_job_value` via `pipeline/job_value.py` using the
  per-vertical `JOB_VALUE_MODEL` (a flat base plus per-sqft/per-garage/per-lot
  terms that only apply when the underlying field is known), or a fallback of
  `JOB_VALUE_FALLBACK_PCT` (4%) of home value — **only when the user hasn't set
  one.**

---

## 8. Predictive Scoring (ML Subsystem)

`pipeline/ml/` is an **optional per-account learned model** that predicts
conversion probability from the tenant's own won/lost history, using a
**dependency-free pure-Python logistic regression** (`model.py`) — no
scikit-learn/numpy required (seams exist for them later).

### The three modes (`SCORER_MODE`)

- **`rules`** (default) — deterministic scoring only; ML computes and stores
  feature snapshots but changes nothing user-facing.
- **`shadow`** — also computes and stores the learned probability alongside the
  rules score, without changing the displayed grade. Use to validate lift before
  flipping the UI.
- **`learned`** — surfaces the learned conversion probability to users.

`scorer.score_zip` calls `_apply_ml` in a try/except so **any ML failure is
non-fatal** to the core pipeline — a stale champion just stays active.

### Feature engineering (`ml/features.py`)

The signature design decision is **missing-awareness**. Every optional continuous
field emits *two* features: a standardized value (0 when absent) **and a
`<name>__missing` indicator**. This lets the model learn "this signal is simply
unknown for this lead" instead of treating absent as a real zero — so a model
trained on accounts without the Versium life-event block stays valid, and lights
up the same feature slots automatically if that account later buys the data.

`feature_names()` is **deterministic and fixed-order** (a model trained today
applies tomorrow). It includes: ~17 continuous features (home age, log value/
equity, months-since-sale/storm/refi, neighborhood ratio/pctile, demographics)
each with a missing flag; ~9 binary flags with missing flags; 2 ordinal lookups
(credit, life stage); one-hot vocabularies for `vertical` and `lead_source` (with
`__other` buckets for unseen values); and 3 **behavioral** features
(`crm_touches`, `days_in_pipeline`, `quotes_sent`) that are injected at score
time (not snapshotted, since they evolve) and carry no missing flag (0 is
meaningful).

`snapshot_payload` persists a JSON-serializable superset of raw fields into
`lead_feature_snapshots`, decoupling storage from engineering so re-engineering
never needs a re-snapshot.

### Labels (`ml/labels.py`, `ml/snapshot.py`)

Outcomes come from lead status: won/converted → positive; lost → negative. The
subtle bit: an **untouched open lead older than `ML_STALE_OPEN_DAYS` (120) is
treated as a soft loss** (negative label), so the model learns from leads that
quietly went nowhere rather than only from explicit losses.

### Training & promotion (`ml/train.py`)

`train_all` (nightly) backfills outcome labels, retrains the **global pooled
model**, then retrains any account with ≥ `ML_MIN_TRAINING_LABELS` (40) of its own
labeled snapshots.

`train_scope` does one scope:
1. Build the dataset; bail with `insufficient_labeled_data` if under the minimum
   (that scope falls back to the pooled model, then to rules).
2. **Time-based split** (`_split`): train on older outcomes, test on newer. A
   random split would leak future information; the realistic question is "trained
   on the past, do my top-ranked *future* leads convert?" A guard falls back to
   evaluating on the train fold if the test fold lacks both classes.
3. Fit `LogisticModel` (L2-regularized gradient descent, `ML_L2/LR/EPOCHS`).
4. Evaluate on the holdout (`metrics.evaluate` → ROC-AUC, etc.).
5. **Champion/challenger promotion**: promote only if there's no incumbent or the
   challenger's AUC ≥ the champion's. Otherwise keep the champion.

`model_versions` is the registry; `registry.save_and_activate` stores the fitted
weights + metrics and flips the active flag. `predict.score_and_store` writes the
learned probability back in shadow/learned mode.

`GET /api/ml/status` reports mode + active-model metrics + label counts;
`POST /api/ml/retrain` (owner) forces it; `GET /api/ml/insights/leads` returns a
"hot untouched leads" + revenue-forecast view.

---

## 9. The Geo Layer ("Juncto")

A spatial scoring layer ([`docs/geo_scoring.md`](geo_scoring.md)) that scores a
lead by **where it sits relative to the tenant's book of business**, then blends
that with the property score. Pure math in `pipeline/geo_scoring.py`; DB glue in
`geo_score_store.py`, `geo_cluster_store.py`. **PostGIS-free** — everything is
haversine + pure-Python geometry, so it runs on vanilla managed Postgres.

### The four components (each 0–100)

- **proximity** — exponential decay on *road* distance (haversine ×
  `GEO_ROAD_CIRCUITY`=1.3, an MVP stand-in for a routing engine) to the nearest
  active customer: `100·exp(−d/2km)`.
- **density** — count of active customers within `GEO_DENSITY_RADIUS_M` (1600m),
  linear and capped at `GEO_DENSITY_CAP` (8) → 100.
- **neighbor** — "visible-work contagion": 100 if a nearby job completed within
  `GEO_NEIGHBOR_FRESH_DAYS` (60), linear decay to 0 at `DECAY_DAYS` (90).
- **territory** — a **multiplicative gate**: 1.0 inside the service area, a heavy
  but non-zero penalty (`GEO_TERRITORY_GATE_OUT`=0.1) outside, so out-of-area
  leads sink without vanishing (they still surface in an expansion view).

"Customers" are properties in `CUSTOMER_STATUSES = (won, converted)`.

### Blending (`score_geo` → `blend_final_score`)

```
base   = (route·proximity + route·density + neighbor·neighbor) / (2·route + neighbor)
geo    = min(100, base + event_bonus) · territory_gate
final  = (1 − geo_blend)·property_score + geo_blend·geo
```

Normalizing by the applied weight sum keeps `geo` in [0,100] for any weights, so
weights are pure relative dials. `geo_blend` is per-vertical (recurring services
lean on geo more than one-time projects: `GEO_BLEND_RECURRING`=0.35 vs
`GEO_BLEND_PROJECT`=0.25). Config comes from the `vertical_geo_config` table,
falling back to `GEO_DEFAULT_CONFIG`. The full component breakdown is stored as
JSONB in `lead_geo_scores` so the UI can explain the geo score.

### Service area (`derive_service_area` / `in_service_area`)

The service area is either **user-drawn** (strict point-in-polygon) or **derived**
as the **convex hull of customer points** (Andrew's monotone chain). For a derived
hull, membership allows a `GEO_SERVICE_AREA_BUFFER_KM` (2km) buffer so leads just
past the edge aren't wrongly gated out. **No polygon → everyone is "inside"** —
never penalize when there's no territory to judge against. Geometry uses GeoJSON
`(lng, lat)` order throughout so polygons round-trip through the DB unchanged.

### Clustering, heatmap, prospecting, events

- **Clustering** (`geo_clustering.py`) — pure-Python **DBSCAN** over haversine
  distance (`GEO_CLUSTER_EPS_M`=800, `MIN_POINTS`=3), a stand-in for
  `ST_ClusterDBSCAN`. Output → `customer_clusters`, and `cluster_id` tagged on
  leads.
- **Heatmap** (`geo_h3.py`) — optional **H3 hex** aggregation (resolution 8 ≈
  0.74 km²). Requires the `h3` package; degrades gracefully (heatmap reports
  `available=false`) when it isn't installed.
- **Cluster-seeded prospecting** (`prospecting.py`) — pulls pre-geocoded prospects
  from a property provider around a cluster seed, dedupes against existing leads
  (within `PROSPECT_DEDUPE_M`=25m), ingests and scores them. **Cost controls:**
  skip a seed whose H3 cell was pulled within `PROSPECT_SKIP_DAYS` (14), cap
  `PROSPECT_MAX_PULLS_PER_CYCLE` (20) and `PROSPECT_MAX_RECORDS` (500) per pull;
  the `prospect_pulls` table is the ledger.
- **Neighbor-of-won-job** — on a win, `api/neighbors.py::create_neighbor_task`
  flags nearby uncontacted leads as an "N neighbors of your new customer"
  door-knock task (see §10 chain).
- **Event polygons** (`geo_events`) — hail swaths / HOA sweeps / heat waves add an
  additive geo bonus (`GEO_EVENT_BONUS` by type, e.g. hail_swath=40) to leads
  inside an active polygon; `best_event_for_point` picks the highest-bonus
  containing event via ray-casting.

### When geo recomputes

- **On a new customer** (status → won/converted): `lead_logic` enqueues
  `enqueue_customer_geo_rescore`, which refreshes the derived service area and
  re-scores leads within `GEO_RESCORE_RADIUS_KM` (8km) of the new customer —
  **off the request path** so the status change never blocks on geo.
- **Nightly** (`run_geo_rescore_tick`): drain the geocode queue, backfill H3,
  refresh service areas, rescore all leads, recompute clusters — per account,
  isolated so one account's failure doesn't block others.

---

## 10. Workflow Automation Engine

`api/workflow_engine.py` evaluates `workflow_rules` on lifecycle events and a
daily tick. A rule has a `trigger_type`, `trigger_config` (JSONB), `action_type`,
`action_config` (JSONB), optional `vertical` scope, `is_active`, `created_by`,
and `account_id`.

### Trigger types

| Trigger | Fired by | Matching |
|---|---|---|
| `status_change` | `lead_logic.apply_status_change` | `from_status`/`to_status` in config |
| `signal_event` | `pipeline/signals.py` | `signal_type` (just_sold/new_permit/storm_event) |
| `lead_imported` | contact/order imports | fires once per newly-inserted lead |
| `quote_event` | quote send/accept/decline | `event` in config |
| `policy_event`/`order_event`/`appointment_event` | child-object routes | `event` = created or new status |
| `date_offset` | daily tick | anchor date + offset within a 3-day window |
| `inactivity` | daily tick | last contact/creation older than N days |

### Action types (`_execute_action`)

- **`create_task`** — insert a `tasks` row with a computed due date.
- **`log_history`** — insert a `contact_history` row.
- **`move_lead_status`** — call `lead_logic.apply_status_change`, which **chains
  into `status_change` rules**. This is how one quote-accepted event can drive the
  whole pipeline response (quote accepted → lead to won → "schedule the job" task
  → neighbor door-knock task).
- **`send_notification`** — email the *rule's creator* about the matched lead
  ("notify me"). Fails soft if Resend isn't configured.
- **`send_template`** — render `message_templates` against the *record's own
  contact* and send. Supports single-template or **multi-channel with fallback**
  (`sms_first`/`email_first`/`both`): sends on the preferred channel, falls back
  to the other when the contact lacks an address for it or the provider isn't
  configured. A provider error on one channel doesn't void another channel's
  completed send; the error is only re-raised (to release the firing claim for
  retry) when nothing was delivered at all. `extra` context (e.g. a policy row)
  injects child-object merge fields into a renewal reminder.

### Idempotency: the firings ledger

Scheduled rules (`date_offset`, `inactivity`) run in a daily sweep with a 3-day
catch-up window, so the same rule/target could match on multiple ticks.
`workflow_rule_firings` is the dedup ledger: `_claim_firing` does an
`INSERT ... ON CONFLICT DO NOTHING RETURNING id` on
`(rule_id, account_id, target_type, target_id, fire_key)`. If the insert returns
nothing, the firing already happened and the action is skipped.
- For `date_offset`, `fire_key` is the **anchor date** — so each policy's renewal
  fires exactly once per expiration date per offset.
- For `inactivity`, `fire_key` is the **last-touch date** — so one firing per
  lapse episode; a new contact re-arms the rule for a future lapse.

On action failure, the code `conn.rollback()`s so the unclaimed firing is
**released and retried next tick**.

### Security: the date-source whitelist

`date_offset` rules can target `properties`, `policies`, `orders`, or
`appointments`. `DATE_TRIGGER_SOURCES` is a **hardcoded whitelist** of tables and
their allowed date columns; the SQL is built *only* from these entries, never
from user input, so a malicious rule config cannot inject identifiers. Each source
declares its `id_col`, `lead_col` (the linked property actions run against), and
an `extra_where` (e.g. skip archived leads, skip child rows with no property).

### Defaults

`VERTICAL_DEFAULTS` in `workflow_engine.py` provides per-vertical starter rules
(e.g. roofing: "schedule roof inspection" on contacted, "order materials" on
won). At import time these are extended with universal `_SIGNAL_DEFAULTS`
(just-sold/new-permit follow-ups), `_QUOTE_DEFAULTS` (quote sent/accepted →
move status, declined → ask why), and `_IMPORT_DEFAULTS` (new imported lead →
outreach task). `POST /api/workflows/seed-defaults` installs them.

---

## 11. The Background Scheduler

`api/scheduler.py` holds a single module-level `BackgroundScheduler(timezone=UTC)`
running jobs in a thread pool inside the FastAPI process. Registered jobs:

| Job | Schedule | Purpose |
|---|---|---|
| `pipeline_schedule_{id}` | per-schedule cron (day/hour) | Recurring data-acquisition run |
| `ml_retrain_nightly` | `ML_RETRAIN_HOUR`:00 UTC | Label backfill + model retrain |
| `workflow_daily_tick` | `WORKFLOW_TICK_HOUR`:15 UTC | Evaluate date_offset/inactivity rules |
| `recurring_invoices_daily` | :30 UTC | Generate due recurring invoices |
| `account_rescore_daily` | :45 UTC | Rescore non-property accounts (renewal proximity, RFM) |
| `geo_rescore_nightly` | :50 UTC | Drain geocode queue, refresh areas, rescore, recluster |

The **:15 → :30 → :45 → :50 ordering is deliberate**: renewal-proximity scores
are fresh before date rules read them; property scores are fresh before the geo
blend reads them.

### Multi-worker safety via advisory locks

Because the scheduler runs in *every* Uvicorn worker, a multi-worker deploy would
otherwise run each daily job N times. Each tick takes a **Postgres advisory lock**
(`pg_try_advisory_lock` with a fixed key per job — `742026001`–`742026004`); if it
can't acquire it, another worker is running and it skips. The firings ledger would
make double-runs *safe* anyway, but the lock avoids the wasted concurrent scan.
`misfire_grace_time=3600` tolerates a late fire.

### Pipeline execution

`_run_pipeline` is described in §6. `enqueue_run`/`enqueue_region_run` fire one-off
runs into the thread pool; `_scheduled_job` wraps a scheduled run by first
creating the `pipeline_runs` row. Run status transitions `running` → `done` /
`failed` / `cancelled`, with `result_json` carrying per-step counters and a
coverage snapshot.

---

## 12. Money: Quotes, Invoices, Payments, Bookkeeping

### Quotes (`routes/quotes.py`, module `quotes`)

Quotes have line items and a **public token** (`024`). Lifecycle: created →
sent (email/SMS) → viewed (public GET stamps `viewed_at`) → accepted/declined
(public endpoints). Acceptance can `POST /convert` into a **new invoice**. Quote
events fire `quote_event` workflow rules (which by default move the lead's status
and chain from there).

### Invoices & AR (`routes/invoices.py`, `invoice_logic.py`, module `invoicing`)

- Full lifecycle: **Draft → Sent → Partial → Paid / Overdue / Void**. The
  payment-state math is pure in `invoice_logic.py` (recompute status from
  `sum(payments)` vs. total, factoring the due date for overdue).
- Line items + tax rate; `invoice_payments` records each payment;
  `POST/DELETE /payments` recompute state.
- **PDF** rendered with `fpdf2` (`invoice_pdf.py`), streamed from
  `GET /{id}/pdf`; a public token variant (`036`) serves it without auth.
- **AR reporting**: `/summary` (totals), `/aging` (bucketed aging report),
  `/export` (CSV).
- **Recurring invoices** (`045`, `recurring_invoices.py`): a create can specify a
  recurrence; the daily `recurring_invoices_daily` tick generates the next
  occurrence of every due series.

### Online payments — Stripe Connect Express (`routes/stripe_payments.py`, `integrations/stripe/`)

The platform model: owners onboard **Express connected accounts**; customers pay
via **Checkout Sessions created on the connected account (direct charges)**, and
Axon takes a platform fee (`STRIPE_PLATFORM_FEE_PCT`). **Axon never touches
customer funds** — money flows directly to the seller's Stripe account, minus the
application fee.

- `POST /api/stripe/connect` (owner) creates/resumes onboarding;
  `GET /api/stripe/status` reports platform + connected-account readiness.
- Public pay page: `GET /api/public/pay/{token}` returns a customer-safe payload;
  `POST /api/public/pay/{token}/checkout` creates the Checkout Session.
- **Webhook**: `POST /api/public/stripe/webhook` is **signature-verified** against
  `STRIPE_WEBHOOK_SECRET` (the *Connect* endpoint secret — direct charges emit
  events on the connected account). `stripe_webhook_events` provides **idempotency**
  so a redelivered event isn't double-applied; on `checkout.session.completed` it
  records the payment and advances invoice state.

### Bookkeeping (`routes/bookkeeping.py`, module `bookkeeping`)

- `/pnl` — monthly P&L for a year (revenue from paid invoices vs. expenses vs.
  net).
- `/job-costing` — revenue, expenses, and margin **per property**, joining
  invoices and expenses by their property linkage.

### Expenses (`routes/expenses.py`, module `bookkeeping`)

Category + tax-deductible flag + optional property/job linkage; `/summary` by
category; `/export` CSV. **Receipt scanning** (`receipt_extract.py`):
`POST /scan-receipt` sends a receipt photo to Claude vision (`RECEIPT_SCAN_MODEL`,
default Haiku) and returns extracted expense fields to prefill the form.

---

## 13. Vertical Child Objects

`policies`, `orders`, `appointments` (migration `043`) are **independently-gated
record types linked to a `properties` row**. Each is a module opted in by
business-type presets (existing accounts were backfilled OFF).

- **Policies** (insurance) — carrier, type, premium, effective/expiration dates.
  Roll-up KPI: premium in force. Renewal proximity drives rescoring; the X-date
  automation suite targets `expiration_date` via `date_offset` rules.
- **Orders** (retail) — with a **Square/Shopify CSV importer**
  (`order_import_logic.py`, `routes/order_imports.py`): preview → commit, with a
  template download. Roll-up: lifetime order value; **RFM** (recency/frequency/
  monetary) drives rescoring.
- **Appointments** — scheduled visits; roll-up: upcoming appointment count.

`GET /api/objects/kpis` returns dashboard aggregates over *enabled* child-object
modules (checked internally). `POST /api/objects/rescore` (owner) recomputes lead
scores from child-object roll-ups. `account_rescore.py` drives the nightly
renewal/RFM rescore for non-property business types.

---

## 14. Messaging, Notifications & Two-Way SMS

### Template rendering (`api/messaging.py`, pure/testable)

`render_template(body, ctx)` does merge-field substitution (`{{first_name}}`,
`{{carrier}}`, …). `build_context(record, business_name, policy=…)` assembles the
merge context from the record (+ optional child object). `channel_order(delivery)`
resolves `sms_first`/`email_first`/`both` into an ordered channel list +
send-all flag. `recipient_for_channel(record, channel)` picks
`contact_email`/`contact_phone`.

### Delivery (`api/notifications.py`)

`send_email` via **Resend** (`RESEND_API_KEY`/`RESEND_FROM_EMAIL`); `send_sms` via
**Twilio** (`TWILIO_*`). `email_configured()`/`sms_configured()` gate everything —
unconfigured channels are skipped gracefully, never raised, so the app runs fine
without them.

### Per-record send

`POST /api/leads/{id}/message` renders a template (or ad-hoc message) and sends to
the record's contact, logging an outbound row to `contact_history` (with
`channel`, `direction='outbound'`, `body`).

### Two-way SMS (`routes/twilio_inbound.py`, migration `048`)

`POST /api/public/twilio/sms` is Twilio's inbound webhook. It's
**signature-verified** (Twilio's `X-Twilio-Signature` HMAC), matches the sender's
phone number to a `properties` row within the right account, and logs an
**inbound** `contact_history` row — so a customer's reply lands on the lead's
timeline. The unified lead timeline (`GET /api/leads/{id}/timeline`) merges
history + notes + tasks + signal events into one chronological feed.

---

## 15. Marketing Connectors & Insights

### Connectors (`api/connectors/`, `routes/connections.py`)

Pure parsers for **manual Meta exports** — Business Suite CSV, Ads Manager CSV,
and "Download Your Information" JSON. There's no live OAuth yet (the `META_*`
env vars are documented placeholder seams). `connections.py` registers a
connection; `/preview` parses an upload into `social_metrics`/`social_posts`
without committing; `/import` commits it.

### Insights (`api/marketing_insights.py`, `routes/insights.py`, module `marketing`)

A **rule-based engine** (`INSIGHTS_GENERATOR=rules`, with a documented future
`claude` seam) that turns imported metrics into recommendations against tunable
benchmarks: engagement vs. `INSIGHTS_ENGAGEMENT_BENCHMARK` (3% of reach), posting
cadence vs. `INSIGHTS_MIN_POSTS_PER_WEEK`, ROAS vs. `INSIGHTS_TARGET_ROAS`, CPA vs.
`INSIGHTS_MAX_CPA`, CTR vs. `INSIGHTS_MIN_CTR`, and staleness vs.
`INSIGHTS_STALE_DAYS`. Surfaced by `GET /api/insights/marketing`.

---

## 16. Import / Export

- **Contact CSV import** (`import_logic.py`, `routes/imports.py`, module
  `prospecting`): `/preview` (with column-mapping) → `/commit`, capped at
  `IMPORT_MAX_BYTES` (5 MB). Newly-inserted leads fire `lead_imported` workflow
  rules. `/template` downloads a sample CSV.
- **Order CSV import** — see §13.
- **Export** (`routes/export.py`): `GET /api/export` streams a CSV of leads with
  the **current filters applied**, authenticated via the `?token=` query-param
  fallback (browser `<a download>` can't set headers). Expenses and invoices have
  their own `/export` endpoints.

---

## 17. The Frontend

Next.js (a **modified, breaking-change build** — the repo's `AGENTS.md` warns that
conventions differ from stock Next.js and to consult `node_modules/next/dist/docs`
before writing frontend code), React 19, TypeScript, Tailwind v4.

### Structure

- **`app/`** — routes. Public: `/` (landing), `/login`, `/preview` (mock-data
  demo), `/pay/[token]`, `/q/[token]`. Authenticated (wrapped in `<AuthGuard>`):
  `/home`, `/dashboard`, `/leads/[id]`, `/pipeline`, `/tasks`, `/expenses`,
  `/bookkeeping`, `/map` (also module-gated), `/marketing`, `/settings`.
  `middleware.ts` redirects `/ → /home` at the root.
- **`components/`** — feature components plus a **design system** in
  `components/ds/` (Button, Card, Input, KpiCard, ScoreBadge, StatusPill, Tag,
  Logo). `home/` and `lead/` hold sub-components (the lead detail page is
  decomposed into ContactInfo/Activity/Policies/Orders/Appointments/CustomFields/
  WhyThisScore/PropertySignals sections). The design-system CSS
  (`app/design-system/*.css`) defines color/typography/spacing/base tokens; the
  root layout wires brand fonts (Roboto Slab, Geist, Geist Mono) to semantic
  tokens.
- **`hooks/`** — `useEntitlements` (cached module/plan lookup + `hasModule`),
  `useTerminology` (per-account vocabulary/KPI/columns), `useKanbanDnd`
  (drag-and-drop).
- **`lib/`** — `api.ts` (every API call, typed against `types.ts`), `auth.ts`
  (localStorage token), `nav.ts` (nav items + module visibility), `terminology.ts`
  (default presets), `types.ts` (TS interfaces mirroring API payloads).

### The API client (`lib/api.ts`)

A thin `req<T>` wrapper: injects the Bearer token, sets JSON content-type, and on
**401 clears the token and redirects to `/login`**; on other errors throws
`API {status}: {body}`. A `multipart` variant omits Content-Type so the browser
sets the multipart boundary (used for CSV/receipt uploads). The base URL comes
from `NEXT_PUBLIC_API_URL`, defaulting to `http://127.0.0.1:8000` (IPv4 explicitly,
because macOS resolves `localhost` to IPv6 first and the dev backend binds IPv4).

### Client-side gating vs. server truth

Module gating in the UI (`useEntitlements`, `nav.ts`, `ModuleGate`) is **visibility
only** — the server's `require_module` is the real enforcement. The client mirror
exists so locked features are hidden and upgrade prompts render, but a crafted
request still hits the 403.

---

## 18. The HTTP API Surface

Interactive docs at `/docs` (Swagger) and `/redoc`. All protected endpoints take
`Authorization: Bearer <token>`. `(module)` = gated; `(public)` =
token/signature-authenticated, no login. The full endpoint catalog lives in the
[README's API Reference](../README.md#api-reference); the routing/gating map is in
§1 above. Route modules (`api/routes/`):

`auth`, `oauth` · `leads`, `notes`, `history`, `export` · `record_fields`,
`segments`, `messaging` · `tasks`, `pipeline` · `expenses`, `invoices`, `quotes`,
`bookkeeping` · `policies`, `orders`, `order_imports`, `appointments`, `objects` ·
`connections`, `insights`, `ml` · `map`, `geo` · `stripe_payments`,
`twilio_inbound`, `public_intake` · `hcad`, `workflows`, `imports`.

Handlers are intentionally thin: parse/validate (Pydantic models in
`api/models.py`), check auth/module/owner via dependencies, call shared pure logic
(`lead_logic`, `invoice_logic`, `messaging`, `workflow_engine`, `pipeline/*`), and
return. Business rules live in the shared modules so a route and a workflow action
take the *same* path (e.g. both move a lead's status through
`lead_logic.apply_status_change`).

---

## 19. Cross-Cutting Concerns

- **Tenancy** — `account_id` on every table and in every query; the conflict key
  on `properties` includes it. There is no Postgres RLS; isolation is
  application-enforced, which means **every new query must remember the
  `account_id` filter** (the single biggest correctness invariant to preserve).
- **Rate limiting** (`api/ratelimit.py`) — in-process token buckets on login,
  import, and pipeline-run. In-process means per-worker, not cluster-global.
- **Graceful degradation** — missing provider keys never crash the app; the
  feature no-ops or returns 503. This is pervasive and intentional.
- **SQL-injection guards** — dynamic column/table references are validated against
  hardcoded allowlists (`ALL_COLS`, `DATE_TRIGGER_SOURCES`); everything else is
  parameterized.
- **Idempotency** — `workflow_rule_firings` (rules), `stripe_webhook_events`
  (payments), the ML champion/challenger gate (models).
- **Non-fatal isolation** — ML, geo rescore, and neighbor-task side effects are
  wrapped in try/except so they never break the core flow.
- **Pure-core testability** — scoring, geo math, features, messaging, invoice
  state, equity/job-value are DB-free and unit-tested directly.

---

## 20. Deployment & Operations

- **Frontend → Vercel**: root dir `frontend`, `NEXT_PUBLIC_API_URL` pointing at
  the API; every push to `master` deploys.
- **Backend → Render (Blueprint)**: `render.yaml` provisions the API + managed
  Postgres, runs migrations on every deploy via `preDeployCommand`, and generates
  `JWT_SECRET_KEY` automatically. Because Render's filesystem is **ephemeral**, the
  HCAD DuckDB is left unset (`SEED_SOURCE=hcad`, `PERMIT_DB_PATH=""`); county data
  must be loaded into the managed Postgres once with
  `tools/load_hcad_to_postgres.py`. See [`docs/RENDER_DEPLOYMENT.md`](RENDER_DEPLOYMENT.md).
- **Railway** is a documented manual alternative.
- **After deploy**: point Vercel's `NEXT_PUBLIC_API_URL` at the backend, and add
  the frontend domain to the hardcoded CORS allowlist in `api/main.py`.
- **Migrations**: `python db/migrate.py` (run all), `status`, `create <name>`.
- **CLIs**: `scripts/create_user.py` (first owner), `scripts/set_account_plan.py`
  (assign plan/modules), `tools/build_hcad_duckdb.py` /
  `tools/load_hcad_to_postgres.py` (HCAD data), `run_pipeline.py` (offline runs).

---

## 21. Testing

`pytest` (config in `pytest.ini` + `conftest.py`), ~45 test modules under
`tests/`. Coverage centers on the **pure cores** (fast, deterministic, no DB):
`test_scoring` (signal math + explanation parity), `test_geo_scoring`/
`test_geo_clustering`/`test_geo_neighbor`/`test_geo_events`/`test_geo_expand`/
`test_geo_prospecting`/`test_geo_rescore`, `test_ml_features`/`test_ml_labels`/
`test_ml_model`/`test_ml_train_logic`, `test_equity`, `test_job_value`,
`test_signals`, `test_storm`, `test_demographics`, `test_neighborhood` (via
`test_property_normalizer`), `test_addr`/`test_seed_normalizer`,
`test_business_types`, `test_provisioning`, `test_segments`, `test_child_objects`,
`test_recurring_invoices`, `test_invoice_pdf`/`test_invoice_send`,
`test_stripe_client`/`test_stripe_webhook`, `test_twilio_inbound`,
`test_oauth_verify`, `test_import`/`test_order_import`, `test_marketing_insights`,
`test_workflow_engine_daily`, `test_account_rescore`, `test_map`,
`test_connectors_meta`, `test_coverage`, `test_select`.

---

## 22. Glossary of Non-Obvious Design Decisions

- **`properties` is the universal record table.** "Lead," "policyholder,"
  "customer," and "deal" are all the same row shape; business type changes only
  the vocabulary and which columns matter.
- **NULL-only upsert.** Enrichment never clobbers existing non-null data;
  `enrichment_flags` is JSONB-merged. This is what makes incremental,
  multi-source enrichment safe and cheap.
- **Free-before-paid, gated-last ordering.** HCAD → RentCast → skip-trace/
  demographics, with selection between free and paid tiers, minimizes API spend.
- **Weights sum to 1.0 → scores are bounded [0,100] by construction.** Adding a
  vertical is adding a dict key; adding a signal is adding a function + a
  `FACTOR_META` entry (test-enforced).
- **Explanation reuses production signal functions**, so the "why this score"
  breakdown can never disagree with the score.
- **Missing-aware ML features.** Every optional field emits a value *and* a
  `__missing` flag, so a model trained on sparse data stays valid and adapts when
  the account later buys richer data.
- **Time-based ML split + champion/challenger promotion.** No future leakage; a
  new model only replaces the old if it's at least as good on a forward holdout.
- **Geo is PostGIS-free.** Haversine + pure-Python DBSCAN/convex-hull/point-in-
  polygon run on any managed Postgres; the territory gate is multiplicative and
  non-zero so out-of-area leads sink but don't vanish.
- **Permissive entitlements.** No `account_plans` row ⇒ full access; plans tighten
  by explicit `false`. Gating is additive and can't lock out an un-provisioned
  account.
- **Advisory locks, not a broker.** Daily jobs are guarded by `pg_advisory_lock`;
  the firings ledger makes double-runs safe regardless.
- **Side effects run off the request path.** New-customer geo rescore and nightly
  ticks are enqueued/scheduled so user actions stay fast and never fail on a
  background concern.
- **Everything degrades gracefully.** Every external integration is optional; a
  missing key means a no-op or a 503, never a crash.
```
