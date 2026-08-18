# Golden-file test suite

Two separate layers, deliberately never merged:

| Layer | Runs | Network | Catches |
|---|---|---|---|
| **A — frozen fixtures** (`test_scoring_golden.py`, `test_boundaries.py`) | every PR (`pytest -m "not live"`) | none — replayed from disk, enforced by a socket guard | our scoring logic changed |
| **B — live contract** (`test_vendor_contract.py`, `-m live`) | nightly cron (`.github/workflows/nightly-contract.yml`) | real vendor APIs | RentCast / HCAD / ACS / geocoder changed under us |

Layer A is hermetic and fast (the whole repo suite runs in seconds); Layer B
is allowed to be slow and allowed to fail without blocking a merge — a failure
opens/updates a `Vendor drift detected` GitHub issue instead.

## How a golden is computed

`harness.py` re-implements **nothing**: each corpus address is replayed
through the real production entry points (`enrich_hcad` → `enrich_property` →
`fetch_income` → `enrich_permits` → `score_zip`), with only the process
boundaries (HTTP, Postgres, DuckDB) replaced by recorded fixtures — the same
`monkeypatch`-the-module-boundary convention the rest of `tests/` uses. The
clock is frozen at `clock.AS_OF` (2026-08-01) in every module that calls
`date.today()`, because the sale-recency/home-age/equity signals decay with
the wall clock and a golden that rots daily is a golden nobody trusts.

Asserted per address: all seven default-profile subscores, the composite
(pinned exactly as production stores it — `round(score, 2)`, Python
round-half-even, from `pipeline/scorer.py`), the grade, per-field
**provenance** (`hcad | rentcast | acs | computed | imputed:{basis}@{stage} |
missing`), the raw scored input values themselves (a vendor value drifting
inside a saturated signal moves no subscore — the `fields` assertion still
catches it), `data_completeness`, and the geocoder resolution.

## The corpus

`fixtures/addresses.yaml`: 25 Harris County addresses — 5 clear A, 5 B, 5 C,
3 below C, and 7 edge rows (new construction; the `garage_spaces = 0` vs
`NULL` twins; a condo with no HCAD parcel match; an ambiguous geocode; a ZCTA
with the ACS suppressed-estimate sentinel; a 90-day-old sale). Synthetic
boundary rows in `test_boundaries.py` pin `GRADE_BANDS` inclusivity at
34.9/35.0/54.9/55.0/74.9/75.0.

**The shipped fixtures are synthetic**: schema-exact vendor payloads authored
by hand (`synthetic: true` in addresses.yaml), so they contain no PII by
construction and Layer A is fully functional. Layer B needs real baselines:
`python scripts/refresh_fixtures.py --confirm` (with `RENTCAST_API_KEY` etc.
set) re-records live payloads, sanitizes them, and registers each slug in
`fixtures/recorded.json` — only registered slugs are drift-checked nightly;
the rest are skipped with an explicit reason, so the nightly job is green
until real baselines exist. House numbers in the synthetic corpus are
fabricated; when recording live, expect some addresses to need replacing with
real parcels (the recorder reports which sources answered).

## Fixture hygiene (enforced by tests, not convention)

`sanitize.py` allowlists what may reach disk: no API keys, **no owner PII**
(owner names, mailing addresses, phones, skip-trace fields — fixtures
describe real parcels and live in git history permanently; TX SB 2121 makes
this a hard requirement). Only fields the six factors and the address/parcel
verification consume survive. Serialization is canonical (sorted keys, floats
pinned to 6 decimals) so re-recording diffs cleanly.
`TestFixtureHygiene` fails the PR if a fixture violates any of this.

## Changing a golden

```
python scripts/regen_golden.py            # dry run — prints the per-factor diff table
python scripts/regen_golden.py --confirm  # writes expected/scores.json
```

`--confirm` is required, the script refuses to run in CI, and a changed
golden is a reviewable diff a human reads — never an automatic update.

## Observed behaviors pinned deliberately (not endorsed, not "fixed")

This suite observes current behavior; changing any of these belongs in its
own PR, where the golden diff will show exactly what moved:

1. **`garage_spaces` 0 vs NULL score identically** under the default
   `SCORE_MISSING_MODE="zero"`. The suite pins the difference where it *does*
   surface today — `data_completeness` (0 counts as measured, NULL doesn't)
   and provenance — plus the fact that the opt-in `renormalize` mode
   separates the composites.
2. **Flat-fallback equity dodges its own haircut when enrichment writes it.**
   `EQUITY_FALLBACK_SIGNAL_SCALE` (0.5×) only applies when the *scorer*
   backfills equity at scoring time; when `enrich_hcad`/`enrich_property`
   store the same `value × 0.6` fallback into the row first, the scorer sees
   a populated field and applies full weight. In Texas (non-disclosure, so
   RentCast rarely has a sale price) HCAD-seeded rows effectively always
   carry full-weight fallback equity.
3. **"No permits" is NULL, not 0** — `query_permits` only emits addresses
   that have permits, so a quiet home loses `data_completeness` rather than
   scoring a measured zero.
4. **Grade comes from the unrounded float.** A composite that *displays* as
   75.0 can grade B (74.99999999999999) — the boundary rows pin raw floats on
   the correct side of each band edge.
5. **There is no ATTOM integration** in this codebase. The cascade is
   HCAD → RentCast (plus ACS income, county permits, Census/Google
   geocoding); the provenance vocabulary reflects reality. The
   "fallback-source swap" failure the brief describes is pinned as
   HCAD→RentCast (`TestSuiteSensitivity::test_cascade_swap_flips_provenance`).
6. **The ambiguous geocode resolves to the first candidate** at confidence
   0.6 (`CensusGeocoder`), and the ACS suppressed-estimate sentinel
   (-666666666) leaves `zip_median_income` NULL.
