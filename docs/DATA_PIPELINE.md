# Axon CRM — Data Pipeline Breakdown

A step-by-step reference for the data-acquisition/enrichment pipeline: every step, the
source it pulls from, the mechanism it uses, the data points it produces, and whether it
costs money.

The pipeline is orchestrated by `run_pipeline.py::run_zip()`. Every step writes the
`properties` table through a **NULL-only upsert** (`pipeline/db.py::upsert_properties`,
`ON CONFLICT (account_id, address, zip)`), so a field is only ever paid for when it is
still empty. The `enrichment_flags` JSONB column records which source filled the row
(e.g. `{"seed": "hcad", "property": "rentcast", "hcad": "assessor"}`).

Run order is deliberate: **all free steps run before any paid step**, and free HCAD data
runs before RentCast/ATTOM specifically so the paid detail step sees a smaller queue of
NULL fields.

---

## Step-by-step

### 1. Seed — `pipeline/seed.py`
- **Source:** RentCast `/properties` (default) — or a CSV (`seed_from_csv`) — or the local
  HCAD data, either ZIP-level (`seed_from_hcad_zip`, free) or region-scoped
  (`seed_from_hcad`). Choose with `SEED_SOURCE` / `--seed-source hcad`.
- **Mechanism:** Paginated `GET /properties?zipCode=&limit=500&offset=` with
  `X-Api-Key`. Records whose `propertyType` isn't in `SEED_PROPERTY_TYPES`
  (Single Family, Condo, Townhouse, Manufactured) are dropped *before* hitting the DB so
  they never incur downstream paid enrichment. If a ZIP returns fewer than
  `SEED_EXPAND_THRESHOLD` rows, the search auto-expands to nearby/city ZIPs
  (`pipeline/geo_expand.py`) up to `SEED_EXPAND_TARGET`. A ZIP already present in the DB
  is skipped unless `--force-seed`.
- **Cost:** **Paid** (RentCast) — billed per `/properties` scan.
- **Data points:** address, city, state, zip, latitude, longitude, property_type,
  year_built, square_footage, estimated_value, last_sale_date, last_sale_price,
  owner_name (`owner.names[0]`), owner_occupied, garage_spaces, garage_type.

### 2. Census income — `pipeline/census.py`
- **Source:** US Census Bureau ACS 5-year (`api.census.gov/data/2022/acs/acs5`).
- **Mechanism:** One `GET` per **unique ZIP** (de-duped, not per-property), variable
  `B19013_001E`. `CENSUS_API_KEY` is optional and only raises rate limits.
- **Cost:** Free.
- **Data points:** zip_median_income.

### 3. Geocode — `pipeline/geocode.py`
- **Source:** Google Maps Geocoding API.
- **Mechanism:** `GET /geocode/json?address=&key=` for each row missing lat/lng, 0.05s
  throttle; geohash-6 computed via `geohash2`. Skipped entirely if `GOOGLE_GEOCODE_KEY`
  is unset.
- **Cost:** Paid (large free tier).
- **Data points:** latitude, longitude, geohash.

### 4. HCAD backfill (free) — `pipeline/hcad_enrichment.py` → `pipeline/hcad_store.py`
- **Source:** Harris County Appraisal District, read from the local `harris_county.duckdb`
  (`PERMIT_DB_PATH`); falls back to the Postgres `hcad_*` mirror tables if the DuckDB
  file is absent.
- **Mechanism:** Loads `query_properties()` + `query_extra_features()` for the ZIP, joins
  to seeded rows on a **normalized address** (`pipeline/addr.py::normalize`), and
  backfills only NULL fields. Pool/slab are written as HCAD ground truth when present.
  Runs **before** the paid detail step on purpose.
- **Cost:** **Free** (local file, zero API calls).
- **Data points:** year_built, square_footage, lot_size, estimated_value (appraised),
  last_sale_date, owner_name, owner_occupied, ownership_years (derived),
  mailing_address, hcad_neighborhood_code, hcad_neighborhood_name, has_pool,
  has_cracked_slab, garage_spaces.

### 4.5. Selection (capped runs only) — `pipeline/select.py`
- **Mechanism:** When `--top-n` or `--address`+`--radius` are set, marks the top subset
  (`enrichment_selected = TRUE`) so the paid steps only touch that subset. Runs after the
  free steps, before any paid step.
- **Cost:** Free. **Data points:** enrichment_selected.

### 5. Property detail — `pipeline/property.py`
- **Source:** RentCast, then ATTOM (`PROPERTY_FIELD_SOURCES = ["rentcast", "attom"]`).
- **Mechanism:** Per-address lookup, each source filling only fields still NULL after the
  previous one. RentCast `GET /properties?address=`; ATTOM `GET /assessment/detail`
  capped at `ATTOM_MAX_ROWS_PER_ZIP` (ATTOM is ~10× RentCast). `estimated_equity` is then
  computed in `pipeline/equity.py` from mortgage/sale data, falling back to
  `EQUITY_FALLBACK_PCT × estimated_value`.
