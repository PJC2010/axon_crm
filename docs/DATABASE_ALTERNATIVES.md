# Postgres Hosting Alternatives — Compatibility & Performance Analysis

Evaluation of managed-database options other than Render, judged against what
**this codebase actually requires**. Written after auditing `db/migrations/`,
`api/`, `pipeline/`, and `tools/`.

Short version: **your storage need is small (tens of GB) and is not your
constraint. Your constraints are (a) session-mode connections for the
scheduler's advisory locks, (b) real PostgreSQL extensions and PL/pgSQL, and
(c) connection-establishment latency, because the API opens a brand-new
connection on every single request.** Any provider you pick must satisfy (a)
and (b), and (c) is a code fix that will beat any provider change.

---

## 1. The compatibility contract

These are hard requirements extracted from the code. A candidate that misses
any of them requires a rewrite, not a connection-string change.

### 1.1 Real PostgreSQL engine — not "Postgres-compatible"

| Requirement | Where | Why it disqualifies re-implementations |
|---|---|---|
| `pg_trgm` extension + 5 GIN trigram indexes (`gin_trgm_ops`) | `0038_account_numbers.sql:78-90` | Powers `/api/leads/search` fuzzy lookup by name/address/phone/email. Distributed PG clones generally lack trigram GIN. |
| PL/pgSQL functions + 11 triggers | `0005`, `0006`, `0023`, `0038`, `0054`, `0043`, `0049`… | `assign_account_number()`, `next_invoice_number()`, `next_quote_number()`, `set_updated_at()`. |
| `GENERATED ALWAYS AS (…) STORED` calling a **custom `IMMUTABLE` SQL function** | `0065_shared_parcels.sql:33-56` — `axon_normalize_address()` backing `parcels.address_norm` | The most demanding single feature in the schema. Most PG-compatible engines allow generated columns only over built-in expressions. |
| `gen_random_uuid()` | `0024`, `0036`, `0047` | Public quote/invoice/pay tokens. |
| `percentile_cont(x) WITHIN GROUP (ORDER BY …)` (ordered-set aggregate) | `api/routes/leads.py:445`, `api/routes/map.py:154-157`, `pipeline/neighborhood.py:127-138` | Neighborhood medians and map bounds. |
| `ON CONFLICT` upserts (41 sites), `RETURNING` (102 sites) | throughout `api/`, `pipeline/` | Core write path. |
| `JSONB` (50), `TEXT[]` arrays (4), `SERIAL`/`BIGSERIAL` (54), window functions | throughout | |
| `COPY … FROM STDIN` via `psycopg2.copy_expert` | `tools/load_hcad_to_postgres.py:136` | Bulk-loads ~1.5M HCAD parcels. |
| libpq wire protocol v3 via `psycopg2` | `requirements.txt`, everywhere | Binary driver, not an HTTP shim. |

### 1.2 Session-mode connections (the #1 migration hazard)

`api/scheduler.py` guards **8 cron jobs** with session-scoped advisory locks:

```python
cur.execute("SELECT pg_try_advisory_lock(%s)", (WORKFLOW_TICK_LOCK_KEY,))
...                       # do the work
cur.execute("SELECT pg_advisory_unlock(%s)", (WORKFLOW_TICK_LOCK_KEY,))
```

`pg_try_advisory_lock` / `pg_advisory_unlock` bind to a **backend session**, not
a transaction. Behind a **transaction-mode pooler** the acquire and the release
can land on two different backends. The result is silent and permanent: the lock
leaks onto a pooled backend, `pg_try_advisory_lock` returns false forever, and
**every one of these jobs stops running with only an `INFO` log line**:

- workflow daily tick, account rescore, recurring invoices, phone-append sweep,
  trial expiry, unverified-signup digest, user digest, geo rescore.

Concretely, this means:

| Provider | Endpoint to use | Endpoint to avoid |
|---|---|---|
| Neon | direct endpoint (`ep-xxx.region.aws.neon.tech`) | `-pooler` endpoint (PgBouncer transaction mode) |
| Supabase | port **5432** (session / direct) | port **6543** (Supavisor transaction mode) |
| Any PgBouncer setup | `pool_mode = session` | `pool_mode = transaction` |

If you ever want the transaction pooler for the API's benefit, the scheduler
must keep a **separate direct DSN**. That is a real and reasonable architecture
— it just has to be deliberate.

### 1.3 No connection pooling in the app

`api/deps.py:12-17`:

```python
def get_db():
    conn = psycopg2.connect(DATABASE_URL)   # new TCP + TLS + auth, every request
    try:
        yield conn
    finally:
        conn.close()
```

Every API request pays a full TCP handshake + TLS negotiation + Postgres
authentication before it runs its first query. `api/scheduler.py` opens another
~11 connections of its own, and `api/routes/geo.py` opens 4 more ad hoc.

Two consequences for provider choice:

- **Connection latency is on the critical path of every request.** Providers
  with scale-to-zero cold starts (Neon free/scale-to-zero, Aurora Serverless v2
  scaling from 0) will show that latency as user-visible p99 spikes.
