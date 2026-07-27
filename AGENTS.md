# Axon CRM — Agent Orientation

Guidance for AI coding agents working in this repository. Read this first for conventions; read `README.md` for the exhaustive feature list, API endpoint catalog, and full project-structure tree.

## Project overview

Axon CRM is a full-stack, multi-tenant business intelligence and CRM platform. It was originally built for home-service contractors and is being generalized to serve other verticals (insurance agencies, retail, professional services) from the same codebase.

Two halves:

1. **Backend** — FastAPI + PostgreSQL, raw SQL via `psycopg2`. Serves the CRM API and houses a standalone data-acquisition/lead-scoring pipeline.
2. **Frontend** — Next.js 16 / React 19 / TypeScript / Tailwind v4, deployed to Vercel.

The core loop: pull property/lead data from public and paid sources, score leads with configurable per-vertical signals, surface the highest-opportunity prospects in a mobile-first dashboard, and layer on CRM features (Kanban pipeline, tasks, notes, quotes, invoices, payments, expenses, marketing insights, call tracking, workflow automation).

## Technology stack

- **Runtime:** Python 3.11+ (backend), Node.js 20.9+ / 22 (frontend)
- **Web framework:** FastAPI 0.111+, Uvicorn
- **Database:** PostgreSQL, migrations are plain SQL files, `psycopg2` raw SQL
- **ORM/validation:** Pydantic v2 for request/response schemas (`api/models.py`)
- **Auth:** JWT (`python-jose`) + bcrypt (`passlib`); Google/Apple OIDC in `api/oauth_verify.py`
- **Scheduling:** APScheduler inside the FastAPI process (`api/scheduler.py`)
- **Frontend:** Next.js 16.2.6, React 19.2.4, TypeScript 5, Tailwind CSS v4, MapLibre GL, Lucide icons
- **Payments/integrations:** Stripe (Connect Express + Billing), Twilio (SMS/voice), Resend (email), Anthropic (receipt OCR)
- **Data stores:** PostgreSQL (primary), DuckDB (local HCAD mirror, read-only), optional `h3` for geo heatmaps
- **ML:** dependency-free pure-Python logistic regression in `pipeline/ml/`

## Project structure

```text
.
├── api/                    # FastAPI backend
│   ├── main.py             # App entry: lifespan, CORS, router registration + module gating
│   ├── deps.py             # get_db, get_current_user, dict_fetch helpers
│   ├── models.py           # Pydantic schemas
│   ├── security.py         # JWT + bcrypt
│   ├── entitlements.py     # Module/plan catalog and require_module guard
│   ├── business_types.py   # Vertical presets (terminology, categories, defaults)
│   ├── scheduler.py        # APScheduler jobs: pipeline, ML retrain, workflows, billing ticks
│   ├── accounts.py         # Org provisioning + business-type seeding
│   ├── billing.py          # Plan/subscription logic
│   └── routes/             # ~40 route modules
├── pipeline/               # Data-acquisition + scoring pipeline (runs standalone or via scheduler)
│   ├── seed.py             # Address seeding (RentCast / HCAD / CSV)
│   ├── hcad_enrichment.py  # Free Harris County backfill
│   ├── property.py         # Paid property-detail gap-filling (RentCast)
│   ├── contact.py          # Skip-trace enrichment (BatchData/Versium)
│   ├── demographics.py     # Household/life-event enrichment
│   ├── scorer.py           # Orchestrates scoring per ZIP
│   ├── scoring.py          # Pure scoring math (DB-free, testable)
│   ├── profiles.py         # Vertical profile registry
│   ├── geo_*.py            # Geo scoring, clustering, H3, prospecting
│   └── ml/                 # Predictive lead scoring subsystem
├── db/
│   ├── migrate.py          # Sequential SQL migration runner
│   ├── schema.sql          # Baseline schema (migrations are authoritative)
│   └── migrations/         # Numbered .sql files 0000–0061+
├── frontend/               # Next.js app
│   ├── app/                # App-router pages
│   ├── components/         # React components (design-system primitives in ds/)
│   ├── lib/                # api.ts, types.ts, nav.ts, terminology.ts, auth.ts
│   └── hooks/              # useEntitlements, useTerminology, useKanbanDnd
├── tests/                  # pytest suite
├── scripts/                # CLI helpers (create_user, set_account_plan, etc.)
├── tools/                  # HCAD DuckDB build/load and pipeline utilities
├── docs/                   # Deep dives (DATA_PIPELINE, RENDER_DEPLOYMENT, etc.)
├── config.py               # All env-overridable tuning: DB, API keys, weights, thresholds
├── run_pipeline.py         # Standalone CLI pipeline entry point
├── render.yaml             # Render Blueprint for backend + managed Postgres
└── requirements.txt        # Python deps; requirements-dev.txt adds pytest
```

