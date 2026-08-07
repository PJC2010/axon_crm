# CLAUDE.md

Guidance for AI assistants working in this repository. Keep it current when architecture or workflows change.

`README.md` is the exhaustive human reference (features, full API endpoint list, project-structure tree, deployment). This file is the fast-orientation + conventions layer — read the README when you need endpoint-level or feature-level detail.

## What this is

**Axon CRM** — a multi-tenant CRM for local service businesses. Two halves:

1. **Backend** (`api/`, `pipeline/`, `db/`, `config.py`) — FastAPI + PostgreSQL, raw SQL via psycopg2. Serves the CRM API *and* houses a standalone data-acquisition/lead-scoring pipeline.
2. **Frontend** (`frontend/`) — Next.js 16 / React 19 / TypeScript / Tailwind v4, deployed to Vercel.

The backend deploys to Render (see `render.yaml`, `docs/RENDER_DEPLOYMENT.md`).

## Commands

Run backend commands from the repo root; frontend commands from `frontend/`.

```bash
# Backend setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # + requirements-dev.txt for tests

# Run the API (http://localhost:8000)
uvicorn api.main:app --reload --port 8000

# Tests — pytest, config in pytest.ini (testpaths=tests, pythonpath=.)
pytest                                    # whole suite
pytest tests/test_scoring.py             # one file
pytest -k geo                             # by keyword

# Database migrations
python db/migrate.py                      # apply all pending
python db/migrate.py status               # show applied/pending
python db/migrate.py create <name>        # scaffold next numbered .sql

# Users / plans (CLI)
python scripts/create_user.py --username admin --email you@x.com --role owner
python scripts/set_account_plan.py --help

# Data pipeline (standalone from the API)
python run_pipeline.py --zip 77396 --vertical roofing
python run_pipeline.py --zip 77396 --skip seed,geocode

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
npm run build      # production build (typechecks)
npm run lint       # eslint
```

There is no root-level Python linter/formatter configured; match surrounding style. The frontend uses ESLint (`npm run lint`).

## Architecture & the conventions that matter

### Multi-tenancy: everything is scoped by `account_id`
An **account** is an organization/tenant (`db/migrations/0017_org_isolation.sql`). Every CRM-owned table carries `account_id`, and the property uniqueness key is `(account_id, address, zip)` — each org gets its own copy of a property. Raw county reference tables (`hcad_*`) are **shared** (not scoped).

**`parcels` is also shared** (`db/migrations/0065_shared_parcels.sql`, `pipeline/parcels.py`). It caches the tenant-*independent* half of a property — assessor data, coordinates, storm history, neighborhood — once, so seeding a ZIP for an org is an `INSERT … SELECT` inside the database rather than a per-org re-run of the enrichment pipeline. `properties.parcel_id` links a tenant row back to its parcel. Data moves in four directions, all server-side: `ensure_from_hcad` (build the cache), `seed_account` (materialize a tenant's rows), `promote` (share a run's findings back), `sync` (adopt findings). **`parcels.SHARED_COLS` is a security boundary** — skip-traced contacts and the demographic append are per-account *purchases* and CRM state is tenant opinion, so neither is ever promoted. Add a column there only if it is a free, objective fact about the parcel.

**When writing any query that touches tenant data, scope it by `account_id`.** The current user (with `account_id`) comes from `Depends(get_current_user)` in `api/deps.py`. Forgetting the scope leaks data across tenants — this is the single most important correctness rule in the codebase.

### Feature gating via modules & plans
Optional features are grouped into **modules** (`prospecting`, `map`, `invoicing`, `bookkeeping`, `quotes`, `marketing`, `automation`, `policies`, `orders`, `appointments`). `core` features (leads, Kanban board, tasks, notes, history, export) are always on and are deliberately *not* modules.

- Source of truth: `api/entitlements.py` (`MODULE_KEYS`, `PLAN_CATALOG`, `get_account_modules`, `require_module`).
- Whole-module routers are gated in `api/main.py` with `dependencies=[Depends(require_module("x"))]`. Mixed-concern routers (e.g. `pipeline.py`) gate **per-endpoint** instead.
- Public, token-addressed routers (pay page, public quote/invoice, Stripe/Twilio webhooks, public intake) stay **ungated** — they must work without a login or plan.
- Gating is **permissive**: an account with no `account_plans` row gets the full set, so gating never silently strips access. Keep `MODULE_KEYS` in sync with the frontend nav (`frontend/lib/nav.ts`).
- Plans are **sold** via Stripe subscription billing (`api/billing.py`, `api/routes/billing.py`): Checkout + customer portal + a platform webhook that writes `plan_name` back to `account_plans`. Advertised prices live in `billing.PLAN_PRICING` — keep them in sync with `PLAN_CATALOG` and the landing page's pricing section. Self-serve signups (`api/routes/signup.py`, provisioning in `api/accounts.py::provision_owner`) start on a `pro` trial; a daily scheduler tick downgrades expired trials to `starter`.

### Business-type presets (generalization layer)
Axon began home-services-specific but is general. Each account has a **business type** (`api/business_types.py`) that bundles terminology overrides (lead↔deal, property↔record), category picklists, whether the property pipeline applies, and default modules. Same code-defined-catalog pattern as entitlements. Terminology resolves in layers: `home_services` is the base, other presets merge on top; frontend ships matching defaults (`frontend/lib/terminology.ts`, `useTerminology.ts`). Keep terminology keys in sync across `api/business_types.py`, `frontend/lib/terminology.ts`, and the frontend fallback.

