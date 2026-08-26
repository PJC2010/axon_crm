# Axon CRM — Multi-Vertical Generalization Roadmap

*Drafted: July 2026 · Scope: evolving Axon from a home-services lead-gen CRM into a general
CRM platform for the majority of small business types (insurance agencies, retail,
appointment-based services, professional services), while keeping the property-data
enrichment pipeline as a differentiator for the verticals where it applies.*

Companion doc: [`CODEBASE_REVIEW.md`](CODEBASE_REVIEW.md) covers technical debt and the
enrichment roadmap; this doc covers the platform generalization strategy.

---

## 1. Where we are: Phases 1–3 are done

The generalization effort has already landed three layers of scaffolding. Everything in
this roadmap builds on them rather than inventing new mechanisms.

| Phase | What it added | Key files |
|---|---|---|
| 1 — Feature modules & plans | Per-account module gating (prospecting, map, invoicing, bookkeeping, quotes, automation) behind starter/growth/pro plans; `require_module()` dependency; module overrides per account | `api/entitlements.py`, `db/migrations/0039_account_plans.sql`, `frontend/hooks/useEntitlements.ts`, `frontend/components/ModuleGate.tsx`, `frontend/lib/nav.ts` |
| 2 — Business types & terminology | Account-level `business_type` presets (`home_services`, `general_sales`, `professional_services`) bundling terminology overrides (lead↔deal↔client, property↔account), category picklists, `property_based` flag, default modules | `api/business_types.py`, `db/migrations/0040_account_business_type.sql`, `frontend/lib/terminology.ts`, `frontend/hooks/useTerminology.ts` |
| 3 — Custom fields | Account-defined field schema (text/number/date/boolean/select) + JSONB value bag on the core record | `api/routes/record_fields.py`, `db/migrations/0041_custom_fields.sql`, `properties.custom_fields` |

Also already vertical-agnostic: multi-tenancy (`account_id` on every table, every query
scoped), tasks, invoicing/AR/payments, quotes, expenses, bookkeeping/P&L, workflow rules,
configurable kanban stages, CSV import/export, email/SMS delivery (Resend/Twilio),
receipt OCR.

**What is still baked in (the real remaining work):**

1. **The core record is a property.** The primary table is literally `properties`
   (year_built, square_footage, equity, garage_spaces, HCAD fields…); "lead" is a UI
   alias. Non-property businesses can hide these columns but the record has no natural
   second object (a policy, an order, an appointment) to hang revenue and dates on.
2. **The workflow engine has one trigger type.** `api/workflow_engine.py` fires only on
   `status_change`. Every vertical's killer automation (insurance renewals, retail
   win-back, service reminders) is *date*-driven.
3. **Scoring is hardwired to property signals.** `pipeline/score.py` + `VERTICAL_WEIGHTS`
   / `FACTOR_META` in `config.py` read property columns; the engine shape (weighted
   signals → 0–100 grade + explanation) is generic but the signal definitions aren't.
4. **The prospecting pipeline, Map page, and territory filters assume geocoded Houston
   property data.** Correctly gated behind the `prospecting`/`map` modules and the
   `property_based` flag already — they become the home-services/real-estate premium
   modules rather than something to generalize.

---

## 2. What each vertical actually needs (research)

Surveyed: insurance AMS/CRMs (AgencyBloc, EZLynx), retail CRM/POS platforms (Voyado,
Celerant, KORONA), appointment platforms (Mindbody), legal CRMs (Clio), and the
horizontal-CRM data model (HubSpot/Salesforce custom objects).