- **Connection *count* limits matter more than usual.** Small managed instances
  cap at 20–100 connections; with no pool you burn one per in-flight request.

**This is the single highest-leverage fix available, and it is free.** See §6.

### 1.4 Long transactions and bulk writes

The pipeline runs multi-minute transactions: the ZIP 77449 seed touches 41,334
parcels in one `INSERT … SELECT` (`pipeline/parcels.py:170-220`), and
`execute_values` batches run across `pipeline/db.py`, `signals.py`,
`neighborhood.py`, `geocode.py`. Avoid platforms that impose short statement or
transaction timeouts, or that suspend compute mid-transaction.

### 1.5 PostGIS — not required today, wanted later

The geo layer is **deliberately PostGIS-free** (`docs/geo_scoring.md:218-240`)
because `CREATE EXTENSION postgis` would break `db/migrate.py` anywhere the
extension is unavailable. But that doc calls the PostGIS upgrade a "drop-in" for
Phase 2/3. **Prefer a provider that offers PostGIS**, so that path stays open.

---

## 2. Sizing reality check: storage is not your problem

Estimated from row counts and column widths in the schema:

| Data | Rows | Est. size (incl. indexes) |
|---|---|---|
| `hcad_properties` (shared) | ~1.5M | ~400 MB |
| `hcad_permits` (shared) | ~2–3M | ~400 MB |
| `hcad_extra_features` (shared) | ~1.5M | ~200 MB |
| `parcels` (shared cache, ~50 cols) | ~1.5M | ~800 MB |
| `properties` (per tenant) | ~41k per ZIP per tenant | ~25–50 MB per ZIP per tenant |

- **Harris County fully loaded: ~2–3 GB shared.**
- **100 tenants × 5 ZIPs each: ~15–25 GB** of tenant rows.
- The 5 GIN trigram indexes on `properties` are the fastest-growing item —
  trigram GIN commonly runs 1–3× the size of the indexed text column.

**Total realistic ceiling in the current design: ~30–50 GB.** Every option below
handles that without strain. Do not pay for a storage tier you will not use.

Storage becomes a genuine decision factor only if you **replicate the `hcad_*`
pattern beyond Harris County**. All 254 Texas counties at the same fidelity is a
~250 GB–1 TB proposition, and national coverage is multi-TB. If that is on the
roadmap, weight the columnar/compression options in §3 accordingly.

---

## 3. Recommended alternatives

All of these are real PostgreSQL and satisfy §1.1. Ranked by fit to *this*
codebase. Verify current pricing directly — it moves.

### Tier 1 — drop-in, change `DATABASE_URL` and go

**1. Crunchy Bridge — best pure fit**
Postgres specialists; full extension catalog including `pg_trgm` and PostGIS,
NVMe storage, native session connections, no pooler surprises. No serverless
cold-start behavior to fight, which suits your connection-per-request pattern.
Strong choice if you want "Render, but the database is actually good."
*Trade-off:* no free tier; you pay from day one.

**2. DigitalOcean Managed Postgres — best simple upgrade**
The closest like-for-like to Render with better price/performance. Real PG, full
extensions, PostGIS available, session connections by default, optional
connection pools you control (**set them to session mode**). Predictable pricing,
easy mental model.
*Trade-off:* nothing exotic — no autoscaling, no branching.

**3. Supabase — best if you want headroom plus a free tier**
Real PG with a generous extension set (`pg_trgm`, PostGIS, `pgvector`).
Provisioned disk with configurable IOPS, which directly addresses your
"speed" question for the big `hcad_*`/`parcels` scans. Scales to very large disk
sizes.
*Trade-offs:* **use port 5432, never 6543** (§1.2). You also inherit
PostgREST/Auth/Storage services you do not need — harmless, but noise.

**4. Neon — best if the workload is bursty and storage-heavy**
Real PG with separated storage/compute, autoscaling, and database branching
(genuinely nice for testing your 65 migrations against a copy of prod).
Cheap per-GB storage makes multi-county expansion affordable.
*Trade-offs:* two real ones. **Use the direct endpoint, not `-pooler`** (§1.2),
and **disable scale-to-zero** — a cold start on a connection-per-request app is
a latency cliff on the first request after idle. Both are settings, not
blockers.

### Tier 2 — more power, more operational work

**5. AWS RDS for PostgreSQL — the capacity/IOPS answer**
Up to 64 TiB on gp3, or io2 Block Express with provisioned IOPS into the
hundreds of thousands. Full extension support. This is the right answer if the
multi-county expansion happens.
*Trade-off:* VPC networking. Reaching it from Render/Vercel means a public
endpoint with tight security groups, or a proper peering setup.

**6. AWS Aurora PostgreSQL**
Up to 128 TiB, fast failover, low-lag read replicas. Aurora Serverless v2 can
scale down to 0 ACU — **do not use the scale-to-zero configuration here**, for
the same cold-start reason as Neon.
*Trade-off:* cost, and a slightly narrower extension list than RDS (`pg_trgm`
is fine).