## Build and test commands

Run backend commands from the repo root; frontend commands from `frontend/`.

```bash
# Backend setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # add -r requirements-dev.txt for tests

# Run the API (http://localhost:8000)
uvicorn api.main:app --reload --port 8000

# Tests — pytest, config in pytest.ini (testpaths=tests, pythonpath=.)
pytest                                   # whole suite
pytest tests/test_scoring.py            # one file
pytest -k geo                           # by keyword

# Database migrations
python db/migrate.py                     # apply all pending
python db/migrate.py status              # show applied/pending
python db/migrate.py create <name>       # scaffold next numbered .sql

# Users / plans (CLI)
python scripts/create_user.py --username admin --email you@x.com --role owner
python scripts/set_account_plan.py --help

# Data pipeline (standalone from the API)
python run_pipeline.py --zip 77396 --vertical roofing --account-id 1
python run_pipeline.py --zip 77396 --skip seed,geocode --account-id 1

# Frontend
npm install
npm run dev       # http://localhost:3000
npm run build     # production build (typechecks)
npm run lint      # eslint
```

There is no root-level Python linter/formatter configured; match surrounding style. The frontend uses ESLint via `npm run lint`.

## Code style guidelines

- **Match the file you are in.** Do not impose a new style; mirror comment density, naming, and structure.
- **Multi-tenancy rule:** every CRM-owned table has `account_id`. Every query that touches tenant data must scope by `account_id`. The current user comes from `Depends(get_current_user)` in `api/deps.py`. Forgetting this leaks data across tenants.
- **Pure logic split:** keep dependency-free computation in its own module so it is unit-testable without a DB or network. Examples: `api/messaging.py`, `api/import_logic.py`, `api/invoice_logic.py`, `api/lead_logic.py`, `pipeline/equity.py`, `pipeline/job_value.py`, `pipeline/scoring.py`.
- **Pipeline rule — degrade gracefully:** paid/optional steps no-op cleanly when no API key is configured. Never make a step hard-fail because a key is missing.
- **Pipeline rule — cost discipline:** free HCAD steps run before paid sources; paid upserts write non-NULL only, so money is spent only on genuine field gaps.
- **Late imports are acceptable** to avoid circular dependencies, especially between `api/` modules.

## Testing instructions

- `pytest.ini` anchors the suite: `testpaths = tests`, `pythonpath = .`, `python_files = test_*.py`.
- `conftest.py` at the repo root sets the pytest rootdir so `import config` and `import pipeline.scoring` resolve without installing a package.
- The project has ~1,000+ tests. Run targeted tests when touching a module (`pytest tests/test_scoring.py`).
- Many pipeline tests exercise pure scoring logic and do not need a database; route tests use FastAPI's `TestClient` and may need `DATABASE_URL` set.
- When adding a feature with non-trivial computation, add a matching `tests/test_*.py` and keep it dependency-free where possible.

## Security considerations

