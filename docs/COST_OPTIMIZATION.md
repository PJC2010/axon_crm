# Axon CRM — Cost Optimization & HCAD-First Aggregation

Goal: minimize paid-API spend by treating **Harris County Appraisal District (HCAD)** as
the canonical base layer for every field it can supply, and routing only the genuinely
unavailable fields to paid APIs.

*Last reviewed: 2026-08-07.*

Today's live cost centers are **RentCast** (seeding + property detail) and the
**skip-trace / demographics** steps (provider-pluggable — `batchdata` or
`versium` via `CONTACT_PROVIDER` / `DEMO_PROVIDER`). Google Geocoding is no
longer a significant cost: the geocode step is now **Census-batch-first** with a
hard-capped Google fallback (Phase 3, below — shipped). (ATTOM was removed from
the project on 2026-07-01.) Scope is Harris County now, with paid APIs kept as
the path for future out-of-county ZIPs.

See `DATA_PIPELINE.md` for the full step-by-step. This document covers (a) which fields
HCAD can vs. cannot supply, and (b) a phased roadmap to drive paid spend down.

---

## 1. Field → source matrix

### Free from HCAD (the aggregation base)
address / site location, year_built, square_footage, lot_size, **appraised** value,
last_sale_**date**, owner_name, owner_occupied (derived from mailing == site),
ownership_years, mailing_address, neighborhood code + name, has_pool, has_cracked_slab,
garage_spaces, permit_count_24mo.

### Paid-only — HCAD genuinely cannot supply these
| Field(s) | Why HCAD can't | Source |
|---|---|---|
| contact_phone, contact_email | Assessor records never contain contact info | BatchData / Versium skip-trace |
| last_sale_**price**, true market **AVM** | **Texas is a non-disclosure state** — sale prices aren't public. HCAD gives *appraised* (tax) value, which trends below market | RentCast |
| garage_type | HCAD records garage *units*, not type | RentCast |
| mortgage_balance | Not in assessor data; equity now uses the amortization fallback in `pipeline/equity.py` | (none — ATTOM removed) |
| Demographics / life-events (refi_date, credit_rating, income band, net worth, LTV, has_children, life_stage, …) | Not assessor data | BatchData / Versium demographic |
| latitude / longitude | Absent from the HCAD text export today | **Free** — US Census batch geocoder (Phase 3, shipped) |

**Bottom line:** inside Harris County, HCAD can fill the large majority of property
fields. Remaining paid spend should be concentrated on **skip-trace contact info** and,
optionally, **market value/sale price** when appraised value isn't good enough.

---

## 2. Roadmap (highest ROI first)

### Phase 1 — HCAD-first seeding (eliminates RentCast seed cost in Harris County) ✅ DONE
- `pipeline/seed.py::seed_from_hcad_zip()` seeds **every parcel in a ZIP** straight from
  the local HCAD DuckDB (Postgres `hcad_*` mirror fallback) with **zero paid calls**,
  backed by `hcad_store.query_parcels_for_zip()`.
- Selected via `SEED_SOURCE=hcad` (`config.py`) or `--seed-source hcad`
  (`run_pipeline.py`); RentCast stays the default so other flows are unchanged.
- `pipeline/hcad_enrichment.py` now also backfills `estimated_equity` from the appraised
  value (via `estimate_equity()`), so the equity signal survives an HCAD-only run.
- Effect: seeding *and* most of step 5's fields come from the free data; with the RentCast
  key blank the paid detail step is a no-op. Re-enable RentCast for testing by setting
  `RENTCAST_API_KEY` — it rejoins step 5 as a pure gap-filler.
- Run it: `python run_pipeline.py --zip 77002 --account-id 1 --seed-source hcad`.

### Phase 1b — Shared parcel cache (pay for a ZIP once, not once per tenant) ✅ DONE
- Migration `0065_shared_parcels.sql` + `pipeline/parcels.py` add a **shared `parcels`
  table** holding the tenant-*independent* half of a property (assessor data,
  coordinates, storm history, neighborhood). `properties.parcel_id` links a tenant row
  back to its parcel.