**7. Google AlloyDB for PostgreSQL**
Full PG compatibility plus a columnar engine for analytical queries. If your
percentile/neighborhood aggregates over 1.5M parcels become the bottleneck,
this is the specialist tool.
*Trade-off:* expensive; overkill at your current scale.

**8. Azure Database for PostgreSQL — Flexible Server**
Real PG, up to 32 TiB, solid managed story. Pick it if you are already on Azure.

### Tier 3 — interesting for your specific data shape

**9. Tiger Data (formerly Timescale) — Postgres + compression**
Real PG plus hypertables and columnstore compression. Your `storm_events`,
`signal_events`, and `stage_transitions` tables are textbook time-series, and
compression could substantially cut the `hcad_*`/`parcels` footprint if you go
multi-county. Extensions and PL/pgSQL all work.
*Trade-off:* you only get the benefit if you actually adopt hypertables.

**10. PlanetScale for Postgres**
Their Postgres offering (distinct from their MySQL/Vitess product) runs on local
NVMe with very high IOPS. Fast. Newer, so fewer miles on it.

---

## 4. Disqualified — do not choose these

| Option | Why it breaks this codebase |
|---|---|
| **CockroachDB** | No `pg_trgm` GIN trigram indexes → `/api/leads/search` breaks. No `pg_try_advisory_lock` → all 8 scheduler jobs break. Limited PL/pgSQL triggers. Generated columns cannot call `axon_normalize_address()`. |
| **AWS Aurora DSQL** | Postgres-*compatible* distributed rewrite: no extensions, no triggers, no PL/pgSQL. `0005`, `0006`, `0023`, `0038`, `0054`, `0065` all fail. |
| **YugabyteDB** | Reuses the PG query layer so much works, but advisory-lock support has been late/partial. Too much risk for 8 production cron jobs. |
| **PlanetScale (MySQL/Vitess), TiDB** | Wrong engine entirely. Every migration fails. |
| **Cloudflare D1, Turso/libSQL** | SQLite. Wrong engine. |
| **MotherDuck / DuckDB as primary** | Analytical, not OLTP. You already use DuckDB correctly — as the local HCAD build artifact (`tools/build_hcad_duckdb.py`), never as the serving database. |
| **Any transaction-mode pooler as the only DSN** | Breaks advisory locks (§1.2). Not a provider, but the most likely way to get burned. |

---

## 5. Migration checklist

`db/migrate.py` makes the move genuinely straightforward — it is provider-
agnostic and tracks state in `schema_migrations`.

1. Provision the new database; confirm **`CREATE EXTENSION pg_trgm`** is
   permitted (this is the one that most often needs an allowlist toggle).
2. `pg_dump` from Render → `pg_restore` into the target. Note that `parcels`
   depends on `axon_normalize_address()` existing before the generated column
   is created; a schema-then-data restore handles this, a parallel data-first
   restore may not.
3. Point `DATABASE_URL` at the **session-mode / direct** endpoint.
4. Run `python db/migrate.py status` — expect all 64 files `applied`, zero
   `orphan`.
5. Verify the things that fail silently:
   - `SELECT pg_try_advisory_lock(742026001), pg_advisory_unlock(742026001);`
     → must return `t`, `t`.
   - `SELECT * FROM pg_indexes WHERE indexdef LIKE '%gin_trgm_ops%';`
     → must return 5 rows.
   - `GET /api/hcad/status` → `{"source": "postgres", …}`, not `"none"`.
   - `SELECT address, address_norm FROM parcels LIMIT 5;` → `address_norm`
     populated.
6. Re-run `tools/load_hcad_to_postgres.py` only if the dump omitted `hcad_*`.
7. Watch the scheduler logs for one full day. "…skipped — another worker holds
   the lock" appearing on *every* run is the signature of a leaked advisory
   lock behind a transaction pooler.

---

## 6. The change that beats any provider swap

Before migrating anything, add connection pooling in the app. You are currently
paying a TCP + TLS + auth handshake on **every API request**
(`api/deps.py:12-17`). On a remote managed database that is typically 20–80 ms
added to every single call — very likely larger than the difference between any
two providers in §3.

`psycopg2.pool.ThreadedConnectionPool` (already available; `psycopg2-binary` is
in `requirements.txt`) fronting `get_db()` keeps the exact
connection-per-request *semantics* the routes rely on — each request still gets
its own connection and its own transaction — while eliminating the handshake.
It also caps concurrent connections, which protects you from the connection
limits in §1.3.

Do this first. Then choose a provider on storage, price, and ops preference —
because at your data size, that is genuinely what the decision comes down to.

---

## 7. Recommendation

- **Staying simple, want a clear upgrade:** DigitalOcean Managed Postgres.
- **Want the best Postgres-specific engineering:** Crunchy Bridge.
- **Want a free tier and lots of runway:** Supabase (port 5432 only).
- **Bursty traffic, storage-heavy roadmap:** Neon (direct endpoint, scale-to-zero off).
- **Committed to multi-county/national HCAD data:** AWS RDS `io2`, or Tiger Data
  if compression is attractive.

In every case: session-mode connections, `pg_trgm` available, PostGIS available
for the Phase 2/3 geo work.
