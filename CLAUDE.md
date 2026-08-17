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
python scripts/set_platform_admin.py --email you@x.com --grant   # flag the first platform admin

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

**`parcels` is also shared** (`db/migrations/0065_shared_parcels.sql`, `pipeline/parcels.py`). It caches the tenant-*independent* half of a property — assessor data, coordinates, storm history, neighborhood — once, so seeding a ZIP for an org is an `INSERT … SELECT` inside the database rather than a per-org re-run of the enrichment pipeline. `properties.parcel_id` links a tenant row back to its parcel. Data moves in four directions, all server-side: `ensure_from_hcad` (build the cache), `seed_account` (materialize a tenant's rows; optional `owner_occupied_only`/`built_only` filters), `promote` (share a run's findings back), `sync` (adopt findings). **`parcels.SHARED_COLS` is a security boundary** — skip-traced contacts and the demographic append are per-account *purchases* and CRM state is tenant opinion, so neither is ever promoted. Add a column there only if it is a free, objective fact about the parcel.

**Coordinates come free from `hcad_parcel_centroids`** (migration 0070) — a shared mirror of the county's public ArcGIS parcel layer (`tools/load_parcel_centroids.py`), joined into the cache by `parcels.fill_coords_from_centroids` (runs inside every production seed and in the county build). The county-wide build is `tools/build_parcel_cache.py` → `pipeline/county_build.py`: every ZIP cached + coordinate-filled (Census batch covers what centroids miss), **zero paid geocode calls by construction** — the build path never imports `pipeline.geocode`, enforced by `tests/test_county_build.py`. It runs OUTSIDE the web process (external runner or Render one-off job; see the OOM note in `config.py`) and creates no `properties` rows — per-tenant materialization stays on-demand.

**When writing any query that touches tenant data, scope it by `account_id`.** The current user (with `account_id`) comes from `Depends(get_current_user)` in `api/deps.py`. Forgetting the scope leaks data across tenants — this is the single most important correctness rule in the codebase.

**The one sanctioned exemption is the platform-admin surface** (`api/routes/admin.py`, migration 0073): deliberately cross-tenant queries for the platform operator, guarded router-wide by `require_platform_admin` (`api/deps.py`), which checks `users.is_platform_admin` — a boolean orthogonal to the tenant `role` column (the string `'admin'` in `require_owner`'s tuple is *tenant*-owner power; never reuse it for platform access). The flag is never carried in the JWT, so revocation is immediate. Rules for that surface: every mutation records an `admin_audit_log` row (`api/admin_audit.py`) in the same transaction as the change; no endpoint may declare a query param named `token` (collides with `get_current_user`'s `?token=` CSV-export fallback); pure logic lives in `api/admin_logic.py`. Login outcomes (password + OAuth) are recorded to `auth_events` best-effort via `api/auth_events.py` — responses stay generic, the failure classification is server-side only. Flag the first admin with `scripts/set_platform_admin.py`; the frontend lives under `frontend/app/admin/` behind `AdminGuard`, and the tenant `PATCH /api/users/{id}` refuses to touch platform admins so a tenant owner can't lock the platform out.

**Deleting is the database's job, not the endpoint's** (migration 0074). `DELETE /admin/accounts/{id}` is one `DELETE FROM accounts` because every FK into `accounts(id)` is `ON DELETE CASCADE` — the alternative, a hand-ordered list of forty DELETEs in Python, goes stale the first time someone adds a table. The two rules are not interchangeable: **accounts cascade, users `SET NULL`**. An account *is* its data; a user *owns* nothing — `created_by`/`assigned_to`/`actor_user_id` are attribution, so deleting a rep must unassign their leads, never delete the org's invoices. A new table therefore declares `REFERENCES accounts(id) ON DELETE CASCADE` and `REFERENCES users(id) ON DELETE SET NULL`, and the migration's closing `DO $$` block fails the deploy if any FK into either table is left un-cascaded. The one gap the cascade cannot see is a table carrying `account_id` with **no** FK — `auth_events` is deliberately one (0073) — so the endpoint deletes it by hand and then `_assert_account_purged` re-derives the account-scoped table list from the catalog and refuses to commit if anything survived. Shared tables (`parcels`, `hcad_*`) have no `account_id` and are untouched by design. Guards and the typed-name confirmation are pure functions in `admin_logic.py` (`validate_user_delete`, `validate_account_delete`); the frontend mirrors them so the danger zone explains itself instead of only 409-ing. `admin_audit_log` has no `account_id` and denormalizes `admin_username`, so the record of a deletion outlives both the org and the admin who performed it.

