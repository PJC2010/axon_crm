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
| `code_description_real.zip` *(optional)* | `desc_r_01_state_class.txt` | `state_class_codes` (county label per class) |
| `code_description_real.zip` *(optional)* | `desc_r_02_building_type_code.txt` | `building_type_codes` |

The files are tab-delimited with a header row, encoded latin-1 (Windows-1252).

## `property_summary` (built from `real_acct.txt`)

| Axon column | HCAD source | Notes |
|---|---|---|
| `acct` | `real_acct.acct` | parcel id, join key |
| `site_address` | `real_acct.site_addr_1` | parcel street address |
| `site_city` | `real_acct.site_addr_2` | parcel's own (situs) city — the display city; **never** substitute `mail_city` |
| `site_zip` | `real_acct.site_addr_3` | |
| `year_built` | `building_res.date_erected`, else `real_acct.yr_impr` | **proxy** unless `Real_building_land.zip` is present |
| `building_sqft` | `real_acct.bld_ar` | total building area |
| `land_sqft` | `real_acct.land_ar` | total land area (sq ft) |
| `tot_appr_val` | `real_acct.tot_appr_val` | appraised value |
| `last_sale_date` | `MAX(deeds.dos)` | latest deed date per parcel |
| `owner_name` | `owners.name` (primary), else `real_acct.mailto` | |
| `mail_addr` / `mail_city` / `mail_state` / `mail_zip` | `real_acct.mail_addr_1` / `mail_city` / `mail_state` / `mail_zip` | owner mailing address |
| `likely_owner_occupied` | derived | normalized `mail_addr_1` == `site_addr_1` |
| `state_class` | `real_acct.state_class` | Texas Comptroller State Category Code — the county's own "what is this?" |

## Code descriptions (from `code_description_real.zip`, optional)

HCAD publishes the decode tables for its own codes as a separate download
("Code Descriptions (Real)"). Two are loaded:

| DuckDB table | HCAD source | Decodes |
|---|---|---|
| `state_class_codes(cd, dept, dscr)` | `desc_r_01_state_class.txt` | `real_acct.state_class` |
| `building_type_codes(cd, dscr)` | `desc_r_02_building_type_code.txt` | `building_res.impr_tp` |

`dept` is a **rollup, not a restatement of `cd`** — every improved condo class
rolls up to A1 single-family (Z1 Apartment Conversion, Z2 Fee Simple Townhouse,
Z3 Townhouse, Z4 Apartment Style, Z5 High Rise), the unimproved Z0 to C1 vacant,
and X1/X2/X3/X4/X7 alike to XV.

`pipeline/property_type.py` turns `state_class` into `properties.property_type`,
which is otherwise written only by RentCast. It maps **only dwellings** (A1, A2,
A4, B1–B4, E1, M3, Z1–Z5) and returns NULL for everything else, including A3
(Auxiliary Buildings — a shed, `bld_ar = 0`) and Z0 (unimproved). Excluding
non-residential parcels stays `pipeline/residential.py`'s job, reading
`state_class` directly. Measured on the full county roll: 79.5% of parcels typed,
71.6% Single Family.

`building_res.impr_tp` is a finer grain than `state_class` and is **not yet
carried** into `property_summary` — it separates 22,530 townhomes that
`state_class` files as plain A1. Adding it means a new column in the
`property_summary` projection and another full rebuild.

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
