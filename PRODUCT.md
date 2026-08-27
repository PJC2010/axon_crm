# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary (confirmed):** Harris County home-services contractor owner-operators — roofing and similar trades — who do outbound prospecting. Small teams: the owner buys and configures; the owner and a handful of reps work leads daily, often from a phone in the field (door-knocking, calling, driving territories). The shipped landing positioning targets exactly this user.

**Secondary (supported, deliberately lower priority):** insurance agencies, retail, and appointment-based businesses served by the business-type preset layer (`api/business_types.py`). Future work keeps this layer intact but does not let it dilute the contractor experience.

**Platform operator:** the owner (Pete) administers tenants cross-account via the `/admin` surface.

## Product Purpose

Axon replaces cold-calling random purchased lists with data-ranked prospecting, then runs the rest of the job: leads → Kanban pipeline → quotes → invoices → online payments → expenses/bookkeeping, with tasks, messaging, and workflow automation around it. Success means a contractor's team spends its outbound hours on the properties statistically most likely to need the service — and can trace exactly why each one ranked.

It is a commercial multi-tenant SaaS: self-serve signup starts a `pro` trial, plans (`starter`/`growth`/`pro`) are sold via Stripe, and features are gated by modules.

## Positioning

Two claims, confirmed as one combined position (both are the moat, neither alone):

1. **County-data scoring engine.** Leads originate from public records — appraisal roll, permits, equity, sale recency, storm exposure, demographics — and carry explainable 0–100 scores with visible signals. No list-buying, no black box.
2. **Territory / geo intelligence.** Heatmaps, customer clustering, neighbor-of-won-job targeting, and territory awareness turn the scored parcels into a map a crew can actually work.

Shipped public tagline: **"Territory intelligence for Harris County contractors"** ("Know which properties are worth calling first.").

## Operating Context

- Outbound, often storm-driven demand: after a hail/wind event, speed to the right doors in the right neighborhoods is the job.
- Texas is a non-disclosure state — sale prices are structurally unavailable from public records; the pipeline is designed around that.
- Data supply chain: HCAD appraisal roll + county ArcGIS parcel centroids (free), Census, RentCast (paid AVM/detail), skip-trace and demographic append (paid, per-account purchases), Twilio (calls/SMS/tracking numbers), Stripe (billing + Stripe Connect customer payments).
- Deployment: FastAPI/PostgreSQL backend on Render, Next.js frontend on Vercel. The data pipeline and scheduler share the web process (memory/cost discipline is a real constraint, documented in CLAUDE.md).
- Usage scene: mobile-first. The dashboard, lead cards, and map get used in trucks and on doorsteps, not only at desks.

## Capabilities and Constraints

- Multi-tenant: every CRM table scoped by `account_id`; shared county reference data (`parcels`, `hcad_*`) is tenant-independent by design.
- Module/plan gating is permissive (no plan row → full access); core CRM (leads, Kanban, tasks, notes, export) is always on.
- Business-type presets override terminology (lead↔deal, property↔record) and default modules per vertical.
- Scoring is rule-based, weighted per vertical, and explainable; a separate dependency-free ML subsystem is optional.
- Pipeline coverage is **Harris County only today**; per-ZIP runs, residential-only filtering, free-sources-before-paid cost discipline.
- **Undecided (do not invent):** timing/priority of expansion beyond Harris County; any evolution of plan pricing.

## Brand Commitments

- **Name: Axon** (also "Axon CRM") — established across product, domain metadata, and landing.
- Existing identity assets (shipped, but not explicitly pinned as binding during init — treat as incumbent evidence): brand mark at `frontend/public/mark.svg` / `mark-dark.svg` / `favicon.svg` (diamond with cross cutout, teal `#1A5A75`), promo video `frontend/public/axon-promo.mp4`, landing styles `frontend/app/landing.css`.

## Evidence on Hand

- **Stage: pre-launch, zero customers (confirmed).** No testimonials, case studies, customer counts, logos, or third-party results exist. **Nothing of that kind may ever be fabricated** — persuasion surfaces must lean on the mechanism itself: real county data, real scores, real maps, the promo video.
- Real first-party assets: a county-wide Harris parcel cache with coordinates, live HCAD/Census-derived data, a working end-to-end product, `frontend/public/axon-promo.mp4`.

## Product Principles

1. **Show the signals.** Every score, grade, and rank must be explainable on demand; opacity breaks the core promise.
2. **Real data or nothing.** Pre-launch means no social proof exists — demonstrate with the live mechanism, never invent proof.
3. **Deep in Harris County before wide.** County-level depth is the moat; the generalization layer survives, but the contractor experience leads.
4. **Built for the truck, not the desk.** Mobile-first is a usage fact, not a checkbox; field scanability outranks density.
5. **Cost discipline is product design.** Free public sources first, paid lookups only for genuine gaps, graceful degradation when a key is missing.