### Feature gating via modules & plans
Optional features are grouped into **modules** (`prospecting`, `map`, `invoicing`, `bookkeeping`, `quotes`, `marketing`, `automation`, `policies`, `orders`, `appointments`, `calls`). `core` features (leads, Kanban board, tasks, notes, history, export) are always on and are deliberately *not* modules.

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
- **A parcel is not a house.** The county roll is every *parcel*, so the free HCAD seed pulls in shopping centres, churches, school-district land and vacant lots; the RentCast seed has always filtered on `propertyType`, but that column is written **only** by RentCast and is NULL on every HCAD-seeded row. `pipeline/residential.py` is the one rule for "is this a home?", in the same Python + byte-compatible-SQL pair as `addr.py`/`owner.py`, with `pipeline/property_audit.py` as its free SQL audit + archive and `parcels.seed_account(residential_only=…)` as the seed-side filter. Reasons are **two-tier and the tiers are load-bearing**: `EXCLUDE` is structurally impossible for a dwelling and may be bulk-archived, `REVIEW` is reported and never acted on. The asymmetry is the whole design — a false positive archives a paying customer, a false negative leaves a visible bad row. Concretely, nothing may key on value, owner-occupancy, lot size or an LLC/LP/TRUST suffix (each describes a River Oaks estate as well as a strip mall); owner tokens match whole words **and** must not be plausible surnames (HCAD writes names LAST-FIRST, so "CHURCH JOHN A" is a homeowner); and `properties` is also the contact book — `address` is nullable and inbound call/SMS/web-form leads carry none, so a parcel-shape rule must require an address before reading its shape. Archiving is the *only* durable cleanup: `seed_account`'s `NOT EXISTS` re-creates a deleted row from the shared cache on the next run.
- **Scoring is rule-based and testable.** `pipeline/scorer.py` / `pipeline/scoring.py` compute 0–100 scores + A/B/C/D grades from weighted signals. Nothing in `FACTOR_META` reads property type, size or owner-entity type, so the scorer has **no vocabulary for "not a house"** — a mall scores on age/equity/sale-recency like any home, `EQUITY_TARGET` saturates at $100k, and the `absentee` signal rewards `owner_occupied = false`. `job_value` then multiplies per-sqft by building area with no cap, so a single commercial row injects six figures of phantom pipeline into forecasts and the digest. Filtering non-residential rows out is what protects those numbers, not a scoring tweak. Weights live in `config.py` (`DEFAULT_WEIGHTS`, `VERTICAL_WEIGHTS` — must sum to 1.0 per vertical; optional signals use `weights.get()`). Adding a vertical = adding a key. Grade bands are in `config.py` (`GRADE_BANDS`).
- **Predictive ML** (`pipeline/ml/`) is a *separate* subsystem from `scorer.py`: a dependency-free pure-Python logistic-regression trainer. scikit-learn/lightgbm/shap are commented-out optional accelerators — do not make them required.
- **Scheduled jobs share the API's process and its memory.** `api/scheduler.py` starts APScheduler in the FastAPI lifespan, so a batch job that loads a whole table OOM-kills the *web service*. Any job here must bound its footprint: stream with a named/server-side cursor (psycopg2 buffers the entire result set client-side otherwise), project the columns you actually read instead of `SELECT *`, and cap retained rows — see `ML_MAX_TRAINING_ROWS` / `ML_MAX_FIT_ROWS` in `config.py` and `pipeline/ml/dataset.py`. Log what a cap dropped rather than truncating silently.
- **A per-ZIP run must cost O(ZIP), not O(account).** The same process runs the web app, and a run that scales with everything ever seeded gets slower forever and holds a worker while it does. `recompute_neighborhood_values(conn, account_id, zips=[...])` is the pattern: scope the write to the geohash cells the run touched, but keep each cell's *statistics* over every member of that cell (cells straddle ZIP lines), so the numbers don't move — `scripts/verify_neighborhood_scoping.py` diffs the two paths against a real database. Three guards back it up in `api/scheduler.py`: `RUN_MAX_SECONDS` (watchdog — a run that exceeds it is cancelled with `error='timeout'`), `PIPELINE_RUN_LOCK_KEY` (single-writer advisory lock, so the 2-instance deploy can't double-fire or pile runs up behind a wedged one), and `reconcile_stale_runs()` (a redeploy leaves rows at `running` forever otherwise).

### Pure logic split out for testability
A recurring pattern: pure, dependency-free logic lives in its own module so it can be unit-tested without a DB or network — e.g. `api/messaging.py` (merge-field rendering), `api/import_logic.py` / `order_import_logic.py` (CSV parsing), `api/invoice_logic.py`, `api/lead_logic.py`, `pipeline/equity.py`, `pipeline/job_value.py`, `pipeline/reconcile.py`. When adding a feature with non-trivial computation, follow this split and add a `tests/test_*.py`.

Where SQL is built by interpolating column names (`pipeline/db.py::fetch_missing_any`, `pipeline/backfill.py`), the allowlist check against `db.ALL_COLS` **is** the injection guard — never skip it, and note that psycopg2 binds `%s` positionally in the order placeholders appear in the statement text, which is not always the order the clauses were written in.

### How a property is matched across sources
`properties` is the join point; HCAD and RentCast attach to it independently and are never matched to each other. The one identifier both sides share is the assessor parcel number, carried as `parcel_apn` (HCAD `acct` ↔ RentCast `assessorID`, migration 0068).

- **HCAD → row**: exact match on a normalized address, in a per-ZIP dict. **`pipeline/addr.py` is the only normalization rule** — `normalize()` for Python lookups, `sql_normalize()` for query-built keys, `axon_normalize_address()` (migration 0065) for the `parcels` generated column. All three must stay byte-compatible; a key built by one and looked up by another that disagrees fails **silently**, which is exactly how HCAD enrichment used to skip every address containing punctuation. `tests/test_addr.py` runs the SQL in a real DuckDB and compares key-for-key — keep that test working rather than hand-copying the expression.
- **RentCast → row**: not a join. One lookup per property by address string, resolved by RentCast's own parser with `limit=1`. Because that can silently resolve to a neighbouring parcel, `reconcile.verify_record` checks the echoed address before anything is written and records a rejection under the `address` field in `property_field_audits`. `addr.same_address` is deliberately lenient — it gates whether paid data is accepted, so a false negative throws away data you already bought. Layered over it, **shadow-mode parcel verification**: when the row's `parcel_apn` and the record's `assessorID` disagree (`pipeline/parcel_id.py::same_parcel` — the only APN comparison rule *across vendors*; a RentCast APN is never a SQL join key), the record is still applied but the disagreement is recorded under `parcel_apn` in `property_field_audits`. Within HCAD's own data there is one sanctioned APN equality join — `parcels.parcel_apn = hcad_parcel_centroids.acct` — sound because both stored forms are produced by the same expression, `pipeline/parcel_id.py::sql_normalize_apn`, DuckDB-parity-tested against `normalize_apn` in `tests/test_parcel_id.py`. Measure that false-accept rate before promoting `same_parcel` to a gate.
- **Both enrichment paths are fill-only.** `upsert_properties` *overwrites* any non-None column it is handed, so the per-ZIP detail step drops fields the row already holds before writing (pipeline/property.py) and the sweep goes through `reconcile`'s policy. Overwriting remains opt-in via the sweep's `mode="refresh"` only. New RentCast response fields join `map_record` as free ride-alongs — added to `SOURCE_FIELDS` (config.py) **only** if a gap in that field alone should trigger a paid lookup; a new column starts NULL everywhere, so listing it there re-queues entire ZIPs.
- **CSV import → row**: `api/routes/imports.py` dedups through the *same* address rule, matching on `axon_normalize_address` rather than on the raw string, so an imported "12 ash st." lands on the lead the pipeline seeded as "12 ASH ST" instead of forking it. It has to: `ON CONFLICT (account_id, address, zip)` is exact-string *and* never fires when `zip` is NULL (Postgres treats NULLs as distinct), so a re-import used to duplicate every ZIP-less row. The unique key is still the insert-race guard. Address-less contacts key on email (partial unique index), then on phone **plus** name — `twilio_inbound.normalize_phone`'s last-10-digits rule, with the name required because a household landline is shared and matching the number alone merges two people. A bare name is not an identity and does not dedup.

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
Sequential numbered SQL files in `db/migrations/` (currently 73, `0000`–`0074` with two historical gaps, 4-digit zero-padded so filename order matches numeric order), tracked in a `schema_migrations` table. **Always create new migrations with `python db/migrate.py create <name>`** — never hand-edit an already-applied migration; add a new one. Render runs `python db/migrate.py` as its pre-deploy command.

## Git workflow for this task
- Work on branch `claude/claude-md-docs-hg7dzp`. Create it from latest `master` if needed.
- Commit with clear messages; push with `git push -u origin claude/claude-md-docs-hg7dzp`.
- Do **not** open a PR unless explicitly asked.

## Further reading
`docs/` has deeper dives: `TECHNICAL_DEEP_DIVE.md`, `DATA_PIPELINE.md`, `geo_scoring.md`, `COST_OPTIMIZATION.md`, `GENERALIZATION_ROADMAP.md`, `RENDER_DEPLOYMENT.md`, `TWILIO_SETUP.md`, `CODEBASE_REVIEW.md`, `hcad_real_property_mapping.md`.
