# Axon CRM v1 — Codebase Review & Product Roadmap

*Review date: June 2026 · Scope: full repository (API, pipeline, frontend, schema)*

---

## 1. Executive summary

Axon CRM v1 is a multi-tenant CRM for small service businesses built on FastAPI + PostgreSQL (raw SQL via psycopg2) with a Next.js 16 / React 19 frontend. Its differentiator is the **property-data enrichment pipeline**: a 9-step ETL (RentCast seed → Census income → Google geocode → HCAD permits/features → volume selection → ATTOM detail → permit counts → vertical-weighted scoring → skip-trace) that turns a ZIP code into graded, explainable leads. Around that core sit a solid set of operations features: kanban pipeline with custom stages, tasks with assignment, invoicing/AR with aging, expense tracking, monthly P&L, job costing, CSV import/export, email/SMS invoice delivery, and a status-change workflow automation engine.

**What's strong:** the enrichment pipeline and explainable scoring (no competitor in the Jobber/Housecall Pro tier generates leads — they only manage them), clean multi-tenant isolation (`account_id` on every table), cost controls on paid APIs (Top-N caps, radius filters, grade gating on skip-trace), and a complete invoice → payment → AR loop.

**Top 5 things to address next:**

1. **Missing composite indexes** on `properties` for the two hottest access patterns (`account_id + status`, `id + account_id`) — cheap fix, broad impact.
2. **Security hardening**: remove the fallback JWT secret, add rate limiting to login/bulk/import endpoints, cap import file size.
3. **Aggregation in Python that belongs in SQL** (invoice aging, kanban grouping, onboarding checklist) plus several unpaginated endpoints.
4. **Event-driven enrichment** (new permits, just-sold homes, storm events, neighbor-of-won-job targeting) — the highest-leverage product investment; details in §3.
5. **API test coverage** — currently zero endpoint tests; the pipeline is tested but the CRM surface isn't.

---

## 2. Inefficiencies & technical debt