### The data pipeline (`pipeline/`, `run_pipeline.py`)
A 13-step, per-ZIP enrichment + scoring flow that runs **independently of the API** (also schedulable — see `api/scheduler.py`). Steps in order: seed → census → geocode → hcad_enrichment → select(trim) → property(RentCast) → permits → storm → scorer → select(precision-trim) → contact(skip-trace) → demographics → signals. See README "How the Pipeline Works" for the table.

Key design rules when touching the pipeline:
- **Provider-pluggable, degrade-gracefully.** Paid/optional steps (contact, demographics, property sources, geo H3, ML accelerators) no-op cleanly when no API key/dependency is configured. `config.py` env vars default to `""` = "step skipped". Never make a step hard-fail because a key is missing.
- **Cost discipline.** Free HCAD backfill runs *before* any paid source, and rows are queued for a paid source only when they have a genuine gap. A row is stamped (`enrichment_flags.<source>_checked`) with the date it was last asked about, so a field the source structurally cannot fill (sale price in a non-disclosure state like Texas) does not keep the row eligible and re-bill it forever.
- **Filling vs. verifying are separate jobs.** A pipeline run is per-ZIP and only fills gaps. `pipeline/backfill.py` sweeps a whole account instead — `audit()` is a free SQL-only null report, `sweep()` re-asks RentCast and applies `pipeline/reconcile.py`'s policy. The policy is the load-bearing part: static county facts are **fill-only** (HCAD outranks an AVM), values that genuinely move are **refreshable**, and disagreements are recorded in `property_field_audits` for review rather than applied. Overwriting is opt-in (`mode="refresh"`) because `estimated_value` feeds scoring, so a refresh moves grades.
- **Scoring is rule-based and testable.** `pipeline/scorer.py` / `pipeline/scoring.py` compute 0–100 scores + A/B/C/D grades from weighted signals. Weights live in `config.py` (`DEFAULT_WEIGHTS`, `VERTICAL_WEIGHTS` — must sum to 1.0 per vertical; optional signals use `weights.get()`). Adding a vertical = adding a key. Grade bands are in `config.py` (`GRADE_BANDS`).
- **Predictive ML** (`pipeline/ml/`) is a *separate* subsystem from `scorer.py`: a dependency-free pure-Python logistic-regression trainer. scikit-learn/lightgbm/shap are commented-out optional accelerators — do not make them required.

### Pure logic split out for testability
A recurring pattern: pure, dependency-free logic lives in its own module so it can be unit-tested without a DB or network — e.g. `api/messaging.py` (merge-field rendering), `api/import_logic.py` / `order_import_logic.py` (CSV parsing), `api/invoice_logic.py`, `api/lead_logic.py`, `pipeline/equity.py`, `pipeline/job_value.py`, `pipeline/reconcile.py`. When adding a feature with non-trivial computation, follow this split and add a `tests/test_*.py`.

Where SQL is built by interpolating column names (`pipeline/db.py::fetch_missing_any`, `pipeline/backfill.py`), the allowlist check against `db.ALL_COLS` **is** the injection guard — never skip it, and note that psycopg2 binds `%s` positionally in the order placeholders appear in the statement text, which is not always the order the clauses were written in.

### Backend layout
- `api/main.py` — app entry: CORS, lifespan (starts APScheduler jobs), router registration + module gating. Read this first to understand what's wired up.
- `api/routes/` — ~30 route modules. Route docstrings list their endpoints.
- `api/deps.py` — `get_db` (per-request psycopg2 conn), `dict_fetchall`/`dict_fetchone`, `get_current_user` (JWT via header **or** `?token=` query param for `<a download>` CSV exports).
- `api/models.py` — Pydantic request/response schemas.
- `api/security.py` — JWT + bcrypt. `api/oauth_verify.py` — Google/Apple OIDC.
- `api/scheduler.py` — APScheduler: pipeline runs, ML retrain, workflow tick, account/geo rescore, recurring invoices.
- `config.py` — the tuning surface: DB URL, API keys, scoring weights/verticals, job-value model, thresholds. All env-overridable via `.env` (see `.env.example`).

### Frontend notes
- **Next.js 16 is intentional and non-standard.** `frontend/CLAUDE.md` → `frontend/AGENTS.md` warns: this version has breaking changes vs. training data. Read the relevant guide in `frontend/node_modules/next/dist/docs/` before writing Next-specific code.
- `frontend/lib/api.ts` — all API client calls. `frontend/lib/types.ts` — TS interfaces. `frontend/lib/nav.ts` — module-gated nav. `frontend/lib/auth.ts` — token in localStorage.
- Hooks: `useEntitlements` (`hasModule()`), `useTerminology`, `useKanbanDnd`.
- Design-system primitives in `frontend/components/ds/`.

## Database migrations
Sequential numbered SQL files in `db/migrations/` (currently 65, `0000`–`0066`, 4-digit zero-padded so filename order matches numeric order), tracked in a `schema_migrations` table. **Always create new migrations with `python db/migrate.py create <name>`** — never hand-edit an already-applied migration; add a new one. Render runs `python db/migrate.py` as its pre-deploy command.

## Git workflow for this task
- Work on branch `claude/claude-md-docs-hg7dzp`. Create it from latest `master` if needed.
- Commit with clear messages; push with `git push -u origin claude/claude-md-docs-hg7dzp`.
- Do **not** open a PR unless explicitly asked.

## Further reading
`docs/` has deeper dives: `TECHNICAL_DEEP_DIVE.md`, `DATA_PIPELINE.md`, `geo_scoring.md`, `COST_OPTIMIZATION.md`, `GENERALIZATION_ROADMAP.md`, `RENDER_DEPLOYMENT.md`, `TWILIO_SETUP.md`, `CODEBASE_REVIEW.md`, `hcad_real_property_mapping.md`.
