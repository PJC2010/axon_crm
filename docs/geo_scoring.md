# Geospatial Scoring Layer — Phases 1–2

*Scope: the Juncto geo layer adapted to Axon's real schema.*
*Phase 1 — proximity + density + territory scoring, RentCast coordinate
persistence, an async geocoding queue, per-vertical geo config, and the
final-score blend wired into the leads list.*
*Phase 2 (data) — customer clustering (DBSCAN), cluster hulls + membership, H3
assignment, and the heatmap + clusters endpoints.*
*Phase 2 (prospecting) — cluster-seeded RentCast radius pull behind a swappable
provider, with client-side refinement, dedupe, ingest, immediate scoring, and
H3-cell cost control.*
*Phase 3 — neighbor / visible-work component wired into scoring, the blast-radius
endpoint, and the map UI (heatmap overlay, cluster hulls + "prospect this area",
"Route fit" chip).*
*Phase 4 — event layers: `geo_events` (manual polygon upload), an additive event
bonus in scoring named in the breakdown, and an event overlay on the map.*

Companion: `juncto-geospatial-layer-plan.md` (the full four-phase plan).

---

## What shipped in Phase 1

| Area | File(s) |
|---|---|
| Migration (columns, config, scores, service areas, geocode queue) | `db/migrations/0049_geo_scoring.sql` |
| Pure scoring math (decay, density cap, territory gate, blend, geometry) | `pipeline/geo_scoring.py` |
| DB orchestration (customers, service area, rescore) | `pipeline/geo_score_store.py` |
| Geocoding provider interface + async queue | `pipeline/geocode_provider.py` |
| RentCast coordinate provenance on ingest | `pipeline/seed.py`, `pipeline/db.py` |
| Re-score-on-new-customer trigger | `api/lead_logic.py`, `api/scheduler.py` |
| Nightly geo rescore + geocode drain | `api/scheduler.py`, `api/main.py` |
| API surface | `api/routes/geo.py` |
| Final-score blend in the leads list | `api/routes/leads.py`, `api/models.py` |
| Config knobs | `config.py` (geo section) |
| Tests | `tests/test_geo_scoring.py`, `tests/test_geo_rescore.py` |

## What shipped in Phase 2 (clustering + heatmap data)

| Area | File(s) |
|---|---|
| Migration (`customer_clusters`, h3/cluster indexes) | `db/migrations/0050_geo_clusters.sql` |
| Pure DBSCAN + cluster hulls + membership | `pipeline/geo_clustering.py` |
| Optional H3 wrapper (graceful fallback) | `pipeline/geo_h3.py` |
| DB orchestration (recompute clusters, H3 backfill) | `pipeline/geo_cluster_store.py` |
| `GET /geo/clusters`, `GET /geo/heatmap`, `POST /geo/cluster/recompute` | `api/routes/geo.py` |
| Nightly clustering + H3 folded into the geo tick | `api/scheduler.py` |
| `h3` optional dependency | `requirements.txt` |
| Tests | `tests/test_geo_clustering.py` |

**Clustering:** pure-Python DBSCAN (`pipeline/geo_clustering.dbscan`) over
haversine distance — the `ST_ClusterDBSCAN` stand-in — with `eps` 800 m and
`min_points` 3 (the point itself counts, matching PostGIS). Each account's
clusters are rewritten as a set into `customer_clusters` with a GeoJSON hull, and
every geo-scored lead is stamped with `lead_geo_scores.cluster_id` when it falls
inside a hull. A lead inside a dense cluster already scores higher through the
proximity + density components — cluster membership is for grouping and the
"prospect this area" flow, not a separate score term.

**Heatmap:** `properties.h3_r8` (resolution 8, ~0.74 km² hexes) is populated by
the nightly job via the optional `h3` package. `GET /geo/heatmap?metric=density|
avg_score` aggregates by hex — `density` = customers per hex, `avg_score` =
average blended score — returning each cell's H3 id (for deck.gl's
`H3HexagonLayer`) plus its boundary polygon. When `h3` isn't installed the
endpoint reports `available: false` and the frontend falls back to the existing
geohash-6 choropleth at `/api/map/cells`.