### 2.1 Database / query layer

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| D1 | High | **Missing `(account_id, status)` index on `properties`.** Pipeline stats run `GROUP BY status` filtered only by `account_id`; existing indexes cover `(zip, lead_score)`, `(vertical, score_grade)`, `(longitude, latitude)`, `archived_at`, and `(account_id, zip, lead_score)` — none serve this query, so it degrades to a scan as lead counts grow. The stats endpoint is called on every dashboard load. | `api/routes/pipeline.py:188-193`; indexes in `db/migrations/0000_properties.sql:46-48`, `db/migrations/0017_org_isolation.sql:83` |
| D2 | High | **N+1 query in the workflow engine.** `_get_lead_vertical()` is called inside the per-rule loop, re-fetching the *same* lead's vertical once per rule. Fetch it once before the loop. Bonus: the helper queries `properties` without an `account_id` filter — harmless today (value only used for comparison) but it breaks the "every query is tenant-scoped" convention. | `api/workflow_engine.py:30-36`, helper at `:64-68` |
| D3 | Medium | **Onboarding checklist runs 5 sequential `COUNT(*)` queries** (leads, contact history, invoices, workflows, expenses) on a per-page-load endpoint. One query with five `EXISTS` subselects does the same work in a single round trip — and `EXISTS` is also far cheaper than `COUNT(*)` on large tables since it stops at the first row. | `api/routes/auth.py:98-122` |
| D4 | Medium | **Invoice aging buckets computed in Python.** All open invoices are fetched, then date math and bucketing run in app code. A single `SUM(...) FILTER (WHERE ...)` or `CASE` query returns the five buckets directly with no row transfer. | `api/routes/invoices.py:115-149` |
| D5 | Medium | **Kanban board fetches every lead, then groups in Python — unpaginated.** `SELECT ... FROM properties WHERE account_id = ...` with no `LIMIT`, then a Python loop assigns rows to stages. With a few thousand leads this is a multi-MB payload on every board view. Add a per-stage limit (e.g., top 50 by score with a "load more") via a window function (`ROW_NUMBER() OVER (PARTITION BY status ORDER BY lead_score DESC)`). Note it also doesn't exclude archived leads at the SQL level. | `api/routes/pipeline.py:172-182` |
| D6 | Medium | **Job costing has no pagination.** The revenue/expense join returns every property that has ever had an invoice or expense; the frontend table renders all rows without virtualization. | `api/routes/bookkeeping.py:96-131`; `frontend/components/JobCostingTable.tsx` |
| D7 | Low | **`/api/zips` returns all distinct ZIPs unpaginated** — fine at current scale, worth a typeahead once orgs span many ZIPs. | `api/routes/leads.py` (`list_zips`) |
| D8 | Low | **CSV import inserts row-by-row** with a savepoint per row. Correct (one bad row doesn't kill the batch) but slow for large files; batching with `execute_values` plus per-batch fallback would be ~10-50× faster. | `api/routes/imports.py:87-99` |

### 2.2 Security

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| S1 | High | **Hardcoded fallback JWT secret.** If `JWT_SECRET_KEY` is unset, the app silently signs tokens with a publicly known string — anyone can forge an owner token. Fail hard at startup when the env var is missing (allow the fallback only under an explicit dev flag). | `api/security.py:8` |
| S2 | High | **No rate limiting anywhere.** Login is brute-forceable, the import endpoint can be hammered, and manual pipeline runs (which spend real API dollars) have no throttle. `slowapi` is a drop-in for FastAPI; start with login + import + pipeline-run. | `api/routes/auth.py`, `api/routes/imports.py`, `api/routes/pipeline.py` |
| S3 | High | **Import endpoint reads the entire upload into memory with no size cap** (`await file.read()`). A large upload can take down the worker. Enforce a max size and stream-parse. | `api/routes/imports.py:84` |
| S4 | Medium | **Bulk archive accepts unbounded, unvalidated ID lists.** Parameterization prevents injection, but `ids` isn't validated as integers and has no length cap (DoS vector via a giant `IN (...)` list). Validate with Pydantic (`list[int]`, `max_length`). | `api/routes/leads.py:275-290` |
| S5 | Medium | **Workflow failures are swallowed silently** — the status change succeeds, the rule's action fails, and the user never finds out (`log.exception` only; `update_status` also discards `workflow_results` instead of returning them). Surface failures in the API response or an activity log entry. | `api/workflow_engine.py:38-43`; `api/routes/leads.py:131-135` |

### 2.3 Architecture / code quality

- **Process-local scheduler state.** Pipeline cancellation uses an in-memory `set` (`api/scheduler.py:18`). Under multiple Uvicorn workers, a cancel request landing on worker A won't stop a run executing on worker B. Move the flag into `pipeline_runs` (a `cancel_requested` column) — the run already polls between steps.
- **`sys.path.insert` import hacks** at call sites (`api/scheduler.py:80-81`, `api/routes/pipeline.py` rescore endpoints). Make the repo a proper package or fix the path once at app startup.
- **Duplicated per-route patterns:** the "fetch lead by `id + account_id` or 404" block is re-implemented across `leads.py`, `history.py`, `notes.py`, and `invoices.py`; filter/WHERE-builder logic is re-implemented in four route modules (`leads.py`, `invoices.py`, `expenses.py`, `pipeline.py`). Extract `get_lead_or_404()` and a shared filter builder into `api/deps.py`.
- **No API tests.** ~1,100 lines of tests cover only the pipeline (scoring, seed normalization). The 50+ CRM endpoints — auth, tenant isolation, invoice payment state transitions — have zero coverage. Tenant-isolation tests in particular are cheap insurance for a multi-tenant product (assert account B can never read account A's lead).

### 2.4 Frontend

- **Home dashboard fires 7 API calls on mount** (`frontend/components/HomeDashboard.tsx:93-101`). `Promise.allSettled` is the right call, but everything blocks the initial paint. Render the shell immediately, load KPIs first, and lazy-load analytics/forecast below the fold.
- **Lead table refetches on every filter change with no debounce** (`frontend/components/Dashboard.tsx:61`) and no caching of previously fetched pages.
- **Inline style objects throughout components** create new objects every render and defeat `React.memo`; extract to module-level constants or CSS classes.
- **No virtualization** on potentially large tables (job costing, lead table).

### 2.5 Prioritized fix list

1. Add indexes: `properties(account_id, status)` and verify PK-led lookups are covered (one migration, biggest perf-per-effort ratio).
2. JWT secret hard-fail + login/import/pipeline-run rate limiting + import size cap (S1-S3).
3. Fix workflow N+1 and surface workflow action failures (D2, S5).
4. Collapse checklist to one `EXISTS` query; move aging buckets to SQL (D3, D4).
5. Paginate kanban and job costing (D5, D6).
6. Add API tests, starting with tenant isolation and invoice payment-state logic.

---

## 3. Data enrichment opportunities ⭐

This is the product's moat — Jobber, Housecall Pro, and ServiceTitan all assume the customer brings their own leads. Axon *generates* them. Everything below builds on infrastructure that already exists; nothing requires a new platform.

> For the multi-vertical platform strategy (insurance, retail, appointment-based businesses), see [`GENERALIZATION_ROADMAP.md`](GENERALIZATION_ROADMAP.md).

### 3.1 Event-driven lead triggers (highest value)

Today the pipeline scores **static state** (home age, equity, garage). The most valuable signals in home services are **timing events** — and the schema already stores the raw material:

- **"Just sold" alerts.** `last_sale_date` is already refreshed on each pipeline run. A delta-detection step ("sale date changed since last run") turns a weekly re-run into a new-mover feed. New homeowners spend heavily on services in their first 6-12 months. Surface as a "🔥 New owner" badge + auto-created follow-up task (the workflow engine's `create_task` action already exists — it just needs a new trigger type alongside `status_change`).
- **"New permit filed" alerts.** `hcad_permits` has `issue_date` per parcel and the pipeline already computes `permit_count_24mo`. Detecting *new* permits since the last run identifies owners actively investing in their home right now — the single best time to cross-sell adjacent work.
- **Score-change notifications.** `score_updated_at` exists but nothing reacts to score movement. A lead jumping from C to A after enrichment should ping the owner.

Implementation shape: one new pipeline step that diffs key fields against their previous values (snapshot in `enrichment_flags` or a small `signal_events` table), plus a new workflow trigger type `signal_event`. The workflow engine (`api/workflow_engine.py`) was clearly designed for additional trigger types.

### 3.2 Weather / storm-damage triggers

NOAA/NWS storm event data (free API) by county/ZIP → after a hail or high-wind event, temporarily boost scores for affected ZIPs in roofing/fencing/pool verticals and notify the owner ("ZIP 77002 took 2″ hail Tuesday — 340 B+ leads affected"). Fits the existing pattern: one new free enrichment step (like `pipeline/census.py`) writing a `recent_storm` signal, plus a scoring weight per vertical in `config.py`.

### 3.3 Neighbor-of-customer targeting

The cheapest lead a service business gets is the house next to a job site ("we're already on your street"). All ingredients exist: `latitude`/`longitude`/`geohash` columns, the geohash index, and the `won` status transition (logged in `stage_transitions`). When a lead hits `won`, flag same-geohash-prefix / radius neighbors and emit a "5 neighbors of your new customer" task or saved filter. This is nearly pure SQL over data already paid for.

### 3.4 More verticals (cheapest win)

`config.py` defines only three weight profiles: `epoxy_flooring`, `pool_maintenance`, `solar`. The signals already collected support at least five more with **zero new data cost** — pure config plus a workflow-defaults entry in `VERTICAL_DEFAULTS`:

| Vertical | Signals already in the schema |
|---|---|
| Roofing | `year_built` (roof-age proxy), permit history, storm trigger (§3.2) |
| HVAC | home age 15-25y (system end-of-life), `zip_median_income` |
| Fencing | `lot_size`, `has_pool` (pool code compliance), new-owner signal |
| Landscaping / lawn care | `lot_size`, `owner_occupied`, income |
| Pressure washing / exterior | home age, pool, income |

Each new vertical widens the addressable market for the same pipeline spend.

### 3.5 Score freshness & decay

Scores are computed once and drift: `score_updated_at` exists, the explanation endpoint even detects weight drift, but nothing decays stale scores or schedules re-scores. Add a staleness indicator in the UI ("scored 6 months ago") and fold re-scoring of stale leads into scheduled runs (the `rescore` endpoints already exist in `api/routes/pipeline.py`).

### 3.6 Enrichment provenance & cost transparency

`enrichment_flags` (JSONB) already tracks sources per lead. Surfacing "what we know, where it came from, how fresh it is, what it cost" per lead — and per-run cost summaries in `pipeline_runs.result_json` — turns a black box into a trust feature, and helps owners tune Top-N/radius/grade-gate controls they already have.

### 3.7 AI next-best-action

`frontend/components/AIInsightsPanel.tsx` is already stubbed. The natural v1: combine score factors, `contact_history` outcomes, and time-in-stage into a daily ranked call list ("call these 10 first, here's why"). The explainable-scoring foundation (`pipeline/scoring.py` breakdowns) makes the "why" credible rather than hand-wavy.

---

## 4. Feature roadmap for service businesses

Table-stakes gaps observed in the product survey, tiered by effort. (Per product direction: online-payment/Stripe work and expanding county data beyond Harris County are explicitly **out of scope**.)

**Quick wins**

- **More workflow triggers/actions.** The engine executes reliably but supports one trigger (`status_change`) and two actions. Add `time_in_stage` ("in *quote_sent* 7 days → follow-up task") and `invoice_overdue` triggers — both are simple scheduled scans, and APScheduler is already running in-process.
- **Custom tags** on leads (only vertical + status exist today) — small schema addition, big filtering payoff.
- **Calendar view of tasks** (due dates exist; there's just no calendar rendering) + recurring tasks for maintenance-contract verticals like pool care.

**Medium effort**

- **Quotes/estimates with quote→invoice conversion.** Invoice line items are 90% of the data model; add a `type`/status distinction, expiration dates, and an accept-and-convert flow. Critical for the `quote_sent` pipeline stage to mean something.
- **File/photo attachments** (before/after photos, signed quotes, receipts — `expenses.receipt_url` exists but nothing populates it). One S3-compatible bucket + an `attachments` table referenced by lead/invoice/expense.
- **Automated payment reminders.** Resend/Twilio delivery already works for invoices; an overdue-invoice scan that sends a templated nudge is mostly wiring.
- **Two-way communication log.** Notes and contact history are manual; logging outbound email/SMS (and inbound via Twilio webhooks) onto the lead timeline closes the biggest CRM gap.

**Strategic**

- **Customer-facing portal** (view quotes/invoices, approve work).
- **Mobile-first field views** (the dashboard has responsive touches, but field crews need a phone-sized "today's jobs + tasks" view; a PWA gets 80% of a native app).
- **QuickBooks/accountant export** — start with a clean P&L + expense CSV pack (mostly exists) before attempting live sync.

---

## 5. Suggested sequencing

1. **Week 1 — hardening sprint:** indexes (D1), JWT/rate-limit/import-cap (S1-S3), workflow N+1 + error surfacing (D2, S5), checklist + aging SQL consolidation (D3, D4). Small, independent, low-risk.
2. **Next — new verticals (§3.4) + score freshness (§3.5):** pure config/SQL, immediately widens the market with zero new data spend.
3. **Then — event-driven signals (§3.1) with one new workflow trigger type**, starting with "just sold" (data already flows). This is the feature that makes the weekly pipeline run feel alive rather than batch.
4. **In parallel — neighbor targeting (§3.3)** as a lightweight win on the `won` transition.
5. **Then — quotes + payment reminders + tags** from §4 to round out the day-to-day workflow, with API tests (tenant isolation first) added alongside each touched module.
