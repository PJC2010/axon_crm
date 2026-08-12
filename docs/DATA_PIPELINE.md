# Axon CRM — Data Pipelines Reference

Last reviewed: 2026-07-01. Covers every data flow in the system: the lead
enrichment pipeline (the main one), the ML scoring pipeline, the HCAD data-store
build, user-driven imports (contacts CSV, Meta/social exports, receipt OCR), and
outbound delivery.

## Architecture at a glance

- **Primary store:** PostgreSQL (`DATABASE_URL`). The `properties` table is the
  center of gravity — every enrichment step writes it via a **NULL-only upsert**
  (`pipeline/db.py::upsert_properties`, `ON CONFLICT (account_id, address, zip)`),
  so a field is only ever paid for while it is still empty. The
  `enrichment_flags` JSONB column records which source filled each row
  (e.g. `{"seed": "hcad", "property": "rentcast", "permits": "hcad"}`).
- **Local free data:** `harris_county.duckdb` (`PERMIT_DB_PATH`) — a read-only
  DuckDB mirror of Harris County Appraisal District (HCAD) assessor + permit
  data, with a Postgres `hcad_*` table fallback when the file is absent.
- **Orchestration:** `run_pipeline.py::run_zip()` (CLI) and
  `api/scheduler.py::_run_pipeline()` (API/scheduled runs) execute the same step
  sequence. Run order is deliberate: **all free steps run before any paid step**,
  and free HCAD data runs before RentCast so the paid detail step sees a
  smaller queue of NULL fields.

---

## 1. Lead enrichment pipeline (the main pipeline)