## What shipped in Phase 2 (cluster-seeded prospecting, Section 5)

| Area | File(s) |
|---|---|
| Migration (`prospect_pulls`, `properties.subdivision`) | `db/migrations/0051_prospecting.sql` |
| Swappable provider (`PropertyDataProvider`, RentCast radius search) | `pipeline/property_provider.py` |
| Flow: seed → pull → refine → dedupe → ingest → score | `pipeline/prospecting.py` |
| `POST /geo/prospect` | `api/routes/geo.py` |
| `subdivision` writable column | `pipeline/db.py` |
| Config knobs | `config.py` (prospecting section) |
| Tests | `tests/test_geo_prospecting.py` |

**Flow:** `pipeline/prospecting.prospect` resolves a seed — a cluster centroid, a
customer, or a user-dropped `{lat,lng}` pin — then pulls a radius of records from
the property-data provider, refines client-side on schema fields the vendor can't
filter server-side (lotSize/yearBuilt ranges, `ownerOccupied` for absentee
targeting, `features.pool`, `hoa.fee` presence), dedupes against existing
properties (normalized address first, then geometry within `PROSPECT_DEDUPE_M`,
default 25 m — also collapsing duplicates within the pull), ingests via
`upsert_properties` with `geocode_source='rentcast'` and the `subdivision`
cluster key, and immediately geo-scores exactly the new leads. By construction
these sit near customer density, so the geo components run high and the property
score does the differentiating.

**Provider swappability:** RentCast lives behind `PropertyDataProvider`
(`search_radius`, `get_by_address`), mirroring `GeocodeProvider`. RentCast's
`/properties` handles the circular geo search (lat/lng + radius in miles) and the
server-side `propertyType` filter; everything else is client-side refinement.
BatchData/ATTOM/BigDBM slot in by adding a provider class.

**Cost control:** every pull is logged in `prospect_pulls`, keyed by the seed's
H3 cell; a cell pulled within `PROSPECT_SKIP_DAYS` (14) is skipped *before* any
API call. `api_requests` is metered per pull (requests, not records, are the
binding constraint — one request returns up to 500 records). `POST /geo/prospect`
returns a funnel summary: returned → refined → deduped → ingested → scored.

**Equity proxy (RentCast):** RentCast carries no mortgage/lien data, so ingest
derives estimated equity from sale price/date via the existing
`pipeline/equity.estimate_equity` — serviceable for home services, and the
property-score equity factor already treats it as a proxy.

## What shipped in Phase 3 (neighbor effect + map UI)

| Area | File(s) |
|---|---|
| Neighbor / visible-work component wired into scoring | `pipeline/geo_score_store.py` |
| Blast-radius helper + `POST /geo/neighbors` | `pipeline/geo_score_store.py`, `api/routes/geo.py` |
| Map overlays: H3 heatmap, cluster hulls, "prospect this area" | `frontend/components/PropertyMap.tsx` |
| "Route fit" chip on the lead detail | `frontend/components/ContactDrawer.tsx` |
| Geo types + API client (`getGeoHeatmap`/`getGeoClusters`/`prospectArea`/`getBlastRadius`/service-area) | `frontend/lib/types.ts`, `frontend/lib/api.ts` |
| Tests | `tests/test_geo_neighbor.py` |

**Neighbor effect:** `_spatial_facts` now derives `days_since_completed_job` from
won/converted customers within `GEO_NEIGHBOR_RADIUS_M` (150 m), dated by
`stage_moved_at` (when the lead reached its terminal state — the "completed job").
The freshest such job feeds `neighbor_component` (100 within 60 days, linear decay
to 0 at 90). Winning a lead already triggers a nearby re-score (Phase 1's
`apply_status_change` hook) and the geohash door-knock task, so the neighbor bump
propagates automatically; `POST /geo/neighbors {job_id, radius_m}` returns the
radius-precise ranked blast-radius list on demand (the complement to the
geohash-bucketed `api/neighbors.find_neighbors`).