- Seeding a ZIP for a new org becomes an `INSERT … SELECT` inside the database instead of
  a per-org re-run of the enrichment pipeline. On ZIP 77449 (41,334 parcels) the old seed
  step alone measured **8m58s**.
- The pipeline's `promote` step (step 6.75) pushes each run's findings back into the cache
  so the next account inherits them free.
- **Cost boundary:** `parcels.SHARED_COLS` deliberately excludes skip-traced contacts and
  the demographic append — those are per-account *purchases* and provider terms forbid
  redistribution. Sharing them would be a licensing problem, not a saving.

### Phase 2 — Skip-trace / demographics spend discipline (biggest live per-record cost)
- Turn on grade gating now: set `CONTACT_MIN_GRADE` / `DEMO_MIN_GRADE` to `B` (or `A`) so
  only worthwhile leads are ever traced.
- Add a **persistent skip-trace/demographic cache** keyed on normalized address (and/or
  owner) so the same parcel is never paid for twice across re-runs. Note this cannot ride
  on the shared `parcels` table (see the boundary above) — it needs a per-account store.
  Confirm and, if needed, strengthen the "row already has contact_phone → skip" guard in
  `pipeline/contact.py` and `pipeline/demographics.py`.
- Enrich **new or stale-only** leads on scheduled runs — contact and demographic data
  rarely change, so add a TTL instead of re-appending every run.
- Prefer **bulk/batch** append endpoints over the per-record loop. BatchData's Reverse
  Skip Trace already does this for the call-tracking append (100 numbers per POST, see
  `api/call_append_sweep.py`) — the batch pattern is proven in the codebase and worth
  extending to the main contact/demographics steps.

### Phase 3 — Free substitutions for the remaining paid edges
- **Geocoding — ✅ DONE.** The geocode step now sends the ZIP's whole backlog to the
  **free US Census batch geocoder** (10,000 addresses per POST,
  `pipeline/geocode_batch.py`), with Google kept only as a fallback for unmatched
  addresses and hard-capped at `GEOCODE_FALLBACK_MAX` (2000; set `0` for free-only
  geocoding). Measured impact on ZIP 77449 (41,334 parcels): **~2h52m and ~$200 of Google
  Geocoding → 5 free requests.** HCAD GIS parcel centroids remain an unexplored
  alternative but are no longer needed for cost reasons.
- **Market value:** keep RentCast as an **explicit, opt-in** market-value
  enrichment used only when the HCAD appraised value isn't accurate enough for the equity
  signal — not a default step in Harris County runs.

### Phase 4 — Treat HCAD as a refreshed master dataset
- Rebuild `harris_county.duckdb` on the county's update cadence (≈annual for values, more
  frequent for deeds/permits) via `tools/build_hcad_duckdb.py`; everything downstream
  reads the refreshed base.
- Future free add-ons worth aggregating in: HCAD GIS geometry (centroids → free
  geocoding), county tax-office delinquency (motivation signal).

---

## 3. Quick wins available now (no schema change)
1. Enable `CONTACT_MIN_GRADE` / `DEMO_MIN_GRADE` gating immediately — this is the
   single largest remaining lever and is pure configuration.
2. Set `GEOCODE_FALLBACK_MAX=0` to make geocoding strictly free (unmatched rows keep
   NULL coordinates, which only affects the geo/map layer for those rows).
3. Leave `PHONE_APPEND_SWEEP_MAX=0` unless the call-tracking backfill is worth the
   spend — it is off by default precisely so deploying it changes nobody's bill.

*(Items 1–3 of the previous revision — HCAD-first seeding and free geocoding — have
shipped; see Phases 1, 1b and 3.)*

## 4. Out-of-county note
Outside Harris County there is no HCAD equivalent loaded, so paid APIs remain the seed and
detail source there. Keep the paid path intact and feature-flag HCAD-first so it only
engages for Harris County ZIPs/regions.