- **JWT secret:** `JWT_SECRET_KEY` is required. The API refuses to start without it unless `ALLOW_INSECURE_DEV_JWT=true` is set for local development only (`api/security.py`).
- **Tenant isolation:** `account_id` is the trust boundary. Always scope queries by it.
- **Public/token routes:** customer-facing pages (pay, public quote/invoice), Stripe/Twilio webhooks, public intake, and landing-page endpoints are intentionally ungated. Do not add `get_current_user` dependencies to them.
- **Shared secrets:** `PUBLIC_INTAKE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_BILLING_WEBHOOK_SECRET`, and Twilio signature verification are used for server-to-server auth.
- **Secrets live in `.env` only.** Never commit credentials. `.env` is in `.gitignore`.
- **Missing API keys fail soft:** endpoints that depend on optional integrations (Resend, Stripe, Twilio, Anthropic, BatchData/Versium) return 503 or skip gracefully when keys are unset.

## Key architecture conventions

### Multi-tenancy
- An **account** is an organization/tenant.
- Property uniqueness is `(account_id, address, zip)` — each org gets its own copy of a property.
- Raw HCAD reference tables (`hcad_*`) are shared and not scoped by account.

### Feature modules and plans
- Optional features are grouped into modules: `prospecting`, `map`, `invoicing`, `bookkeeping`, `quotes`, `marketing`, `automation`, `policies`, `orders`, `appointments`, `calls`.
- `core` features (leads, Kanban, tasks, notes, history, export) are always on.
- Source of truth: `api/entitlements.py` (`MODULE_KEYS`, `PLAN_CATALOG`, `require_module`).
- Whole routers are gated in `api/main.py` with `dependencies=[Depends(require_module("x"))]`; mixed-concern routers (e.g., `pipeline.py`) gate per-endpoint.
- Keep `MODULE_KEYS` in sync with `frontend/lib/nav.ts`.

### Business-type presets
- Each account has a **business type** (`api/business_types.py`): `home_services`, `general_sales`, `professional_services`, `insurance_agency`, `retail`.
- Presets bundle terminology overrides, category picklists, whether the property pipeline applies, default modules, stages, fields, templates, and workflows.
- Terminology resolves in layers: `home_services` is the base; other presets merge overrides on top. Keep keys in sync with `frontend/lib/terminology.ts`.

### Data pipeline
- Order of steps: seed → census → geocode → hcad_enrichment → select (optional trim) → property (RentCast) → permits → storm → scorer → select (precision trim) → contact → demographics → signals.
- Free steps run before paid steps; HCAD runs before RentCast.
- Scoring weights live in `config.py` (`DEFAULT_WEIGHTS`, `VERTICAL_WEIGHTS`); weights must sum to 1.0 per vertical. Grade bands are in `config.py` (`GRADE_BANDS`).
- The ML predictive layer is separate from rule-based scoring. `SCORER_MODE` controls whether learned scores are computed/shown. The trainer is pure Python; do not make scikit-learn/lightgbm/shap required.

## Database migrations

- Sequential numbered SQL files in `db/migrations/` (currently `0000`–`0061+`), tracked in a `schema_migrations` table.
- **Always create new migrations with `python db/migrate.py create <name>`** — never hand-edit an already-applied migration.
- Render runs `python db/migrate.py` as its pre-deploy command (`render.yaml`).

## Deployment

- **Frontend:** Vercel from the `frontend/` directory.
- **Backend:** Render via `render.yaml` (managed Postgres + Python web service).
- Render-specific notes:
  - Use a paid/starter Postgres plan — the free tier expires after ~30 days.
  - The DuckDB is ephemeral on Render; load HCAD data into the managed Postgres with `tools/load_hcad_to_postgres.py`.
  - Set `SEED_SOURCE=hcad` and `PERMIT_DB_PATH=""` in production.
  - Set `JWT_SECRET` to a generated random value.
  - See `docs/RENDER_DEPLOYMENT.md` for the full HCAD load flow.

## Useful files to read first

- `api/main.py` — what is wired up
- `api/deps.py` — auth and DB dependencies
- `api/entitlements.py` — module gating
- `api/business_types.py` — vertical presets
- `config.py` — tuning surface and env vars
- `run_pipeline.py` — standalone pipeline CLI
- `frontend/lib/api.ts` — all frontend API calls
- `frontend/lib/nav.ts` — module-gated navigation
- `docs/DATA_PIPELINE.md` and `docs/RENDER_DEPLOYMENT.md` — deeper context
