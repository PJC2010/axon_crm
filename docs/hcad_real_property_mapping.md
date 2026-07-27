# HCAD Real Property → Axon mapping

How Harris County Appraisal District (HCAD) **Real property** export files map
into the tables Axon's pipeline consumes. Column meanings come from the
[HCAD PDATA Codebook](https://hcad.org/assets/uploads/pdf/pdataCodebook.pdf).

> Scope note: Axon targets **residential homeowners**, so the *Real* property
> export is the right HCAD dataset. The separate *Personal* property export
> (`PP_files.zip`, `t_*` tables) describes **businesses** and is **not** used
> here — see the prior analysis.

## Source files

| HCAD zip | File | Feeds |
|---|---|---|
| `Real_acct_owner.zip` | `real_acct.txt` | `property_summary` (site + mailing address, value, area) |
| `Real_acct_owner.zip` | `owners.txt` | `property_summary.owner_name` (clean primary owner) |
| `Real_acct_owner.zip` | `deeds.txt` | `property_summary.last_sale_date` |
| `Real_acct_owner.zip` | `permits.txt` | `permits` |
| `Real_building_land.zip` *(optional)* | `extra_features.txt` | `extra_features` (pool / slab / garage) |
| `Real_building_land.zip` *(optional)* | `building_res.txt` | `property_summary.year_built` (true year built) |

The files are tab-delimited with a header row, encoded latin-1 (Windows-1252).

## `property_summary` (built from `real_acct.txt`)

| Axon column | HCAD source | Notes |
|---|---|---|
| `acct` | `real_acct.acct` | parcel id, join key |
| `site_address` | `real_acct.site_addr_1` | parcel street address |
| `site_zip` | `real_acct.site_addr_3` | (`site_addr_2` = city) |
| `year_built` | `building_res.date_erected`, else `real_acct.yr_impr` | **proxy** unless `Real_building_land.zip` is present |
| `building_sqft` | `real_acct.bld_ar` | total building area |
| `land_sqft` | `real_acct.land_ar` | total land area (sq ft) |
| `tot_appr_val` | `real_acct.tot_appr_val` | appraised value |
| `last_sale_date` | `MAX(deeds.dos)` | latest deed date per parcel |
| `owner_name` | `owners.name` (primary), else `real_acct.mailto` | |
| `mail_addr` / `mail_city` / `mail_state` / `mail_zip` | `real_acct.mail_addr_1` / `mail_city` / `mail_state` / `mail_zip` | owner mailing address |
| `likely_owner_occupied` | derived | normalized `mail_addr_1` == `site_addr_1` |

## `permits` (from `permits.txt`)

| Axon column | HCAD source |
|---|---|
| `id` | `permits.id` |
| `acct` | `permits.acct` |
| `status` | `permits.status` |
| `issue_date` | `permits.issue_date` (MM/DD/YYYY → DATE) |
| `permit_type` | `permits.permit_type` |
| `permit_tp_descr` | `permits.permit_tp_descr` |

## `extra_features` (from `extra_features.txt`, optional)

| Axon column | HCAD source |
|---|---|
| `acct` | `extra_features.acct` |
| `bld_num` | `extra_features.bld_num` |
| `cd` | `extra_features.cd` (use code) |
| `s_dscr` | `extra_features.s_dscr` |
| `l_dscr` | `extra_features.l_dscr` |
| `uts` | `extra_features.uts` (units) |

Signals are derived at query time in `pipeline/hcad_store.query_extra_features`:
`has_pool` (`l_dscr LIKE %POOL%`), `has_cracked_slab`, `garage_spaces`
(`SUM(uts)` where `l_dscr LIKE %GARAGE%`, converted from square feet to a
space count at ~240 sqft/car by `garage_spaces_from_sqft()` — HCAD's `uts`
is garage area, not a car count).

## How it flows into the CRM

1. **Build the DuckDB** from the raw files:
   ```bash
   python tools/build_hcad_duckdb.py /path/to/unzipped_hcad_dir -o harris_county.duckdb
   ```
   Point `PERMIT_DB_PATH` at the result. `pipeline/hcad_store.py` reads it
   directly (and `pipeline/hcad_enrichment.py` backfills null property fields,
   now including `mailing_address`).

2. **Or mirror selected ZIPs into Postgres** (for hosts without the DuckDB):
   ```bash
   python tools/export_hcad_zip.py 77002 77396      # writes per-ZIP CSVs
   # then POST each pair to /api/hcad/upload
   ```
   Requires migration `0020_hcad_mailing_address.sql` for the mailing columns.

## What this does and doesn't add

- ✅ Richer **location** (precise site address) and **owner mailing address**
  per parcel — the mailing address is the high-value input for skip-trace
  (`pipeline/contact.py`) and direct mail.
- ✅ `last_sale_date` from deeds; owner-occupancy inference.
- ⚠️ **No phone/email** — HCAD never publishes those. `mailing_address` +
  `owner_name` improve skip-trace hit rate; they don't replace it.
- ⚠️ Without `Real_building_land.zip`, `year_built` is the `yr_impr` proxy and
  pool/slab/garage signals stay empty.