- **Cost:** **Paid** (RentCast + ATTOM).
- **Data points:** year_built, square_footage, lot_size, estimated_value, last_sale_price,
  owner_name, owner_occupied, garage_spaces, garage_type, mortgage_balance (ATTOM) →
  estimated_equity.

### 6. Permits — `pipeline/permits.py`
- **Source:** HCAD permits (DuckDB/Postgres) — or a CSV via `--permit-csv`.
- **Mechanism:** Counts non-voided permits issued in the last 24 months per parcel.
- **Cost:** Free. **Data points:** permit_count_24mo.

### 6.5. Storm / hail — `pipeline/storm.py`
- **Source:** NOAA/NWS via the Iowa Environmental Mesonet Local Storm Reports
  (`IEM_LSR_URL`, no key).
- **Mechanism:** One GeoJSON pull per ZIP for WFO `HGX` over `STORM_LOOKBACK_MONTHS`;
  each property is matched by Haversine distance within `STORM_MATCH_RADIUS_MI`.
- **Cost:** Free.
- **Data points:** last_storm_date, last_storm_type, hail_size_in, storm_count_24mo.

### 7. Scoring — `pipeline/scorer.py` + `pipeline/scoring.py`
- **Mechanism:** Pure-Python weighted scoring using `DEFAULT_WEIGHTS` / per-vertical
  `VERTICAL_WEIGHTS` in `config.py`. With `SCORER_MODE` = `shadow`/`learned`, the
  logistic-regression model (`pipeline/ml/`) also produces `ml_conversion_prob`.
- **Cost:** Free.
- **Data points:** lead_score (0–100), score_grade (A–D), [ml_conversion_prob, ml_model_version].

### 7.5. Trim (capped runs only) — `pipeline/select.py`
- **Mechanism:** Cuts the over-sampled selection back to exactly `top_n` using the
  now-real scores, *before* the expensive skip-trace step. Cost: free.

### 8. Contact / skip-trace (optional) — `pipeline/contact.py`
- **Source:** pluggable — Versium Contact Append or BatchData (`CONTACT_PROVIDER`).
- **Mechanism:** Per-record append for rows that have an `owner_name`; gated by
  `CONTACT_MIN_GRADE` and capped by `CONTACT_MAX_ROWS_PER_ZIP`; 0.1s throttle. No-op when
  no provider is configured.
- **Cost:** **Paid (highest per record).**
- **Data points:** contact_name, contact_phone, contact_email.

### 9. Demographics / life-events (optional) — `pipeline/demographics.py`
- **Source:** Versium Demographic Append (`DEMO_PROVIDER`).
- **Mechanism:** Per-record append for rows with `owner_name`; gated by `DEMO_MIN_GRADE`,
  capped by `DEMO_MAX_ROWS_PER_ZIP`.
- **Cost:** **Paid (high).**
- **Data points:** refi_date, credit_rating, home_improvement_flag, has_children,
  gardening_flag, owner_age, life_stage, est_household_income, age_range,
  estimated_net_worth, loan_to_value, marital_status, occupation, senior_in_household,
  pets_flag, decorating_flag, credit_lines_count, mortgage_rate_type.

### Signals — `pipeline/signals.py`
- **Mechanism:** Diffs sale/permit/storm fields against the previous run's baseline,
  records `signal_events`, and fires `signal_event` workflow rules. Cost: free.

---

## Triggers
- **CLI:** `python run_pipeline.py --zip 77002 --account-id 1 --vertical roofing`
  (flags: `--zip-file`, `--skip`, `--top-n`, `--address`/`--radius`, `--limit`,
  `--seed-csv`, `--permit-csv`, `--force-seed`).
- **Scheduled:** APScheduler (`api/scheduler.py`) on cron rows in `pipeline_schedules`,
  started in `api/main.py`. Nightly ML retrain at `ML_RETRAIN_HOUR`.
- **API:** `POST /api/pipeline/run` (`api/routes/pipeline.py`).

## Existing cost controls (already in the codebase)
- NULL-only upserts — never pay to refetch a field that's already populated.
- HCAD runs before RentCast/ATTOM so paid detail sees fewer gaps.
- `ATTOM_MAX_ROWS_PER_ZIP` cap on the expensive secondary source.
- Grade gates (`CONTACT_MIN_GRADE`, `DEMO_MIN_GRADE`) + per-ZIP caps on Versium steps.
- Top-N / radius selection before paid steps; precision trim before skip-trace.
- ZIP-already-seeded short-circuit; shared retry/backoff (`pipeline/http.py`).
- Seed-type allowlist drops non-target property types before any paid enrichment.

See `COST_OPTIMIZATION.md` for the HCAD-first strategy and roadmap.
