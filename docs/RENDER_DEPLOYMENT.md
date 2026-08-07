# Deploying Axon CRM on Render (with HCAD in Postgres)

This covers how to keep the Harris County (HCAD) data **present and durable** when
the backend runs on Render, so HCAD-first seeding (`SEED_SOURCE=hcad`) works.

## Why the DuckDB can't live on Render

Render web services have an **ephemeral filesystem** — anything written at runtime
(including the multi-GB `harris_county.duckdb`) is wiped on every deploy, restart, or
scale event. So the production source of truth is the **managed Render Postgres**, into
which we mirror the HCAD `hcad_*` tables. The pipeline already reads them automatically:
`pipeline/hcad_store.py` falls back to Postgres whenever no DuckDB file is found
(`db_exists()` is False).

You build the DuckDB **locally** (one machine, one time per refresh) and push its contents
into Render Postgres with the bulk loader. The DuckDB never ships to Render.

## Prerequisite: build the DuckDB locally

The repo ships **tooling only — no HCAD data**. Download the free exports from
<https://hcad.org/pdata/> ("Real and Personal Property Data"):

| Download | Files | Gives you |
|---|---|---|
| `Real_acct_owner.zip` (**required**) | `real_acct.txt`, `owners.txt`, `deeds.txt`, **`permits.txt`** | properties, owner, mailing address, sale date, **permits** |
| `Real_building_land.zip` (**optional**) | `extra_features.txt`, `building_res.txt` | **pool / cracked slab / garage** signals, true year built |

Permit data is bundled in the required download. Pool/slab/garage need the optional zip —
without it those signals stay empty (matters for epoxy, pool, and garage-weighted verticals).

```bash
# Unzip both into one directory, then:
python tools/build_hcad_duckdb.py /path/to/unzipped_hcad_dir -o harris_county.duckdb
```

## One-time: load the whole county into Render Postgres

1. In the Render dashboard, open your database and copy its **External Database URL**.
2. From your machine (where the DuckDB lives):

```bash
python tools/load_hcad_to_postgres.py \
  --duckdb harris_county.duckdb \
  --dsn "postgresql://USER:PASS@HOST:5432/DBNAME"   # Render External URL
```

The loader `TRUNCATE`s and bulk-`COPY`s three tables — `hcad_properties` (with
neighborhood names), `hcad_permits`, and `hcad_extra_features` (pool/slab/garage) — so the
Postgres path matches the DuckDB path. For ~1.5M parcels this is far faster than the
per-ZIP `POST /api/hcad/upload` route (which only carries properties + permits).

> The target tables must exist first. They're created by migrations, which the blueprint
> runs on deploy (`preDeployCommand: python db/migrate.py`). To run the loader before the
> first deploy, run `python db/migrate.py` against the External URL once.

Alternatively, run the loader as a Render **one-off Job** in the same environment (then it
can use the internal `DATABASE_URL` and you skip the External URL).

## Deploy with the blueprint

`render.yaml` defines the managed Postgres + the API service. Key settings:

- `preDeployCommand: python db/migrate.py` — applies migrations on every deploy.
- `startCommand: uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- `healthCheckPath: /api/health`
- Env: `DATABASE_URL` (from the DB), `JWT_SECRET` (generated), `SEED_SOURCE=hcad`,
  `PERMIT_DB_PATH=""` (forces the Postgres path), paid API keys blank.
- Use **Starter** Postgres or higher — the free database expires after ~30 days.

## Verify it's working

- `GET /api/hcad/status` → `{"source": "postgres", "zips": [...]}`. `source: "none"` means
  no data is loaded.
- App logs on startup: with `SEED_SOURCE=hcad` and an empty mirror you'll see a loud
  WARNING (`SEED_SOURCE=hcad but no HCAD data is available…`). It disappears once loaded.
- Run a pipeline (CLI or `POST /api/pipeline/run`) for a ZIP that exists in the data and
  confirm rows seed and score.

## Twilio (SMS + call tracking)

`render.yaml` sets `PUBLIC_API_BASE_URL` (the API's own origin, used to build the webhook
URLs stamped onto purchased call-tracking numbers) but deliberately leaves the credentials
out — set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER` in the
service's env. Unset, SMS fails soft and `/api/calls/*` returns 503.

The global number's inbound-SMS webhook is the one thing you must configure by hand, in the
Twilio console: `https://<your-api-host>/api/public/twilio/sms`, HTTP POST, https, no
trailing slash. Call-tracking numbers configure themselves at purchase time. Full
walkthrough — including A2P 10DLC registration, which US SMS will not work without — in
[`TWILIO_SETUP.md`](TWILIO_SETUP.md).

## Refreshing the data

HCAD updates periodically (values ≈annually; deeds/permits more often). To refresh: rebuild
the DuckDB from a fresh download and re-run `tools/load_hcad_to_postgres.py` — it truncates
and reloads. No app redeploy needed.

## Re-enabling paid APIs later

To test RentCast as a gap-filler, set `RENTCAST_API_KEY` in the service's env. It rejoins
the property-detail step and fills only the fields HCAD can't (sale price, garage type,
market AVM). See `COST_OPTIMIZATION.md` for the field→source matrix.
