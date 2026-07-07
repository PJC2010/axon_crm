# Axon CRM

A full-stack, multi-tenant business intelligence and CRM platform, originally built for home-service contractors and generalized to serve other verticals (insurance, retail, appointment-based businesses) from the same codebase. Axon pulls property data from public sources, scores leads using configurable per-vertical signals, and surfaces the highest-opportunity prospects in a mobile-first dashboard — alongside task management, a Kanban pipeline, quotes, invoicing with accounts receivable reporting, online payments, expense tracking, marketing insights, and workflow automation.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Environment Variables](#environment-variables)
  - [Database Setup](#database-setup)
  - [Running Locally](#running-locally)
  - [Testing](#testing)
- [Multi-Tenancy, Plans & Business Types](#multi-tenancy-plans--business-types)
- [Data Pipeline](#data-pipeline)
  - [How the Pipeline Works](#how-the-pipeline-works)
  - [Lead Scoring Engine](#lead-scoring-engine)
  - [Running the Pipeline](#running-the-pipeline)
  - [Harris County (HCAD) data](#harris-county-hcad-data)
  - [Scheduled Pipeline Runs](#scheduled-pipeline-runs)
- [Geo Scoring & Prospecting](#geo-scoring--prospecting)
- [Predictive Lead Scoring (ML)](#predictive-lead-scoring-ml)
- [API Reference](#api-reference)
- [Frontend Pages](#frontend-pages)
- [Deployment](#deployment)
  - [Frontend — Vercel](#frontend--vercel)
  - [Backend — Render / Railway](#backend--render--railway)
- [Database Migrations](#database-migrations)
- [Authentication](#authentication)
- [Further Reading](#further-reading)

---

## Overview

Axon is designed for contractors, service companies, and small businesses that do outbound prospecting. Instead of cold-calling random lists, the pipeline identifies homeowners who are statistically most likely to need your service — based on home age, equity, recent sale activity, garage size, zip income, neighborhood-relative value, permit history, storm exposure, and demographic/intent signals — then scores and ranks them so your team works the hottest leads first. A separate geo-scoring layer adds proximity, density, and territory awareness (customer clustering, heatmaps, neighbor-of-won-job targeting), and an optional predictive-scoring model learns conversion probability from your own won/lost history.

The platform is self-hosted, multi-tenant, and data-sovereign: every table is isolated by `account_id`, and all leads, notes, tasks, quotes, invoices, and expenses live in your own PostgreSQL database. A per-account **plan** (`starter` / `growth` / `pro`) and **business type** (terminology + KPI presets) let the same codebase serve different verticals without forking.

---

## Features

### Home Dashboard
- At-a-glance business health screen shown immediately after login
- Personalized greeting with time-of-day awareness
- Pipeline value card (sum of all estimated job values in active stages)
- KPI grid driven by the account's business-type preset
- "Needs Attention" alerts for overdue tasks and outstanding invoices
- Command Center pipeline-health alerts: deals stuck too long in a stage, overdue follow-ups, and high-grade leads going cold
- Quick-action buttons, onboarding checklist/wizard for new accounts, recent top-scored leads strip
- Mobile-first, responsive 2→4 column layout

### Lead Management
- Universal search by account number, name, address, phone, or email
- Scored lead table with sort, filter by zip/grade/vertical/status, saved segments, and account-defined custom fields
- Lead detail drawer/page: property info, owner details, unified activity timeline (notes + history + tasks + signal events), score explanation, neighbor leads
- Inline status updates (drives Kanban stage + fires workflow automations)
- On-demand contact enrichment (skip-trace) per lead
- CSV import (with column-mapping preview) and export with current filters applied

### Kanban Pipeline
- Configurable custom stages (not hardcoded)
- Stage summary: count and total job value per column
- Pipeline analytics: win rate, cycle time, funnel, forecast (weighted pipeline value), stuck-deal/overdue-follow-up alerts
- Performance attribution by lead source, rep, or service vertical

### Task Management
- Tasks linked optionally to specific leads/properties, with due date, priority, and assignment
- Overdue and due-today counts surfaced in the home dashboard and a task-bell indicator

### Quotes
- Create quotes with line items, send via email/SMS, and share a public accept/decline link
- Customer acceptance converts the quote directly into a new invoice

### Invoicing & Accounts Receivable
- Full invoice lifecycle: Draft → Sent → Partial → Paid / Overdue / Void, with recurring invoices
- Line items, tax rate, payment recording, PDF generation, and email/SMS delivery
- AR summary, aging report buckets, CSV export
- **Online payments**: Stripe Connect Express — a public pay page lets customers pay by card; Axon takes a configurable platform fee and never touches customer funds directly

### Expense Tracker
- Log expenses by category with a tax-deductible flag, monthly summary, property/job linkage, CSV export
- Receipt photo scanning (Claude vision) auto-fills expense fields from a picture of a receipt

### Bookkeeping
- P&L report by month for any year (revenue vs. expenses vs. net profit)
- Job costing table: revenue, expenses, profit margin per property

### Vertical Child Objects (Policies / Orders / Appointments)
- Independently gated per-vertical record types associated with a core lead/customer record: insurance **Policies**, retail **Orders** (with a Square/Shopify CSV import), and **Appointments**
- Each drives roll-up KPIs (premium in force, lifetime order value, upcoming appointment count) and can trigger rescoring (renewal proximity for policies, RFM for orders)

### Custom Fields, Segments & Messaging
- Account-defined custom fields on any record
- Saved segments (named, reusable filter sets)
- Reusable message templates with merge-field rendering; per-record send (email/SMS) logs to the contact timeline
- Two-way SMS: inbound Twilio messages are matched to a record by phone number and logged to its timeline

### Marketing Insights
- Connect Meta (Facebook/Instagram) via manual export upload (Business Suite CSV, Ads Manager CSV, "Download Your Information" JSON)
- Rule-based recommendations (engagement, posting cadence, ROAS, CPA, CTR benchmarks — all tunable) surfaced as a Marketing Insights panel

### Predictive Lead Scoring & Geo Prospecting
See [Predictive Lead Scoring (ML)](#predictive-lead-scoring-ml) and [Geo Scoring & Prospecting](#geo-scoring--prospecting) below.

### Pipeline Scheduler
- Schedule pipeline runs by zip code, vertical, day of week, and hour; active/inactive toggle per schedule
- Run history with status tracking; background execution via APScheduler (also drives nightly ML retraining, the workflow automation tick, account rescoring, recurring-invoice generation, and geo rescoring)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4 |
| Icons | lucide-react |
| Maps | MapLibre GL JS, ngeohash |
| Backend | FastAPI (Python 3.11+), Uvicorn |
| Database | PostgreSQL (primary), DuckDB (HCAD permit/property data, optional) |
| Auth | JWT (python-jose), bcrypt password hashing, Sign in with Google/Apple (OIDC) |
| Scheduler | APScheduler 3.x |
| Data Pipeline | RentCast API, Google Geocoding API, US Census ACS API, NOAA/IEM storm reports, BatchData/Versium (skip-trace + demographics) |
| Predictive Scoring | Pure-Python logistic regression (`pipeline/ml/`) — no heavyweight ML dependency required |
| Payments | Stripe Connect Express |
| Messaging | Resend (email), Twilio (SMS, two-way) |
| Documents | fpdf2 (invoice/quote PDF rendering) |
| AI | Anthropic Claude (receipt OCR vision extraction) |
| ORM | Raw SQL via psycopg2 |

---

## Project Structure

```
axon-crm/
├── api/                         # FastAPI application
│   ├── main.py                  # App entry point, CORS, router registration, module gating
│   ├── deps.py                  # Shared FastAPI dependencies (DB conn, current user)
│   ├── models.py                # Pydantic request/response models
│   ├── security.py              # JWT creation/verification, password hashing
│   ├── entitlements.py          # Plans (starter/growth/pro) + require_module() gating
│   ├── business_types.py        # Business-type/terminology presets (multi-vertical)
│   ├── accounts.py              # New-account provisioning (default stages, etc.)
│   ├── scheduler.py             # APScheduler setup: pipeline, retrain, workflow tick, rescore, recurring invoices
│   ├── workflow_engine.py       # Status-change + scheduled workflow automation engine
│   ├── ratelimit.py             # In-process rate limiting (login/import/pipeline-run)
│   ├── oauth_verify.py          # Google/Apple OIDC ID token verification
│   ├── messaging.py             # Message-template merge-field rendering (pure/testable)
│   ├── notifications.py         # Invoice/quote delivery via Resend (email) + Twilio (SMS)
│   ├── invoice_logic.py         # Shared invoice payment-state logic
│   ├── invoice_pdf.py           # Invoice/quote PDF rendering (fpdf2)
│   ├── lead_logic.py            # Shared lead status-change logic
│   ├── import_logic.py          # Pure helpers for contact/lead CSV import
│   ├── order_import_logic.py    # Pure helpers for retail order CSV import
│   ├── recurring_invoices.py    # Recurring invoice generation
│   ├── marketing_insights.py    # Rule-based marketing insights engine
│   ├── receipt_extract.py       # Claude-vision receipt OCR
│   ├── neighbors.py             # Neighbor-of-customer targeting
│   ├── connectors/              # Pure parsers for social/ads export uploads (Meta, base)
│   ├── integrations/stripe/     # Stripe Connect Express client helpers
│   └── routes/                  # ~26 route modules — see API Reference for the full endpoint list
│       ├── auth.py, oauth.py                        # Login, session, account features, team, OAuth
│       ├── leads.py, notes.py, history.py, export.py # Core lead CRUD, notes, history, CSV export
│       ├── record_fields.py, segments.py             # Custom fields, saved segments
│       ├── messaging.py                              # Message templates + per-record send
│       ├── tasks.py, pipeline.py                     # Tasks, Kanban/analytics + data-acquisition runs
│       ├── expenses.py, invoices.py, quotes.py        # Expenses, invoicing/AR, quotes
│       ├── bookkeeping.py                             # P&L, job costing
│       ├── policies.py, orders.py, order_imports.py,
│       │   appointments.py, objects.py                # Vertical child objects + roll-up KPIs
│       ├── connections.py, insights.py                # Social connectors + marketing insights
│       ├── ml.py                                       # Predictive lead scoring
│       ├── map.py, geo.py                              # Service-area map + geo scoring/prospecting
│       ├── stripe_payments.py                          # Online payments (Connect + public pay page)
│       ├── twilio_inbound.py                           # Inbound two-way SMS webhook
│       ├── public_intake.py                            # Public website lead intake
│       ├── hcad.py                                     # Harris County data upload/status
│       ├── workflows.py, imports.py                    # Automation rules, contact CSV import
│
├── pipeline/                    # Data acquisition + scoring pipeline (run independently)
│   ├── seed.py, census.py, geocode.py, hcad_enrichment.py,
│   │   select.py, property.py, permits.py, storm.py, contact.py,
│   │   demographics.py, signals.py                  # The 13-step enrichment flow — see Data Pipeline
│   ├── scorer.py, scoring.py                        # Rule-based per-vertical scoring
│   ├── hcad_store.py, coverage.py, equity.py,
│   │   job_value.py, addr.py, neighborhood.py        # Supporting helpers
│   ├── geo_scoring.py, geo_clustering.py, geo_h3.py,
│   │   geo_score_store.py, geo_cluster_store.py,
│   │   geo_expand.py, prospecting.py                 # Geo scoring / clustering / prospecting subsystem
│   ├── account_rescore.py                            # Rescore trigger (used by workflow/geo events)
│   └── ml/                                            # Predictive lead-scoring pipeline (separate from scorer.py)
│       ├── dataset.py, features.py, labels.py, model.py,
│       │   train.py, predict.py, metrics.py, registry.py, snapshot.py
│
├── db/
│   ├── migrate.py               # Migration runner CLI
│   └── migrations/              # 53 numbered .sql files — see Database Migrations
│
├── frontend/                    # Next.js application
│   ├── app/
│   │   ├── layout.tsx, page.tsx           # Root layout, public landing page
│   │   ├── login/                         # Sign in (password + Google/Apple)
│   │   ├── home/, dashboard/, pipeline/,
│   │   │   tasks/, expenses/, bookkeeping/,
│   │   │   map/, marketing/, settings/    # Authenticated app sections
│   │   ├── leads/[id]/                    # Lead detail (dynamic route)
│   │   ├── pay/[token]/, q/[token]/       # Public, token-addressed pay page + quote page
│   │   └── preview/                       # Public mock-data demo dashboard
│   ├── components/
│   │   ├── ds/                            # Design-system primitives (Button, Card, Input, KpiCard, …)
│   │   ├── home/, lead/                   # Home-dashboard and lead-detail sub-components
│   │   ├── Dashboard.tsx, LeadTable.tsx,
│   │   │   ContactDrawer.tsx, ScoreBadge.tsx, …  # Lead management
│   │   ├── KanbanCard.tsx, PipelineAnalytics.tsx  # Pipeline
│   │   ├── TaskList.tsx, TaskForm.tsx            # Tasks
│   │   ├── ExpenseTracker.tsx, …                  # Expenses
│   │   ├── InvoiceList.tsx, QuoteList.tsx, ARDashboard.tsx,
│   │   │   BookkeepingDashboard.tsx, JobCostingTable.tsx,
│   │   │   StripeConnectSection.tsx              # Invoicing/quotes/bookkeeping/payments
│   │   ├── MarketingInsightsPanel.tsx, AIInsightsPanel.tsx
│   │   ├── PropertyMap.tsx                       # Map
│   │   └── ConnectionsSection.tsx, WorkflowRuleForm.tsx,
│   │       CustomFieldsSettings.tsx, MessageTemplatesSettings.tsx  # Settings
│   ├── hooks/
│   │   ├── useEntitlements.ts   # Cached module/plan lookup + hasModule()
│   │   ├── useTerminology.ts    # Per-account vocabulary/KPI/column config
│   │   └── useKanbanDnd.ts      # Kanban drag-and-drop
│   ├── lib/
│   │   ├── api.ts               # All API client functions
│   │   ├── auth.ts              # Token storage (localStorage)
│   │   ├── nav.ts               # Nav items + module-based visibility
│   │   ├── terminology.ts       # Default terminology/category presets
│   │   └── types.ts             # TypeScript interfaces
│   └── middleware.ts            # Root redirect (/ → /home)
│
├── docs/                        # Architecture/roadmap docs — see Further Reading
├── tests/                       # pytest suite (pipeline, ML, geo, imports, Stripe, Twilio, OAuth, …)
├── tools/                       # HCAD DuckDB build/export/load, pipeline visualization
├── scripts/                     # create_user.py, set_account_plan.py, provider smoke tests
├── config.py                    # Scoring weights, verticals, API keys, thresholds
├── run_pipeline.py               # Pipeline CLI entry point
├── render.yaml                   # Render Blueprint (API + managed Postgres)
├── requirements.txt / requirements-dev.txt
└── .env.example                  # Full annotated list of environment variables
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ (running locally or via a cloud provider)
- A virtual environment tool (`python -m venv` or `uv`)

### Environment Variables

Copy `.env.example` to `.env` in the project root — it documents every variable (grouped: core, social login, map basemap, connectors/marketing insights, predictive ML scoring, property data sources, contact/demographics enrichment, storm events, cost/tuning knobs, invoice/quote delivery, website lead intake, Stripe, seed source). The minimum to run locally:

```env
DATABASE_URL=postgresql://localhost/axon_crm
JWT_SECRET_KEY=your-long-random-secret-key-here

# Required for pipeline data enrichment
RENTCAST_API_KEY=your_key
GOOGLE_GEOCODE_KEY=your_key
```

> `JWT_SECRET_KEY` is **required** — the API refuses to start without it. For local development only, you may instead set `ALLOW_INSECURE_DEV_JWT=true` and skip it.

> Everything else (Census, HCAD, contact/demographics skip-trace, storm data, Stripe, Resend/Twilio, Google/Apple sign-in, website lead intake) is optional; each feature no-ops or 503s until its keys are set. See `.env.example` for details on each.

For the frontend, create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Database Setup

1. Create the database:
```bash
createdb axon_crm
```

2. Run all migrations:
```bash
python db/migrate.py
```

3. Check migration status anytime:
```bash
python db/migrate.py status
```

4. Create a new migration file:
```bash
python db/migrate.py create add_customers
```

5. Create your first owner (admin) user:
```bash
python scripts/create_user.py --username admin --email you@example.com --role owner
```
You'll be prompted for a password (or pass `--password`). Run `python scripts/create_user.py --help` for all options.

6. (Optional) Assign a plan/feature modules to an account from the CLI:
```bash
python scripts/set_account_plan.py --help
```

### Running Locally

**Backend:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# Runs at http://localhost:3000
```

Navigate to `http://localhost:3000/login` and sign in. You'll be taken to the home dashboard.

### Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite (`tests/`, configured via `pytest.ini` and `conftest.py`) covers pipeline scoring/enrichment, ML training, geo scoring/clustering, CSV import, Stripe client logic, Twilio webhook verification, and OAuth token verification.

---

## Multi-Tenancy, Plans & Business Types

Every table is isolated by `account_id` (`db/migrations/017_org_isolation.sql`), so one deployment can safely host multiple organizations.

- **Plans** (`api/entitlements.py`): `starter` (core features only), `growth` (adds invoicing, bookkeeping, quotes, automation, appointments), `pro` (every module). Core features — leads, the Kanban board, tasks, notes, history, export, custom fields, segments, and messaging — are always on and aren't gated behind any plan.
- **Modules** are enforced server-side via a `require_module(key)` FastAPI dependency (403s with an `upgrade: true` hint when missing) and mirrored client-side by `useEntitlements`/`hasModule()` for UI visibility only.
- **Business types** (`api/business_types.py`, `docs/GENERALIZATION_ROADMAP.md`) let one codebase serve different verticals: each business type provides default terminology (e.g. "lead" vs. "policy" vs. "customer"), a default category picklist, which KPI tiles to show, and which lead-table columns to show. The frontend's `useTerminology` hook resolves this per account.

---

## Data Pipeline

### How the Pipeline Works

`run_pipeline.py` runs the following steps in order for a given ZIP code and optional service vertical (steps can be skipped individually with `--skip`):

| Step | Module | Description |
|---|---|---|
| 1 | `pipeline/seed.py` | Seeds addresses from RentCast (paid, default), local HCAD data (`--seed-source hcad`, free), or a CSV |
| 2 | `pipeline/census.py` | Enriches each ZIP with median household income from US Census ACS |
| 3 | `pipeline/geocode.py` | Geocodes addresses to lat/lng via Google Maps Geocoding API |
| 4 | `pipeline/hcad_enrichment.py` | Free backfill of property/owner/mailing-address fields from Harris County Appraisal District data, run before any paid step |
| 5 | `pipeline/select.py` | Optional Top-N / radius volume trim (`--top-n`, `--address` + `--radius`) before paid enrichment |
| 6 | `pipeline/property.py` | RentCast paid enrichment — only fills fields still NULL after HCAD |
| 7 | `pipeline/permits.py` | Pulls 24-month permit counts from HCAD DuckDB/Postgres |
| 8 | `pipeline/storm.py` | Matches NOAA/IEM hail/wind/tornado history to geocoded properties |
| 9 | `pipeline/scorer.py` | Scores each property 0–100 and assigns a letter grade (A/B/C/D) per vertical weights |
| 10 | `pipeline/select.py` (trim) | Optional precision cut back to the exact top-N using real scores, before paid skip-trace |
| 11 | `pipeline/contact.py` | Skip-trace contact enrichment (BatchData/Versium), optionally grade-gated |
| 12 | `pipeline/demographics.py` | Household demographics/life-events append (BatchData/Versium), optionally grade-gated |
| 13 | `pipeline/signals.py` | Diffs key fields against the previous run (new sale, new permit, storm, score change), records `signal_events`, and fires workflow automations |

### Lead Scoring Engine

Each lead receives a composite score (0–100) from up to 13 weighted signals, most optional and applied only where a vertical's config includes them:

| Signal | What it Measures |
|---|---|
| Home age | Age in renovation sweet spot (15–30 years) |
| Sale recency | Last sale within 24 months |
| Equity | Estimated equity toward $100,000 |
| Garage | Garage spaces toward 2+ |
| Zip income | Zip median household income toward $75,000 |
| Neighborhood value | Value-per-sqft vs. the immediate block (finer-grained than ZIP income) |
| Permit activity | ≥ 2 permits pulled in last 24 months |
| Pool present *(optional)* | Confirmed pool from HCAD |
| Cracked slab *(optional)* | Confirmed cracked slab from HCAD |
| Storm activity *(optional)* | Recent hail/wind/tornado event nearby |
| Home improvement *(optional)* | Owner buys home-improvement products |
| Recent refinance *(optional)* | Cash-out refi signals available capital |
| Credit quality *(optional)* | Financing eligibility for big-ticket work |
| Children in home *(optional)* | Safety-focused spending driver |
| Gardening interest *(optional)* | Landscaping/outdoor-service intent |
| Absentee owner *(optional)* | Investor/landlord — rental turnover & exterior work prospect |
| Ownership tenure *(optional)* | Long-tenured owners run aging systems overdue for replacement |
| Life stage *(optional)* | New movers renovate soon; retirees invest in aging-in-place |

**Grade bands:**

| Score | Grade |
|---|---|
| 75–100 | A |
| 55–74 | B |
| 35–54 | C |
| 0–34 | D |

**8 built-in verticals** are configured in `config.py`'s `VERTICAL_WEIGHTS`, each with its own weight profile (weights must sum to 1.0 per vertical): `epoxy_flooring`, `pool_maintenance`, `solar`, `roofing`, `hvac`, `fencing`, `landscaping`, `pressure_washing`. Adding a new vertical requires only adding a key. Every signal contributes a human-readable "reason to contact" surfaced in the lead's score explanation.

### Running the Pipeline

```bash
# Single ZIP code
python run_pipeline.py --zip 77002

# ZIP + service vertical
python run_pipeline.py --zip 77002 --vertical roofing

# Multiple ZIPs from a file (one per line)
python run_pipeline.py --zip-file zips.txt --vertical roofing

# Seed from a local CSV instead of RentCast
python run_pipeline.py --zip 77002 --seed-csv /path/to/addresses.csv

# Skip specific steps (comma-separated)
python run_pipeline.py --zip 77002 --skip geocode,permits

# Limit / target a subset of records
python run_pipeline.py --zip 77002 --top-n 100
python run_pipeline.py --address "123 Main St, Houston, TX" --radius 1
```

Available verticals (defined in `config.py`): `epoxy_flooring`, `pool_maintenance`, `solar`, `roofing`, `hvac`, `fencing`, `landscaping`, `pressure_washing` — or pass any custom string.

### Harris County (HCAD) data

Step 4 (`hcad_enrichment.py`) backfills property, owner, and owner mailing address fields for free from Harris County Appraisal District data. It reads a local `harris_county.duckdb` (path in `PERMIT_DB_PATH`), falling back to the Postgres `hcad_*` tables.

Build that DuckDB from HCAD's [Real property export](https://hcad.org/pdata/):

```bash
python tools/build_hcad_duckdb.py /path/to/unzipped_hcad_dir -o harris_county.duckdb
```

For hosts without the DuckDB (e.g. Render, whose filesystem is ephemeral), mirror selected ZIPs into Postgres with `tools/load_hcad_to_postgres.py` (or `tools/export_hcad_zip.py` + the `/api/hcad/upload` endpoint for a subset). See [`docs/RENDER_DEPLOYMENT.md`](docs/RENDER_DEPLOYMENT.md) and the full column mapping in [`docs/hcad_real_property_mapping.md`](docs/hcad_real_property_mapping.md).

### Scheduled Pipeline Runs

Pipeline runs can be scheduled from the **Settings** page. Each schedule specifies ZIP code, vertical (optional), day of week, and hour. The APScheduler background process (started with the API server) picks up active schedules on boot and runs them automatically. Run history is tracked in the `pipeline_jobs` table.

---

## Geo Scoring & Prospecting

A separate spatial layer (internally called "Juncto," see [`docs/geo_scoring.md`](docs/geo_scoring.md)) adds proximity, density, and territory awareness on top of the property score, driven by `/api/geo/*`:

- **Proximity/density/territory scoring** — haversine distance (× a road-circuity factor) to your existing customers (won/converted leads), local customer density, and whether a lead falls inside your drawn service area.
- **Customer clustering & heatmap** — pure-Python DBSCAN clusters won customers; an optional H3-hex heatmap (`pipeline/geo_h3.py`, requires the `h3` package) visualizes density/score on the map.
- **Cluster-seeded prospecting** — pulls pre-geocoded prospects from a property-data provider around a cluster seed, dedupes against existing leads, ingests, and scores them, with cost controls (skip-days, max pulls per cycle).
- **Neighbor-of-won-job targeting** — when a lead is marked `won`, flags nearby uncontacted leads as a "N neighbors of your new customer" list.
- **Event polygons** — hail swaths, HOA sweeps, and similar events add a scoring bonus to leads inside the polygon while active.

This subsystem runs via the geo scheduler tick and the `/api/geo/*` endpoints rather than through `run_pipeline.py`.

---

## Predictive Lead Scoring (ML)

An optional per-account model (`pipeline/ml/`) learns conversion probability from your own won/lost lead history, using a dependency-free pure-Python logistic-regression trainer (no `scikit-learn`/`numpy` required, though the code has seams for them later).

- `SCORER_MODE=rules` (default) — deterministic scoring only, no behavior change.
- `SCORER_MODE=shadow` — computes and stores the learned probability alongside the rules score, without changing the user-facing grade — use this to validate lift before flipping the UI.
- `SCORER_MODE=learned` — surfaces the learned conversion probability to users.

A scope (account, or the pooled/global model) needs at least `ML_MIN_TRAINING_LABELS` labeled leads before it trains; an untouched open lead older than `ML_STALE_OPEN_DAYS` is treated as a soft loss so the model learns from leads that quietly went nowhere. Retraining runs nightly (`ML_RETRAIN_HOUR`, via the scheduler) or on demand via `POST /api/ml/retrain`. See `/api/ml/insights/leads` for a predictive "hot untouched leads" + revenue-forecast view.

---

## API Reference

The FastAPI server exposes interactive docs at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`. All protected endpoints require `Authorization: Bearer <token>`. Endpoints marked **(module)** are gated behind that feature module (see [Multi-Tenancy, Plans & Business Types](#multi-tenancy-plans--business-types)); endpoints marked **(public)** are ungated, token- or signature-authenticated, and meant for customers or third-party webhooks.

### Auth & Account
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | Authenticate and receive JWT access token |
| GET | `/api/auth/me` | Current user info + enabled modules + business type |
| GET | `/api/account/features` | Resolved plan, modules, and business-type profile |
| PATCH | `/api/account/plan` | Owner toggles modules within the plan's allowance |
| PATCH | `/api/account/business-type` | Owner switches business type/terminology |
| GET | `/api/account/business-types` | Business-type catalog for onboarding |
| PATCH | `/api/auth/onboarding-complete` | Mark onboarding done |
| GET | `/api/auth/checklist-status` | Onboarding checklist booleans |
| POST | `/api/users` | Create team member (owner) |
| GET | `/api/team` / `/api/users` | List team roster / full user list (owner) |
| PATCH | `/api/users/{id}` | Update a user's role/active status (owner) |
| POST | `/api/auth/oauth/google` / `/apple` | Sign in with Google/Apple (existing invited user only) |

### Leads
| Method | Path | Description |
|---|---|---|
| GET | `/api/leads` | List leads with filtering, sorting, pagination |
| GET | `/api/leads/search` | Universal lookup by account #, name, address, phone, email |
| GET | `/api/leads/by-number/{account_number}` | Resolve by durable account number |
| GET | `/api/leads/{id}` | Get single lead |
| GET | `/api/leads/{id}/score-explanation` | Factor-by-factor score breakdown (+ ML overlay) |
| PATCH | `/api/leads/{id}/status` | Update lead status (fires workflow automations) |
| PATCH | `/api/leads/{id}/contact` | Update contact fields |
| PATCH | `/api/leads/{id}/job-value` | Update estimated job value |
| PATCH | `/api/leads/{id}/custom-fields` | Merge/clear custom field values |
| POST | `/api/leads/{id}/enrich` | On-demand skip-trace contact enrichment |
| GET | `/api/leads/{id}/neighbors` | Uncontacted leads in the same geohash cell |
| GET | `/api/leads/{id}/timeline` | Unified activity feed (history + notes + tasks + signals) |
| POST | `/api/leads/{id}/archive` / `/unarchive` | Soft delete / restore |
| POST | `/api/leads/archive-bulk` / `/unarchive-bulk` / `/archive-by-filter` | Bulk archive operations |
| GET | `/api/zips` / `/api/regions` / `/api/neighborhoods` | ZIP list / named HCAD regions / geohash-6 cell aggregates |

### Notes, History & Export
| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/leads/{id}/notes` | Notes for a lead |
| GET/POST | `/api/leads/{id}/history` | Contact/activity history |
| GET | `/api/export` | CSV download of leads (respects current filters) |

### Custom Fields, Segments & Messaging (core)
| Method | Path | Description |
|---|---|---|
| GET/POST/PATCH/DELETE | `/api/record-fields[/{id}]` | Account-defined custom field definitions (write = owner) |
| GET/POST/PATCH/DELETE | `/api/segments[/{id}]` | Saved segments (filter sets) |
| GET/POST/PATCH/DELETE | `/api/message-templates[/{id}]` | Reusable email/SMS templates (write = owner) |
| POST | `/api/leads/{id}/message` | Render + send a template (or ad-hoc message) to a record's contact |

### Tasks
| Method | Path | Description |
|---|---|---|
| GET | `/api/tasks/counts` | Due-today / overdue badge counts |
| GET | `/api/tasks` | List tasks (filter by due, overdue, property, assignee, complete) |
| GET | `/api/leads/{id}/tasks` | Tasks linked to a lead |
| POST | `/api/tasks` | Create task |
| GET/PATCH | `/api/tasks/{id}` | Get / update task |
| POST | `/api/tasks/{id}/complete` | Mark task complete |
| DELETE | `/api/tasks/{id}` | Delete task (owner) |

### Pipeline / Kanban
| Method | Path | Description |
|---|---|---|
| GET/POST/PATCH/DELETE | `/api/pipeline/stages[/{id}]` | Custom stage CRUD (write = owner) |
| GET | `/api/pipeline` | Leads grouped by stage (Kanban) |
| GET | `/api/pipeline/stats` | Count + total value per stage |
| GET | `/api/pipeline/analytics` | Win rate, cycle time, funnel, avg days/stage |
| GET | `/api/pipeline/forecast` | Weighted pipeline value by stage |
| GET | `/api/pipeline/alerts` | Stuck deals / overdue follow-ups / cooling leads |
| GET | `/api/pipeline/performance` | Win-rate/revenue attribution by source, rep, or vertical |
| GET/POST/PATCH/DELETE | `/api/pipeline-schedules[/{id}]` **(prospecting)** | Recurring pipeline-run schedules (write = owner) |
| POST | `/api/pipeline/run` **(prospecting)** | Trigger a manual data-acquisition run (owner, rate-limited) |
| GET | `/api/pipeline/runs[/{id}]` **(prospecting)** | Run history / detail |
| POST | `/api/pipeline/rescore` / `/rescore-all` **(prospecting)** | Rescore a ZIP / every ZIP (owner) |
| DELETE | `/api/pipeline/runs/{id}` **(prospecting)** | Cancel a running pipeline (owner) |

### Expenses **(bookkeeping)**
| Method | Path | Description |
|---|---|---|
| GET | `/api/expenses/summary` | Totals by category + tax-deductible summary |
| GET | `/api/expenses/export` | CSV download |
| GET/POST | `/api/expenses` | List (filters) / create |
| POST | `/api/expenses/scan-receipt` | Extract fields from a receipt photo (Claude vision) |
| GET/PATCH/DELETE | `/api/expenses/{id}` | Get / update / delete (delete = owner) |

### Invoices & AR **(invoicing)**
| Method | Path | Description |
|---|---|---|
| GET | `/api/invoices/summary` | AR overview totals |
| GET | `/api/invoices/aging` | Aging report buckets |
| GET | `/api/invoices/export` | CSV download |
| GET/POST | `/api/invoices` | List (filters) / create with line items (supports recurrence) |
| GET | `/api/invoices/{id}` | Get invoice with line items + payments |
| GET | `/api/invoices/{id}/pdf` | Stream print-ready PDF |
| PATCH/DELETE | `/api/invoices/{id}` | Update / delete (delete = owner) |
| POST/DELETE | `/api/invoices/{id}/payments[/{pid}]` | Record / remove a payment |
| POST | `/api/invoices/{id}/send` | Deliver PDF via email/SMS |
| POST | `/api/invoices/{id}/checkout` | Staff-initiated Stripe Checkout Session URL |
| GET | `/api/public/invoices/{token}/pdf` **(public)** | Token-addressed PDF, no auth |

### Quotes **(quotes)**
| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/quotes` | List (filters) / create with line items |
| GET/PATCH/DELETE | `/api/quotes/{id}` | Get / update / delete (delete = owner) |
| POST | `/api/quotes/{id}/send` | Deliver to client by email/SMS |
| POST | `/api/quotes/{id}/convert` | Accept + convert to a new invoice |
| GET | `/api/public/quotes/{token}` **(public)** | Customer view (stamps viewed_at) |
| POST | `/api/public/quotes/{token}/accept` / `/decline` **(public)** | Customer accepts/declines |

### Bookkeeping **(bookkeeping)**
| Method | Path | Description |
|---|---|---|
| GET | `/api/bookkeeping/pnl` | Monthly P&L report for a given year |
| GET | `/api/bookkeeping/job-costing` | Revenue, expenses, margin per property |

### Vertical Child Objects
| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/policies` **(policies)** | List (+ roll-ups) / create; PATCH/DELETE `/api/policies/{id}` |
| GET/POST | `/api/orders` **(orders)** | List (+ roll-ups) / create; PATCH/DELETE `/api/orders/{id}` |
| POST | `/api/imports/orders/preview` / `/api/imports/orders` **(orders)** | Preview + commit a Square/Shopify order CSV import |
| GET | `/api/imports/orders/template` **(orders)** | Sample CSV download |
| GET/POST | `/api/appointments` **(appointments)** | List (+ roll-ups) / create; PATCH/DELETE `/api/appointments/{id}` |
| GET | `/api/objects/kpis` | Dashboard aggregates over enabled child-object modules |
| POST | `/api/objects/rescore` | Owner-triggered rescore from child-object roll-ups (owner) |

### Marketing: Connections & Insights
| Method | Path | Description |
|---|---|---|
| GET/POST/DELETE | `/api/connections[/{id}]` | List / register / disconnect a social connection (owner) |
| POST | `/api/connections/{id}/preview` / `/import` | Parse / commit a Meta export upload |
| GET | `/api/insights/marketing` **(marketing)** | Rule-based (or LLM) acquisition recommendations |

### Predictive Scoring (ML) **(prospecting)**
| Method | Path | Description |
|---|---|---|
| GET | `/api/ml/status` | Scorer mode, active model metrics, labeled-data counts |
| POST | `/api/ml/retrain` | Backfill labels + retrain (owner) |
| GET | `/api/ml/insights/leads` | Predictive findings + revenue forecast |

### Map **(map)** & Geo
| Method | Path | Description |
|---|---|---|
| GET | `/api/map/cells` | Geohash-6 choropleth aggregates |
| GET | `/api/map/properties` | Property pins within a viewport bbox |
| GET | `/api/geo/config` | Resolved per-vertical geo config |
| POST | `/api/geo/score/batch` | Recompute geo + final scores |
| POST | `/api/geo/geocode/backfill` | Enqueue geocoding for leads missing coordinates |
| GET | `/api/geo/clusters` / `/heatmap` | Customer clusters / H3 heatmap (GeoJSON) |
| POST | `/api/geo/cluster/recompute` | Re-run clustering + H3 backfill |
| POST | `/api/geo/prospect` | Cluster-seeded prospecting |
| POST | `/api/geo/neighbors` | Blast-radius door-knock list around a won job |
| GET/POST/DELETE | `/api/geo/events[/{id}]` | Event polygons (hail swaths, etc.), triggers rescore |
| GET/PUT | `/api/geo/service-area` | Account's service-area polygon |

### Payments **(invoicing)**
| Method | Path | Description |
|---|---|---|
| POST | `/api/stripe/connect` | Create/resume Stripe Connect Express onboarding (owner) |
| GET | `/api/stripe/status` | Platform + connected-account readiness |
| GET | `/api/public/pay/{pay_token}` **(public)** | Customer-safe pay-page payload |
| POST | `/api/public/pay/{pay_token}/checkout` **(public)** | Create Checkout Session |
| POST | `/api/public/stripe/webhook` **(public)** | Signature-verified Stripe event sink |

### Messaging Webhooks & Public Intake
| Method | Path | Description |
|---|---|---|
| POST | `/api/public/twilio/sms` **(public)** | Inbound Twilio SMS webhook (two-way messaging) |
| POST | `/api/public/website-lead` **(public)** | Website lead intake (shared-secret authenticated) |

### HCAD **(prospecting)**
| Method | Path | Description |
|---|---|---|
| POST | `/api/hcad/upload` | Upload county properties+permits CSVs for a ZIP (owner) |
| GET | `/api/hcad/status` | Active HCAD source and loaded ZIPs/row counts (owner) |
| DELETE | `/api/hcad/{zip}` | Remove county data for a ZIP (owner) |

### Workflows **(automation)** & Imports **(prospecting)**
| Method | Path | Description |
|---|---|---|
| GET/POST/PATCH/DELETE | `/api/workflows[/{id}]` | Automation rule CRUD (write = owner) |
| POST | `/api/workflows/seed-defaults` | Seed vertical-specific default rules (owner) |
| POST | `/api/imports/contacts/preview` / `/api/imports/contacts` | Preview / commit a contact CSV import |
| GET | `/api/imports/contacts/template` | Sample CSV download |

### Utility
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Server health check |

---

## Frontend Pages

| Route | Page | Auth Required |
|---|---|---|
| `/` | Public landing / marketing page | No |
| `/login` | Sign in (password + Google/Apple) | No |
| `/preview` | Public mock-data demo dashboard | No |
| `/pay/[token]` | Public invoice payment page (Stripe Checkout) | No |
| `/q/[token]` | Public quote accept/decline page | No |
| `/home` | Home dashboard (post-login landing) | Yes |
| `/dashboard` | Lead management table | Yes |
| `/leads/[id]` | Lead detail | Yes |
| `/pipeline` | Kanban board + analytics | Yes |
| `/tasks` | Task list | Yes |
| `/expenses` | Expense tracker | Yes |
| `/bookkeeping` | Quotes + Invoices + P&L + AR + job costing (tabbed) | Yes |
| `/map` | Service-area property map | Yes, and gated on the `map` module |
| `/marketing` | Marketing insights panel | Yes |
| `/settings` | Pipeline schedules/runs, workflows, custom fields, message templates, order import, rescoring, Stripe Connect, connections | Yes |

Authentication is handled client-side: the JWT token is stored in `localStorage` under the key `axon_token`. Protected pages are wrapped in `<AuthGuard>` which redirects to `/login` if no token is present. A 401 response from any API call also clears the token and redirects.

---

## Deployment

### Frontend — Vercel

1. Push the repo to GitHub
2. Import the repo at [vercel.com/new](https://vercel.com/new)
3. Set **Root Directory** to `frontend`
4. Vercel auto-detects Next.js — no build command changes needed
5. Add environment variable:
   ```
   NEXT_PUBLIC_API_URL=https://your-api-domain.com
   ```
6. Deploy — every push to `master` triggers a new deployment

### Backend — Render / Railway

**Render (recommended — Blueprint provided):** the repo includes `render.yaml`, a ready-to-use [Render Blueprint](https://render.com/docs/blueprint-spec) that provisions the API service and a managed Postgres database together, runs migrations on every deploy (`preDeployCommand`), and generates the JWT secret automatically. Push the repo, then **New + → Blueprint** in Render and point it at this file. Because Render's web filesystem is ephemeral, the HCAD DuckDB is intentionally left unset in the blueprint (`SEED_SOURCE=hcad`, `PERMIT_DB_PATH=""`) — load county data into the managed Postgres database once with `tools/load_hcad_to_postgres.py` before running the pipeline. See [`docs/RENDER_DEPLOYMENT.md`](docs/RENDER_DEPLOYMENT.md) for the full walkthrough.

**Railway (manual alternative):**
1. Create a new project and connect your GitHub repo
2. Add a PostgreSQL service — Railway provides `DATABASE_URL` automatically
3. Set the start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
4. Add remaining environment variables (JWT secret, API keys)
5. Run migrations after deploy: `python db/migrate.py`

**After deploying the backend**, update your Vercel frontend environment variable `NEXT_PUBLIC_API_URL` to the backend's public URL, and add the frontend domain to the hardcoded `allow_origins` list in `api/main.py` (CORS origins aren't currently env-configurable).

---

## Database Migrations

Migrations live in `db/migrations/` as 53 numbered `.sql` files, run in filename order; the runner tracks applied migrations in a `schema_migrations` table. They span the core CRM foundation, multi-tenancy (`017_org_isolation.sql`), quotes, custom fields/plans/business types (the "generalization" phases), Stripe payments, two-way SMS, and the phased geo-scoring layer (`049`–`052`). Note that `db/schema.sql` is **not** a consolidated current schema — it predates the migration system and only mirrors the very first migration; the real current schema is the cumulative result of applying every file in `db/migrations/`.

```bash
# Run all pending migrations
python db/migrate.py

# Check what's been applied
python db/migrate.py status

# Scaffold a new migration file
python db/migrate.py create add_customers
```

Always test on a development database before applying to production.

---

## Authentication

- Passwords are hashed with bcrypt via `passlib`
- JWTs are signed with HS256 using `JWT_SECRET_KEY` from the environment — the app **hard-fails at startup** if it's unset (bypass for local dev only with `ALLOW_INSECURE_DEV_JWT=true`)
- Tokens expire after 8 hours
- Login is rate-limited (`api/ratelimit.py`) to slow brute-force attempts
- Sign in with Google/Apple is also supported (`api/oauth_verify.py`) — it's invite-only: it links to an existing user by verified email rather than self-registering a new account

To rotate credentials, update `JWT_SECRET_KEY` in your environment. All existing tokens will be immediately invalidated.

---

## Further Reading

- [`docs/DATA_PIPELINE.md`](docs/DATA_PIPELINE.md) — the primary pipeline architecture reference (NULL-only upsert, enrichment provenance, full step walkthrough)
- [`docs/geo_scoring.md`](docs/geo_scoring.md) — the geo scoring/clustering/prospecting layer, phase by phase
- [`docs/GENERALIZATION_ROADMAP.md`](docs/GENERALIZATION_ROADMAP.md) — the multi-vertical platform strategy (plans, business types, custom fields, child objects)
- [`docs/COST_OPTIMIZATION.md`](docs/COST_OPTIMIZATION.md) — HCAD-first enrichment strategy to minimize paid-API spend
- [`docs/RENDER_DEPLOYMENT.md`](docs/RENDER_DEPLOYMENT.md) — deploying on Render given its ephemeral filesystem
- [`docs/hcad_real_property_mapping.md`](docs/hcad_real_property_mapping.md) — column-level mapping of HCAD's raw export files
- [`docs/CODEBASE_REVIEW.md`](docs/CODEBASE_REVIEW.md) — architecture review and technical-debt/product roadmap