Processes one ZIP (or an HCAD region's ZIPs) per run, for one account.

### Step 1 — Seed (`pipeline/seed.py`)
- **Source (selectable via `SEED_SOURCE` / `--seed-source` / `--seed-csv` / region):**
  - `rentcast` (default, **paid**) — RentCast `GET /properties?zipCode=&limit=500&offset=`
    with `X-Api-Key`, paginated.
  - `hcad` (**free**) — every parcel in the ZIP from the local DuckDB
    (`seed_from_hcad_zip`), pre-filling assessor fields so paid steps have less to do.
    Region runs (`region_id`) use `seed_from_hcad` scoped to one HCAD neighborhood.
  - CSV file (`seed_from_csv`) — dev/manual seeding.
- **Filters:** records whose `propertyType` is not in `SEED_PROPERTY_TYPES`
  (Single Family, Condo, Townhouse, Manufactured by default) are dropped *before*
  the DB so they never incur downstream paid enrichment. A ZIP already present
  for the account is skipped unless `--force-seed`.
- **Auto-expansion:** if a ZIP yields fewer than `SEED_EXPAND_THRESHOLD` (50) rows,
  the search expands to nearby ZIPs within `SEED_EXPAND_RADIUS_MI` (then same-city
  ZIPs) up to `SEED_EXPAND_TARGET` (200), via `pipeline/geo_expand.py` (`uszipcode`).
- **Data pulled:** address, city, state, zip, latitude/longitude, property_type,
  year_built, square_footage, estimated_value, last_sale_date, last_sale_price,
  owner_name (RentCast nests it as `owner.names[0]`), owner_occupied,
  garage_spaces, garage_type. HCAD seeds additionally: lot_size, mailing_address,
  hcad_neighborhood_code/name.

### Step 2 — Census income (`pipeline/census.py`)
- **Source:** US Census Bureau ACS 5-year — `https://api.census.gov/data/2022/acs/acs5`,
  variable `B19013_001E` (median household income). **Free**; `CENSUS_API_KEY`
  optional (only raises rate limits).
- **Mechanism:** one GET per **unique ZIP** (de-duped, not per property).
- **Data pulled:** `zip_median_income`.

### Step 3 — Geocode (`pipeline/geocode.py`)
- **Source:** Google Maps Geocoding API (`GOOGLE_GEOCODE_KEY`). Paid, large free tier.
  Skipped entirely if the key is unset.
- **Mechanism:** `GET /geocode/json` per row missing lat/lng, 0.05 s throttle;
  geohash-6 computed locally via `geohash2`.
- **Data pulled:** `latitude`, `longitude`, `geohash`.

### Step 4 — HCAD backfill (`pipeline/hcad_enrichment.py` → `pipeline/hcad_store.py`)
- **Source:** local `harris_county.duckdb` (read-only), falling back to Postgres
  `hcad_*` mirror tables. **Free — zero API calls.** Runs *before* the paid
  detail step on purpose.
- **Mechanism:** loads the ZIP's parcels + extra features, joins to seeded rows
  on a normalized address (`pipeline/addr.py::normalize`), backfills only NULL
  fields. Pool/slab are written as HCAD ground truth when present.
- **Data pulled:** year_built, square_footage, lot_size, estimated_value
  (appraised), last_sale_date, owner_name, owner_occupied, ownership_years
  (derived), mailing_address, hcad_neighborhood_code/name, has_pool,
  has_cracked_slab, garage_spaces.

### Step 4.5 — Selection (capped runs only) (`pipeline/select.py`)
- When `--top-n` and/or `--address`+`--radius` are set, marks the top subset
  (`enrichment_selected = TRUE`) so paid steps only touch that subset. Runs after
  the free steps, before any paid step. Free.

### Step 5 — Property detail (`pipeline/property.py`)
- **Source:** RentCast (`PROPERTY_FIELD_SOURCES`, env-overridable; default
  `rentcast`). **Paid.** (ATTOM was removed from the project 2026-07-01.)
- **Mechanism:** per-address lookup (RentCast `GET /properties?address=`),
  filling only fields still NULL after the free steps. `estimated_equity` is
  then computed by `pipeline/equity.py` from sale data, falling back to
  `EQUITY_FALLBACK_PCT` (0.6) × estimated_value.
- **Data pulled:** year_built, square_footage, estimated_value,
  last_sale_date, last_sale_price, owner_name, owner_occupied, ownership_years,
  garage_spaces, garage_type → estimated_equity (derived).

### Step 6 — Permits (`pipeline/permits.py`)
- **Source:** HCAD permit data from the local DuckDB (Postgres fallback). **Free.**
  (`--permit-csv` is deprecated and raises.)
- **Mechanism:** counts non-voided permits issued in the last 24 months per
  parcel, joined on normalized address.
- **Data pulled:** `permit_count_24mo`.

### Step 6.5 — Storm / hail (`pipeline/storm.py`)
- **Source:** NOAA/NWS Local Storm Reports via the Iowa Environmental Mesonet
  (`IEM_LSR_URL` GeoJSON API). The NWS Weather Forecast Office is resolved per
  ZIP from its centroid via `NWS_POINTS_URL`, so any market works without
  configuration (`STORM_WFO` is only a fallback). **Free, no key.**
- **Mechanism:** the `STORM_LOOKBACK_MONTHS` (24) window is fetched in
  `STORM_FETCH_CHUNK_MONTHS` (6) slices, because IEM silently truncates a
  response at 10,000 features — an active office exceeds that in a single
  24-month pull on snow reports alone. Reports are memoized per (office, day),
  so ZIPs sharing an office fetch once. Each property is then matched by
  Haversine distance within `STORM_MATCH_RADIUS_MI` (1.0 mi).
- **Event types:** hail, thunderstorm/non-thunderstorm wind, tornado (incl.
  landspout). Marine and waterspout reports are excluded — they describe no
  property damage. The feed uses NWS product abbreviations (`TSTM WND DMG`,
  not `THUNDERSTORM WIND`); `pipeline/storm.py::_TYPE_MAP` must match exactly.
- **Data pulled:** last_storm_date, last_storm_type, hail_size_in, storm_count_24mo.

### Step 7 — Scoring (`pipeline/scorer.py` + `pipeline/scoring.py`)
- **Source:** none (pure computation over the enriched row). Free.
- **Mechanism:** weighted signal scoring using `DEFAULT_WEIGHTS` or per-vertical
  `VERTICAL_WEIGHTS` in `config.py` (verticals: epoxy_flooring, pool_maintenance,
  solar, roofing, hvac, fencing, landscaping, pressure_washing). Signals include
  home age, sale recency, equity, garage, income, neighborhood value ratio
  (`pipeline/neighborhood.py`), permits, pool, slab, storm, plus demographic
  signals (refi, credit, children, gardening, home_improvement, absentee,
  tenure, life_stage). With `SCORER_MODE` = `shadow`/`learned`, the logistic
  model (`pipeline/ml/`) also produces `ml_conversion_prob`.
- **Data produced:** lead_score (0–100), score_grade (A ≥ 75, B ≥ 55, C ≥ 35,
  else D), score_factors, [ml_conversion_prob, ml_model_version].
  `estimated_job_value` ballpark comes from `pipeline/job_value.py`
  (`JOB_VALUE_MODEL` per vertical, fallback `JOB_VALUE_FALLBACK_PCT` × value).

### Step 7.5 — Trim (capped runs only) (`pipeline/select.py`)
- Cuts the over-sampled selection back to exactly `top_n` using the now-real
  scores, *before* the expensive skip-trace step. Free.

### Step 8 — Contact / skip-trace (`pipeline/contact.py`) — optional
- **Source:** pluggable via `CONTACT_PROVIDER`: **`versium`** (Contact Append) or
  **`batchdata`**. No-op when unset. **Paid — highest per-record cost.**
- **Mechanism:** per-record append for rows with an `owner_name` (business/trust
  owner names are skipped); gated by `CONTACT_MIN_GRADE`, capped by
  `CONTACT_MAX_ROWS_PER_ZIP` (200), 0.1 s throttle.
- **Data pulled:** contact_name, contact_phone, contact_email.

### Step 9 — Demographics / life events (`pipeline/demographics.py`) — optional
- **Source:** pluggable via `DEMO_PROVIDER`: **`versium`** (Demographic Append)
  or **`batchdata`**. No-op when unset. **Paid.**
- **Mechanism:** per-record append for rows with `owner_name`; gated by
  `DEMO_MIN_GRADE`, capped by `DEMO_MAX_ROWS_PER_ZIP` (200).
- **Data pulled:** refi_date, credit_rating, home_improvement_flag, has_children,
  gardening_flag, owner_age, life_stage, est_household_income, age_range,
  estimated_net_worth, loan_to_value, marital_status, occupation,
  senior_in_household, pets_flag, decorating_flag, credit_lines_count,
  mortgage_rate_type.

### Final — Timing signals (`pipeline/signals.py`)
- Diffs sale/permit/storm/score fields against the previous run's baseline
  (`just_sold`, `new_permit`, `storm_event`, `score_changed` on grade-band
  crossings), records `signal_events`, and fires `signal_event` workflow rules
  (`api/workflow_engine.py`). Free.

### Triggers
- **CLI:** `python run_pipeline.py --zip 77002 --account-id 1 --vertical roofing`
  (flags: `--zip-file`, `--skip <steps>`, `--top-n`, `--address`/`--radius`,
  `--limit`, `--seed-csv`, `--seed-source`, `--permit-csv`, `--force-seed`).
- **API:** `POST /api/pipeline/run` (`api/routes/pipeline.py`) — owner-only,
  rate-limited per account (real dollars), gated on the `prospecting` module.
  Takes exactly one of `zip` or `region_id` (HCAD neighborhood, seeded free),
  plus optional `top_n` / `center_address` / `radius_mi`. Runs execute in
  APScheduler's thread pool with per-step cancellation
  (`DELETE /api/pipeline/runs/{id}`); status/results land in `pipeline_runs`.
- **Scheduled:** APScheduler (`api/scheduler.py`, started in `api/main.py`) on
  cron rows in `pipeline_schedules` (per-account day-of-week + hour, managed via
  `/api/pipeline-schedules`).
- **Re-score only:** `POST /api/pipeline/rescore` (one ZIP) and
  `/api/pipeline/rescore-all` (whole org; also recomputes the neighborhood value
  benchmark) — scoring without re-running acquisition.

### Coverage checkpoints (cost-efficient HCAD-first workflow)

CLI runs log a per-field null-count table at two points: **after the HCAD step**
(what the free steps left NULL = what RentCast would be paid to fill) and
**after the property-detail step** (what remains for the BatchData skip-trace /
demographics steps). `python -m pipeline.coverage --zip <ZIP>` prints the same
table on demand. `PROPERTY_FIELD_SOURCES` (env, comma-separated) can pin the
property step to `rentcast` only.

Recommended two-phase run for a new ZIP:
1. **Free pass:** `python run_pipeline.py --zip <ZIP> --account-id <ID>
   --seed-source hcad --skip property,contact,demographics` — seeds every parcel
   from local HCAD, then inspect the post-HCAD coverage table.
2. **Paid fill:** `python run_pipeline.py --zip <ZIP> --account-id <ID>
   --vertical <v> --skip seed,census,hcad` — RentCast fills only remaining NULL
   fields, scoring runs, then BatchData fills contact/demographics (grade-gated
   via `CONTACT_MIN_GRADE` / `DEMO_MIN_GRADE`, capped per ZIP).

### Cost controls baked in
- NULL-only upserts — never refetch a field that's already populated.
- HCAD (free) runs before RentCast; HCAD seeding avoids the paid scan entirely.
- Seed property-type allowlist drops non-target types before any paid step.
- Top-N / radius selection before paid steps; precision trim before skip-trace.
- Grade gates (`CONTACT_MIN_GRADE`, `DEMO_MIN_GRADE`) + per-ZIP caps on append steps.
- ZIP-already-seeded short-circuit; per-account rate limit on manual runs.
- Shared retry/backoff for all outbound HTTP (`pipeline/http.py`,
  `HTTP_RETRIES`/`HTTP_BACKOFF`).

See `docs/COST_OPTIMIZATION.md` for the HCAD-first strategy and roadmap.

---

## 2. HCAD data-store build (upstream of the pipeline)

One-time / periodic tooling in `tools/` that produces the free local data the
pipeline leans on:

- `tools/build_hcad_duckdb.py` — builds `harris_county.duckdb` from HCAD source
  exports (parcels, extra features, permits). Field mapping documented in
  `docs/hcad_real_property_mapping.md`.
- `tools/load_hcad_to_postgres.py` — loads the same data into Postgres `hcad_*`
  mirror tables for deploys where the DuckDB file isn't available (e.g. Render).
- `tools/export_hcad_zip.py` / `tools/hcad_export/` — per-ZIP extracts.
- `pipeline/hcad_store.py` — the read-only query layer both enrichment and
  seeding use (`query_parcels_for_zip`, `query_permits`, region queries); opens
  DuckDB `read_only=True` so concurrent API/scheduler threads don't block.
  `hcad_available()` is checked at startup so an HCAD-seeded deploy with no data
  fails loudly.

---

## 3. ML scoring pipeline (`pipeline/ml/`)

- **Source:** internal only — lead outcomes in Postgres (won/lost stages; open
  leads idle past `ML_STALE_OPEN_DAYS` = 120 count as soft losses).
- **Mechanism:** pure-Python logistic regression (`model.py`, no heavy deps):
  `labels.py` builds labels → `features.py`/`dataset.py` build the matrix →
  `train.py` fits per-scope models (falling back to pooled/global below
  `ML_MIN_TRAINING_LABELS` = 40) → `registry.py` versions them →
  `predict.py` scores at pipeline time.
- **Schedule:** nightly retrain at `ML_RETRAIN_HOUR` (03:00 UTC), registered by
  `schedule_retraining()` in `api/main.py` — **gated on `ML_RETRAIN_ENABLED`,
  which is off by default.** Below `ML_MIN_TRAINING_LABELS` real labeled outcomes
  the job falls back to deriving approximate examples from every property row,
  every night, for a model `SCORER_MODE=rules` never surfaces. Turning it on is
  an env-var flip plus a restart; nothing accumulates while it is off, because
  `snapshot.backfill_outcomes` derives labels from *current* lead state and
  catches up in one pass. `POST /api/ml/retrain` is not gated.
- **Resource caps:** the retrain runs *inside* the API process, so it is bounded
  rather than allowed to size itself off the table. `ML_MAX_TRAINING_ROWS` (20k)
  caps the labeled rows held in memory per scope, keeping the most recently
  decided outcomes; `ML_MAX_FIT_ROWS` (4k) caps what reaches the gradient loop,
  whose cost is `epochs × rows × features` on one core; `ML_STREAM_BATCH` sizes
  the server-side fetches. The bootstrap scan streams through a named cursor and
  projects only the columns features/labels read — never `SELECT p.*`, which on a
  ~68-column table with two JSONB columns is ~7 KB of Python heap per row. A
  capped run logs what it dropped, and `train_scope` reports both `n_train` (what
  the model saw) and `n_train_available`.
- **Modes (`SCORER_MODE`):** `rules` (default — deterministic only) · `shadow`
  (store `ml_conversion_prob` alongside, keep rules grade user-facing) ·
  `learned` (surface the model probability).

---

## 4. User-driven imports (API)

### Contacts / leads CSV import — `api/routes/imports.py` + `api/import_logic.py`
- Upload → preview → commit flow, size-capped at `IMPORT_MAX_BYTES` (5 MB),
  rate-limited, per-row savepoints. Writes `properties` rows (source: user CSV).
  Import can auto-create follow-up tasks (import auto-follow-ups feature).

### Marketing / social connections — `api/routes/connections.py` + `api/connectors/`
- **Source today:** file exports from **Meta Business Suite / Ads Manager**
  (CSV) and "Download Your Information" (JSON). The `auth_type` seam leaves room
  for live Meta OAuth later (`META_APP_ID`/`META_APP_SECRET` placeholders in config).
- **Flow:** register connection → `POST /{id}/preview` parses the upload →
  `POST /{id}/import` commits. Writes `social_metrics` (reach, impressions,
  followers, engagements, ad_spend, ad_cpc/cpa/roas, campaign_name, …) and
  `social_posts` (posted_at, caption, likes, comments, shares, saves, …).
- **Downstream:** `api/marketing_insights.py` generates insights from these
  tables — deterministic rules by default (`INSIGHTS_GENERATOR=rules`, with
  benchmark thresholds in config); a Claude LLM generator is a future seam.

### Receipt OCR — `api/receipt_extract.py` (expenses module)
- **Source:** user-uploaded receipt photos (≤ `RECEIPT_MAX_BYTES`, 10 MB).
- **Mechanism:** Anthropic API (`ANTHROPIC_API_KEY`), model `RECEIPT_SCAN_MODEL`
  (default `claude-haiku-4-5`) extracts expense fields (vendor, amount, date,
  category) for the expense tracker.

---

## 5. Outbound delivery (data leaving the system)

- **Email:** Resend (`RESEND_API_KEY`/`RESEND_FROM_EMAIL`) — invoices, quote
  links, notifications (`api/notifications.py`).
- **SMS:** Twilio (`TWILIO_*`) — same notification layer.
- **Public quote/accept pages:** links built off `APP_BASE_URL`.
- **Exports:** `api/routes/export.py` (user-facing data export),
  `tools/pipeline_export.py` (ops).

---

## 6. External sources & keys summary

| Source | Used by | Key / config | Cost |
|---|---|---|---|
| RentCast (`api.rentcast.io/v1`) | Seed (default), property detail | `RENTCAST_API_KEY` | Paid |
| Google Geocoding | Geocode step, radius centers | `GOOGLE_GEOCODE_KEY` | Paid (free tier) |
| US Census ACS 5-yr (2022) | ZIP median income | `CENSUS_API_KEY` (optional) | Free |
| HCAD (local DuckDB / Postgres mirror) | Seed (free mode), backfill, permits | `PERMIT_DB_PATH` | Free |
| NOAA/IEM Local Storm Reports | Storm/hail enrichment | `IEM_LSR_URL`, `STORM_WFO` | Free, no key |
| NWS point API (`api.weather.gov`) | ZIP centroid → forecast office | `NWS_POINTS_URL`, `NWS_USER_AGENT` | Free, no key |
| Versium | Contact append, demographic append | `CONTACT_*` / `DEMO_*` (provider `versium`) | Paid (highest/record) |
| BatchData | Contact append, demographic append | `CONTACT_*` / `DEMO_*` (provider `batchdata`) | Paid |
| Anthropic | Receipt OCR (expenses) | `ANTHROPIC_API_KEY`, `RECEIPT_SCAN_MODEL` | Paid |
| Meta (file export, not API) | Social/ads metrics import | — (OAuth is a future seam) | Free |
| Resend / Twilio | Outbound email / SMS | `RESEND_*` / `TWILIO_*` | Paid |