| Vertical | Primary object besides the contact | Killer workflow | Platform gap it exposes |
|---|---|---|---|
| **Insurance agency** | **Policy** — carrier, line (auto/home/life/health/commercial), policy #, premium, effective/expiration dates, commission | Renewal & X-date automation ("policy expires in 30/60/90 days"), commission tracking, cross-sell (auto→home→umbrella) | Date-based workflow triggers; a second record type with roll-ups |
| **Retail** | **Order / purchase** — items, total, channel, date | RFM segmentation (recency/frequency/monetary), win-back ("no purchase in 90 days"), loyalty | Customer-base analytics instead of outbound lead gen; POS/e-commerce import |
| **Appointment-based** (salon, fitness, clinics) | **Appointment** + membership | Booking reminders, no-show reduction, recurring billing | Scheduling primitives; subscription invoices |
| **Professional services** (law, accounting) | **Matter / engagement** | Retainers, deadline tracking, document-heavy comms | Mostly covered by existing preset + custom fields + quotes |
| **Home services / real estate** | Property (today's core) | Enrichment pipeline + event triggers | — (existing moat; see `CODEBASE_REVIEW.md` §3) |

Two cross-vertical lessons:

- **The horizontal-CRM pattern is objects → records → fields → associations.** Axon has
  records and fields; it lacks a way to attach *other object types* to a record. A small
  number of first-class child objects covers ~90% of small-business needs without
  building a full metadata-driven object engine.
- **Vertical feel = terminology + defaults, not forks.** What makes AgencyBloc feel
  "insurance" or Mindbody feel "fitness" is preset language, preset pipeline stages,
  preset automations, and preset reports over a shared engine. Phase 2's preset
  mechanism is exactly the right chassis — the presets just need to carry more payload.

Sources: [AgencyBloc insurance CRM](https://www.agencybloc.com/agency-management-system/insurance-crm/),
[EZLynx AMS features](https://www.ezlynx.com/blog/posts/modern-insurance-agency-management-system/),
[Voyado retail CRM guide](https://voyado.com/resources/blog/best-crm-for-retail/),
[POS+CRM integration](https://www.connectpos.com/pos-and-crm/),
[HubSpot data architecture](https://www.hyphadev.io/blog/complete-guide-hubspot-crm-data-architecture),
[Clio legal CRM](https://www.clio.com/features/legal-crm-software/).

---

## 3. Architecture decision: incremental core, typed child objects

**Decision:** keep the `properties` table as the single core record store. Treat its
real-estate columns as an optional "property detail bundle" shown only when the business
type's `property_based` flag is true. Model vertical data as **typed child object tables**
(`policies`, `orders`, `appointments`) that are `account_id`-scoped and reference the core
record, plus custom fields for the long tail. Revisit renaming `properties` → `records`
behind a SQL view only after non-property verticals prove out.

**Rejected alternatives:**

- *Big-bang refactor to a generic `records` core with a `property_details` extension
  table.* Cleaner on paper, but every one of the 50+ endpoints, the pipeline, and the
  frontend touch `properties` via raw SQL — a rename is a multi-week migration with zero
  user-visible value, undertaken before we know what non-property customers need. Do it
  later, if ever, behind a view.
- *Full metadata-driven custom-objects engine (HubSpot-style `object_defs`).* Maximum
  flexibility, but small businesses don't define objects — they pick a template. Typed
  tables give real columns, real indexes, real roll-up SQL, and obvious code. If a third
  wave of verticals needs bespoke objects, add the metadata engine then; the association
  pattern established by the typed tables becomes its blueprint.

---

## 4. Roadmap

### Phase 4 — Generalize the engines (vertical-neutral, highest leverage)

The three platform gaps that block *every* new vertical, fixed once:

1. **Date/recurrence-based workflow triggers.** Extend `workflow_rules` with a trigger
   config (`trigger_type: 'status_change' | 'date_offset' | 'inactivity'`, target field,
   offset days) and add a daily APScheduler tick that evaluates date rules per account
   (`api/scheduler.py` already hosts jobs; the engine in `api/workflow_engine.py` was
   designed for new trigger types — see also `CODEBASE_REVIEW.md` §3.1's `signal_event`
   trigger, same seam). Actions (create task, send notification) already exist.
   Examples unlocked: "policy renews in 30 days → create task", "no contact in 60 days →
   notify rep", "birthday → send email".
2. **Config-driven scoring profiles.** Refactor the scorer so a profile = a set of signal
   definitions (field, normalization, weight, label/description) resolved per business
   type, generalizing `VERTICAL_WEIGHTS` + `FACTOR_META`. Property signals become the
   `home_services` profile; add an **RFM profile** (recency/frequency/monetary over the
   orders table) for retail and a **renewal-proximity/cross-sell profile** (days to
   expiration, mono-line flag) for insurance. The explainable "why this score" UI
   (`frontend/components/lead/WhyThisScore.tsx`) works unchanged.
3. **Saved segments.** Named, shareable filter sets over records + custom fields (e.g.
   "A-grade, no policy, added <30d"). Feeds list views, CSV export, and later
   workflow targeting. Reuse the shared WHERE-builder consolidation already
   recommended in `CODEBASE_REVIEW.md` §2.3.

### Phase 5 — Associated objects: policies, orders, appointments

- Three typed tables, one pattern: `account_id` FK, `record_id` FK to the core record,
  status, money and date columns per object, `custom_fields` JSONB (reuse the Phase-3
  field-def mechanism with a `scope` column so accounts can extend objects too).
- CRUD routes follow the existing router conventions (`api/routes/quotes.py` is the best
  template: child-of-record + public token pattern).
- Roll-ups on the record drawer and dashboards: total premium in force / lifetime spend /
  next appointment; SQL aggregates, indexed by `(account_id, record_id)`.
- Object timelines merge into the existing `contact_history` activity feed.

### Phase 6 — Vertical preset packs (insurance first, then retail)

Extend the Phase-2 preset payload from {terminology, categories, modules} to a full
provisioning pack: default pipeline stages, enabled objects, default custom fields,
default date-triggered workflows, scoring profile, dashboard KPI layout, and expense
categories.

- **`insurance_agency` pack:** policy object on; stages `Prospect → Quoted → Bound →
  Renewal → Lost`; X-date workflows (90/30/7-day renewal tasks); commission fields on
  policy; cross-sell segment ("has auto, no home"); KPI row = premium in force, policies
  per client, retention rate, renewals next 30 days. Note the pipeline's existing
  new-mover/life-event data is a genuine insurance lead signal — a future bridge, not a
  Phase-6 requirement.
- **`retail` pack:** orders object on; orders CSV import (Square/Shopify export formats,
  reusing `api/routes/imports.py` guardrails and `IMPORT_MAX_BYTES`); RFM scoring
  profile; segments (VIP, at-risk, lapsed); win-back workflow; KPI row = repeat-purchase
  rate, avg order value, 90-day active customers.
- **Onboarding wizard:** business-type picker on first login → provision the pack →
  extend the existing onboarding checklist (`api/routes/auth.py`) with pack-specific
  steps ("import your book of business", "import your orders").
- Later packs: `appointments` (salon/fitness — needs Phase-7 recurring billing),
  enriched `professional_services` (matters = quotes+tasks composition).

### Phase 7 — Communication hub & recurring revenue

- Generalize invoice email/SMS (`api/notifications.py`) into contact-level messaging:
  template library with merge fields, per-record send log in `contact_history`, simple
  sequences (workflow action `send_template`).
- Recurring invoices: `recurrence` on invoices + scheduler tick that clones and sends —
  memberships (fitness/salon), retainers (professional services), maintenance contracts
  (home services). Builds directly on the complete invoice→payment→AR loop.

### Phase 8 — Integrations layer

- Priority order: **Square/Shopify** (retail orders sync — replaces Phase-6 CSV
  import), **Google Calendar** (appointments), **QuickBooks export**
  (all verticals), and eventually **carrier/IVANS-AL3 download parsing** (the long-term
  insurance moat — what separates an AMS from a generic CRM).

### Platform prerequisites (gate before onboarding new-vertical customers)

From `CODEBASE_REVIEW.md` §2, these become more urgent as account types multiply:
tenant-isolation API tests (zero endpoint coverage today), JWT-secret hard-fail, rate
limiting on login/import/pipeline-run, the missing `properties(account_id, status)`
index, and kanban pagination.

---

## 5. Sequencing rationale & success criteria

Phase 4 before 5 because date triggers and scoring profiles are useful to *existing*
home-services accounts on day one (maintenance reminders, stale-lead nudges) — new
engine, zero new UI surface. Phase 5 before 6 because packs need objects to provision.
Insurance before retail because it exercises the whole stack (object + date workflows +
roll-ups) with CSV-importable data, while retail's full value depends on POS integration
(Phase 8).

| Phase | Done when |
|---|---|
| 4 | A home-services account gets an auto-created task from a date rule; a `general_sales` account scores leads without any property signal; a saved segment drives the lead table and export |
| 5 | A policy/order/appointment can be created on a record via API+UI; record drawer shows roll-ups; activity feed shows object events |
| 6 | A brand-new account picks "Insurance agency" at signup and lands in a working renewal-pipeline CRM (stages, fields, workflows, KPIs) without touching settings |
| 7 | A membership invoice recurs monthly unattended; a templated email sends from a record and logs to history |
| 8 | A Shopify store's orders sync on a schedule and update RFM scores |