**Map UI (Section 8):** the existing MapLibre `PropertyMap` gains a **Heatmap**
toggle (H3 hexes from `/geo/heatmap`, shaded by density or avg score — rendered
from the cell boundary polygons the endpoint returns, so no deck.gl dependency),
a **Clusters** toggle (DBSCAN hulls from `/geo/clusters`) whose hulls are
clickable to fire the Section 5 **"prospect this area"** flow with the map's
current vertical filter, and a **"Route fit"** chip on the lead drawer ("0.3 mi
from 2 active customers") read straight off the lead's `nearest_customer_m` /
`customers_within_1600m`. Verified with `tsc --noEmit`, `eslint`, and a full
`next build`.

**Service-area polygon draw/edit shipped with the maps remodel** — it used
**Terra Draw** (MIT, zero runtime dependencies, headless) with
`terra-draw-maplibre-gl-adapter`, smoke-tested against MapLibre 6.4.1 first
because the adapter's peer range predates v6 and its CI pins 5.24.0. Correcting
the note this replaces: `@mapbox/mapbox-gl-draw` was never a *licensing*
blocker — it is ISC; only the `mapbox-gl` **renderer** is proprietary. What ruled
it out is that its types package depends on that proprietary renderer, dragging
it into the tree.

The same draw session also feeds `POST /geo/events` (event polygons) and
`/geo/prospect`'s long-unused `lat`/`lng` seed, and a select mode drives bulk
archive over the pins inside a drawn shape.

## What shipped in Phase 4 (event layers)

| Area | File(s) |
|---|---|
| Migration (`geo_events`) | `db/migrations/0052_geo_events.sql` |
| Event bonus in scoring + `best_event_for_point` | `pipeline/geo_scoring.py` |
| Active-event loading + per-lead containment/bonus | `pipeline/geo_score_store.py` |
| `GET`/`POST`/`DELETE /geo/events` (+ rescore on change) | `api/routes/geo.py` |
| Event overlay toggle on the map; event chip on the lead drawer | `frontend/components/PropertyMap.tsx`, `frontend/components/ContactDrawer.tsx` |
| Config (`GEO_EVENT_BONUS`, `GEO_EVENT_DEFAULT_BONUS`) | `config.py` |
| Tests | `tests/test_geo_events.py` |

Some demand is created by events that hit whole polygons at once — hail swaths
(roofing), new-construction phases (lawn/pest/pools), HOA sweeps, heat waves
(HVAC). A lead inside an **active** event polygon (now within `[starts_at,
ends_at]`, NULL bounds open) gets an additive **event bonus**:

```
geo_score = min(100, weighted_base + event_bonus) * territory_gate
```

The bonus is per `event_type` (`config.GEO_EVENT_BONUS`, e.g. hail_swath 40), with
an optional per-event override (`geo_events.bonus`). The winning event is named in
the component breakdown (`components.event = {type, id, name}`), so the lift is
explainable — the lead drawer shows an event chip ("May hail +40"). The gate still
applies, so an out-of-territory lead in a swath stays suppressed.

MVP ingestion is manual: an admin uploads a polygon via `POST /geo/events`, which
re-scores the account so the bonus lands immediately; `GET /geo/events` returns a
FeatureCollection (with an `active` flag) for the map overlay. NOAA / storm-data
automation waits until a roofing tenant exists. As with the rest of the layer,
`geo_events.polygon` is GeoJSON in JSONB and containment runs in Python — the
PostGIS `geometry(Polygon,4326)` + `ST_Contains` upgrade is a drop-in.

---

## Answers to the plan's Section 11 open questions (from the codebase)

**1. Does a `customers` table exist, distinct from leads?**
No. Leads *are* the `properties` table; there is no separate customers entity. A
"customer" for the geo layer is a property in a won/converted status
(`config.CUSTOMER_STATUSES = ("won", "converted")`, matching `WON_STATUSES` in
`pipeline/ml/labels.py`). Service address is `properties.address`; there is no
separate billing address. Proximity and density are measured against these
won/converted properties' coordinates.

**2. Multi-market tenants: one service area per tenant or per branch?**
One per account. The schema has no branch/location entity — `account_id` (INT) is
the only tenant key. `service_areas` is keyed by `account_id`; the store layer
keeps at most one area per account (a `user_drawn` area wins over the `derived`
hull). Per-branch areas are a trivial future extension (add a nullable
`branch_id`).

**3. Existing background-job mechanism?**
APScheduler, in-process, in `api/scheduler.py` (started in `api/main.py`'s
lifespan). Daily ticks take a `pg_try_advisory_lock` so multi-worker deploys
don't double-run; one-off work is fired with `scheduler.add_job(...)`. The geo
layer reuses this exactly — a nightly `run_geo_rescore_tick` (advisory-locked) and
a fire-and-forget `enqueue_customer_geo_rescore` for the new-customer trigger. No
Celery introduced.

**4. Is `vertical` a tenant-level attribute?**
No — `vertical` is per-property (`properties.vertical`). The tenant-level industry
attribute is `accounts.business_type`. So `vertical_geo_config` is keyed by the
per-lead vertical, with an optional `account_id` override; scoring resolves a
lead's config as **tenant override → platform default → `GEO_DEFAULT_CONFIG`**
(mirroring how `scorer.score_zip` falls back to `DEFAULT_WEIGHTS`).

**5. RentCast tier / per-tenant request budget? — FLAGGED (product decision)**
Not answerable from the codebase. The seed path confirms one radius request
returns up to 500 records (`pipeline/seed.py BATCH_SIZE = 500`), so requests, not
records, are the binding constraint. A monthly per-tenant pull allowance needs a
call from product/finance once prospecting (Phase 2) is built; the
`prospect_pulls` cost-control table lands with it.

---

## Key adaptation: no PostGIS (intentional)

The plan calls for PostGIS geometry columns + GIST indexes. Phase 1 deliberately
does **not** require PostGIS:

- `properties.latitude/longitude` already exist and are populated by the seed +
  geocode steps.
- The plan's own MVP distance rule is **haversine × a 1.3 road-circuity factor**
  (Section 4) — no routing engine, and no PostGIS needed. This is computed in
  Python (`pipeline/geo_scoring.haversine_km` / `road_distance_km`).
- Adding `CREATE EXTENSION postgis` to a migration would break `python
  db/migrate.py` on any Postgres without the extension available (CI, and some
  managed tiers), for zero Phase-1 benefit.

Polygons (service areas, and later clusters/events) are stored as **GeoJSON in
JSONB**. Membership and hull math live in `pipeline/geo_scoring.py`.

### PostGIS upgrade path (Phase 2/3, drop-in)

When clustering (`ST_ClusterDBSCAN`), H3 heatmaps, and larger customer books make
Python scans and JSONB polygons the bottleneck:

1. `CREATE EXTENSION postgis;` in a new migration.
2. Add `geom geometry(Point,4326)` to `properties` (backfill from lat/lng:
   `ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)`), plus a GIST index.
3. Convert `service_areas.polygon` / cluster hulls to `geometry(Polygon,4326)`.
4. Swap the O(leads × customers) nearest-customer scan in
   `geo_score_store._spatial_facts` for a `<->` KNN / `ST_DWithin` query.
5. Optionally replace haversine × 1.3 with OSRM `/table` for real drive times.

Nothing above changes the scoring math or the stored component breakdown.

---

## Scoring model (as implemented)

```
proximity = 100 * exp(-road_km / GEO_PROXIMITY_DECAY_KM)      # 100 at doorstep
density   = min(customers_within_1600m, 8) / 8 * 100          # capped
neighbor  = 0 in Phase 1 (no jobs table; wired in Phase 3)
gate      = 1.0 inside service area, else 0.1                 # multiplicative

geo_score = (route*proximity + route*density + neighbor_w*neighbor)
            / (2*route + neighbor_w) * gate                   # normalized 0–100

final_score = (1 - geo_blend) * property_score + geo_blend * geo_score
```

Every scored lead stores its component breakdown as JSONB in
`lead_geo_scores.components` so the UI can explain *why*. Weights and blends are
per-vertical, seeded from the plan's Section 3 matrix as platform defaults and
tenant-overridable via `vertical_geo_config`.

**Distance semantics:** density counts customers within 1600 m straight-line;
proximity decays on the road distance (haversine × 1.3) to the nearest customer.

**Territory (derived area):** with no user-drawn polygon, the service area is the
convex hull of the account's customers; membership allows a 2 km buffer so leads
just past the edge aren't wrongly gated out. With fewer than 3 customers there is
no polygon and the gate is neutral (inside), so early-stage accounts aren't
penalized.

---

## Data flow

- **RentCast leads** arrive pre-geocoded; `pipeline/seed.py` stamps
  `geocode_source = 'rentcast'` and they never enter the geocode queue.
- **Tenant-entered addresses** without coordinates are enqueued in
  `geocode_queue` (`POST /api/geo/geocode/backfill`) and drained by the background
  job through `GeocodeProvider` (US Census by default; Google slots in). Geocoding
  never happens in a request path.
- **A lead becomes a customer** (won/converted): `apply_status_change` enqueues
  `enqueue_customer_geo_rescore`, which refreshes the derived service area and
  re-scores every lead within `GEO_RESCORE_RADIUS_KM` (8 km) of the new customer.
- **Nightly:** `run_geo_rescore_tick` drains the geocode queue, refreshes derived
  service areas, and re-scores all accounts.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/geo/config` | Effective per-vertical geo config for the account |
| POST | `/api/geo/score/batch` | Recompute geo + final scores (`{lead_ids: [...]}`; empty → full-account background rescore) |
| POST | `/api/geo/geocode/backfill` | Queue geocoding for leads missing coordinates |
| GET | `/api/geo/service-area` | The account's service-area polygon (GeoJSON) |
| PUT | `/api/geo/service-area` | Save a user-drawn service-area polygon |
| GET | `/api/geo/clusters` | Customer clusters as a GeoJSON FeatureCollection |
| GET | `/api/geo/heatmap` | H3-hex aggregates (`metric=density\|avg_score`) |
| POST | `/api/geo/cluster/recompute` | Re-run DBSCAN + H3 backfill for the account |
| POST | `/api/geo/prospect` | Cluster-seeded RentCast pull → dedupe → ingest → score |
| POST | `/api/geo/neighbors` | Blast radius around a completed job — ranked targets |
| GET | `/api/geo/events` | Event polygons as a GeoJSON FeatureCollection |
| POST | `/api/geo/events` | Upload an event polygon (e.g. a hail swath) |
| DELETE | `/api/geo/events/{id}` | Remove an event |

The leads list (`GET /api/leads`) LEFT JOINs `lead_geo_scores`, exposes
`geo_score` / `final_score` / `geo_components` / `nearest_customer_m` /
`customers_within_1600m`, and accepts `sort=final_score`.

---

## Config knobs (`config.py`)

`GEO_ROAD_CIRCUITY`, `GEO_PROXIMITY_DECAY_KM`, `GEO_DENSITY_RADIUS_M`,
`GEO_DENSITY_CAP`, `GEO_NEIGHBOR_FRESH_DAYS`, `GEO_NEIGHBOR_DECAY_DAYS`,
`GEO_TERRITORY_GATE_OUT`, `GEO_RESCORE_RADIUS_KM`, `GEO_SERVICE_AREA_BUFFER_KM`,
`GEO_BLEND_RECURRING`, `GEO_BLEND_PROJECT`, `GEO_DEFAULT_CONFIG`,
`CUSTOMER_STATUSES`, `GEOCODE_PROVIDER`, `CENSUS_GEOCODER_URL`,
`GEO_CLUSTER_EPS_M`, `GEO_CLUSTER_MIN_POINTS`, `GEO_H3_RESOLUTION`,
`PROPERTY_PROVIDER`, `PROSPECT_DEFAULT_RADIUS_M`, `PROSPECT_MAX_RECORDS`,
`PROSPECT_SKIP_DAYS`, `PROSPECT_MAX_PULLS_PER_CYCLE`, `PROSPECT_DEDUPE_M`,
`GEO_EVENT_BONUS`, `GEO_EVENT_DEFAULT_BONUS`.
