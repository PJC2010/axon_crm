# Scoring on free data

Why the vertical profiles produced almost no A grades on an account that has
not bought the demographic append, what the scorer now does about it, and what
the remaining levers are worth. Every figure below was produced by
`tools/vertical_grade_audit.py` on the checked-in Harris County export for ZIP
77396 (20,160 parcels, 14,636 dwelling-shaped) as of 2026-09-05.

| | |
|---|---|
| Audit tool | `tools/vertical_grade_audit.py` |
| The rule | `pipeline/scoring.py::_weighted_sum` / `renormalized_out`, `config.DEMOGRAPHIC_FIELDS`, `SCORE_DEMOGRAPHIC_BLOCK_MODE` |
| Weights | `config.DEFAULT_WEIGHTS`, `config.VERTICAL_WEIGHTS`, `config.REGIONAL_CALIBRATION_MATRIX` |
| Paid step | `pipeline/demographics.py` (`DEMO_PROVIDER` — Versium or BatchData demographic append) |
| Tests | `tests/test_scoring_hardening.py::TestDemographicBlock`, `tests/test_vertical_grade_audit.py` |
| Kill switch | `SCORE_DEMOGRAPHIC_BLOCK_MODE=zero` |

---

## 1. Which signals need a paid step

Six signals read a column that only the demographic append writes
(`config.DEMOGRAPHIC_FIELDS`):

| Signal | Field | Carried by |
|---|---|---|
| `home_improvement` | `home_improvement_flag` | every vertical |
| `refi` | `refi_date` | solar, roofing, hvac |
| `credit` | `credit_rating` | solar, hvac, pool_maintenance |
| `children` | `has_children` | pool_maintenance, fencing |
| `gardening` | `gardening_flag` | landscaping |
| `life_stage` | `life_stage` | epoxy, pool_maintenance, solar, fencing, landscaping |

Everything else is free: the assessor roll (`age`, `sale`, `equity` via the
flat fallback, `home_size`, `tenure`, `owner_occupied`), HCAD extra-features
(`garage`, `pool`, `slab`), the HCAD permit table (`permit`), NOAA (`storm`,
`hail`, `freeze`), Census ACS (`income`) and the computed `neighborhood` ratio.
The skip-trace append (`CONTACT_PROVIDER`) writes contact columns only — no
signal reads them, so it never moves a grade.

## 2. The rule: a NULL purchased attribute is not a zero

A NULL in one of those six columns never means "measured absent". It means the
append has not reached the row, or the provider returned nothing for that
field. Under `SCORE_MISSING_MODE=zero` — the right default for free signals,
where a NULL permit count or pool really is the county recording nothing — that
NULL scored 0, so the block's weight was a **constant** subtracted from every
un-appended lead's ceiling. A constant ranks nobody; it only caps the scale:

| Vertical | national paid share | ceiling, block scored 0 | Houston paid share | ceiling |
|---|---|---|---|---|
| default | 0 | 100.0 | 0 | 100.0 |
| pressure_washing | 0.050 | 95.0 | 0.049 | 95.1 |
| epoxy_flooring | 0.080 | 92.0 | 0.071 | 92.9 |
| roofing | 0.100 | 90.0 | 0.088 | 91.2 |
| landscaping | 0.150 | 85.0 | 0.146 | 85.4 |
| hvac | 0.160 | 84.0 | 0.145 | 85.5 |
| fencing | 0.190 | 81.0 | 0.170 | 83.0 |
| pool_maintenance | 0.230 | 71.2 | 0.218 | 73.1 |
| solar | 0.280 | **72.0** | 0.202 | 79.8 |

(`pool_maintenance` gates on `pool`, which contributes no points, so its paid
share is read against the non-gate weight.) Nationally a solar lead could not
be an A without the append, and it stayed a constant even on deployments that
run the append: the step is capped at `DEMO_MAX_ROWS_PER_ZIP` (200) per run and
grade-gated by `DEMO_MIN_GRADE`, so on a 14,636-row ZIP 98.6% of rows are
un-appended after a run.

The scorer therefore leaves a block field out of a row's numerator **and**
denominator whenever it is NULL (`SCORE_DEMOGRAPHIC_BLOCK_MODE=renormalize`,
the default). Consequences, each pinned by a test:

* An un-appended row is scored over its free signals alone. That is a pure
  multiplication of its old score by `live / (live − paid)`, so rank order
  among un-appended rows is unchanged — the audit prints the residual (0.000)
  as proof, and a perfect free-only row now scores 100 in every vertical and
  market.
* A row the append did reach keeps every returned field. A `False` flag or a
  `'D'` credit grade is a measurement and still counts, so poor demographics
  cost a row points against its un-appended neighbour — the append revealed
  something. A field the provider did not return is treated like any other
  NULL in the block.
* Free signals are untouched. `SCORE_MISSING_MODE` still governs them.
* `data_completeness` still reports the block as missing, which is what keeps
  "weak lead" and "thin file" distinguishable in the UI and the score
  snapshots.
* `explain_score` returns the factors a row was scored without as
  `renormalized_out`, and the lead-explain endpoint passes it through, so the
  UI can say "scored on property signals only" rather than drawing a 0-point
  credit bar as if it were measured.

Stored scores move only when a lead is rescored. Until then the explain
endpoint's `weights_drift` flag shows the difference, as it does after any
calibration change.

## 3. What the free signals look like on a real ZIP

Hit rates on 77396 under the Houston default profile (present = field is not
NULL; >0 = signal above zero; sat. = signal at 1.0):

| Signal | weight | present | >0 | sat. | mean | note |
|---|---|---|---|---|---|---|
| age | 0.223 | 100% | 100% | 42% | 0.76 | |
| sale | 0.196 | 100% | **6.5%** | 0% | 0.02 | a sale in the last 24 months |
| equity | 0.160 | 100% | 100% | 56% | 0.90 | fallback 0.6 × value vs the $150k Texas target |
| garage | 0.134 | — | — | — | — | not in the roll export; extra-features supply it in production |
| income | 0.053 | 100% | 100% | 100% | 1.00 | uniform across the ZIP |
| neighborhood | 0.053 | 100% | 50% | 5% | 0.22 | ratio vs the ZIP median |
| permit | 0.071 | **1.1%** | 1.1% | 0.1% | 0.01 | 266 parcels of 20,160 |
| owner_occupied | 0.060 | 100% | 74% | 74% | 0.74 | |
| home_size | 0.050 | 100% | 100% | 20% | 0.72 | 2,900 sqft Houston target |

Two free signals are structurally sparse: `sale` (6.5% of the book) and
`permit` (1.1%). Together they hold 16–30% of every profile. Under absolute
grade bands, weight on a signal that 93% of the book cannot earn caps those
93% just as the paid block did — the difference is that the 7% who do earn it
are genuinely the hottest leads, so this weight *does* rank.

## 4. Measured grade distributions

**As exported** (no extra-features, no storm data): zero A grades in every
profile under either mode, the default included (max 72.5). Roofing tops out
at 54.7 because `storm` + `hail` are 27% of its Houston profile.

**Typical enrichment scenario** — 2-car garage on every row, 12% of parcels
with a pool, a 1.75" hail storm 8 months ago and a freeze 20 months ago, both
ZIP-wide. `now` is production scoring; `block scored 0` is the legacy mode;
`proposal` is the reweight discussed in §5.1.

| Vertical (Houston) | A, block scored 0 | A now | A, proposal | p90 now |
|---|---|---|---|---|
| default | 61 (0.4%) | 61 (0.4%) | 260 (1.8%) | 64.0 |
| roofing | 0 | 2 (0.0%) | 3,287 (22.5%) | 66.6 |
| hvac | 0 | 0 | 427 (2.9%) | 63.8 |
| solar | 0 | 146 (1.0%) | 324 (2.2%) | 67.3 |
| landscaping | 0 | 40 (0.3%) | 56 (0.4%) | 60.8 |
| epoxy_flooring | 0 | 0 | 0 | 61.2 |
| pool_maintenance | 0 | 45 (0.3%) | 305 (2.1%) | 60.3 |
| fencing | 0 | 1 (0.0%) | 10 (0.1%) | 55.8 |
| pressure_washing | 5 (0.0%) | 50 (0.3%) | 317 (2.2%) | 60.7 |

Nationally solar goes 0 → 745 (5.1%) → 1,661 (11.3%) across the same three
columns, because the national profile puts 28% on the block.

**Quiet weather** (same scenario, no storm or freeze in the window): roofing
and hvac have zero A grades under every variant — roofing max 54.7, hvac max
63.1. That is the profile working as designed: roofing demand is storm-driven,
and the audit's ZIP-wide storm is generous (production matches reports within
one mile, so a real event lifts a swath, not a ZIP).

The block rule restores the top of the scale; it does not by itself fill it.
Expect ≤ 1% A grades in Houston from it alone.

## 5. The remaining levers

### 5.1 Move weight from sparse to dense free signals — a product decision

The `proposal` column trims `permit` (×0.35–0.5) and `sale` (×0.6–0.7) and,
for roofing and hvac, pins `home_size` at 0.06 (roof plane and duct run scale
with floor area — a per-home fact, so it passes the regional layer's rule).
The freed weight flows to `age`, `equity`, `tenure`, `storm`/`hail`/`freeze`
and `owner_occupied`, all dense on a county roll. Resulting weights, Houston
roofing:

```
age 0.207  sale 0.081  equity 0.135  income 0.021  neighborhood 0.021
permit 0.043  storm 0.238  tenure 0.042  hail 0.083  owner_occupied 0.071
home_size 0.060
```

This is a real reweight: the grade of 68% of roofing rows and 78% of hvac rows
changes, and ranking changes with it. What an A comes to mean shifts from
"motivated (just bought, pulling permits) and hit by a storm" to "old enough,
able to pay, and hit by a storm". Reasonable for replacement trades, where the
mechanism is component age; less so for landscaping and fencing, where a new
owner *is* the mechanism — which is why the landscaping proposal leaves `sale`
alone and still yields 0.4% A grades. Express it as a `scale`/`set` block in
`REGIONAL_CALIBRATION_MATRIX` (or a national one in `VERTICAL_WEIGHTS`), test
it with the audit's `--scale`/`--set` flags first, and regenerate the goldens;
`scripts/regen_golden.py` shows which factor moved each corpus row.

### 5.2 Thresholds — small effects, real trade-offs

* `GARAGE_TARGET` is 3 in Texas, so the modal 2-car garage scores 0.67: a
  third of the garage weight (4.5 points on the default profile, 7.7 on epoxy)
  is out of reach for most of the book. It was set there so the signal ranks
  the 3-car suburbs — a target the mode saturates ranks nobody. Under absolute
  bands, ranking calibration and grade attainability pull in opposite
  directions; that tension is the whole reason this document exists.
* `SALE_RECENCY_MAX_MO` 24 → 36 (`--threshold SALE_RECENCY_MAX_MO=36`) lifts
  roofing's max by about a point and landscaping's A count from 40 to 94.
  Marginal.
* `AGE_*` and `EQUITY_TARGET` already carry Texas overrides
  (`docs/regional_calibration.md`) and are not the constraint.

### 5.3 What not to do

* **`SCORE_MISSING_MODE=renormalize`** gives Houston roofing 15.7% A grades
  (`--renormalize`), but for the wrong reason: `permit_count_24mo` is NULL, not
  0, on a parcel with no permit (`pipeline/permits.py` only writes matches), so
  renormalize treats "no permit" as "unknown" and drops 10.5% of the profile
  from 99% of rows. It also inflates any row lacking garage or pool data. The
  block rule is that switch scoped to the one block where NULL genuinely means
  unknown.
* **Lowering `GRADE_BANDS`.** `CONTACT_MIN_GRADE` / `DEMO_MIN_GRADE`, the
  dialer's A-first queue and the reveal quota all key on the letter, so more
  A's by fiat means more paid appends and more revealed leads per month.

### 5.4 If the goal is "a workable A list"

Absolute bands over signals calibrated for ranking give few A's by
construction. The product already handles surfacing: `pipeline/focus.py`
widens the default lead list to B or C until it reaches max(50, 10% of the
book). If the letter itself needs to mean "top of this book", a percentile band
(A = top 10% within the account) follows the ranking without touching a single
weight — the p90 column above is that cutoff.

## 6. Quirks found on the way

* `EQUITY_FALLBACK_SIGNAL_SCALE` (0.5) applies only when the *scorer* derives
  equity, but `pipeline/hcad_enrichment.py` writes the same flat fallback first
  on every HCAD row, unflagged — so the down-weight never fires on the county
  roll. The audit mirrors production. Making it fire would lower every Texas
  score by up to half the equity weight.
* HCAD extra-features only ever write `has_pool = TRUE`; a parcel without the
  feature stays NULL, and NULL never gates. The pool_maintenance gate therefore
  never fires on HCAD-only rows.
* `zip_median_income` is one number per ZIP: it separates ZIPs, never homes.

## 7. Reproducing

```bash
python tools/vertical_grade_audit.py --zip 77396                              # as exported, Houston
python tools/vertical_grade_audit.py --zip 77396 --region us --no-hit-rates   # national profiles
python tools/vertical_grade_audit.py --zip 77396 --garage 2 --pool-share 0.12 \
    --storm-months 8 --hail-in 1.75 --freeze-months 20 --renormalize
python tools/vertical_grade_audit.py --zip 77396 --vertical roofing --garage 2 \
    --storm-months 8 --hail-in 1.75 --freeze-months 20 \
    --scale home_improvement=0 --scale refi=0 --scale permit=0.35 --scale sale=0.6 \
    --set home_size=0.06
SCORE_DEMOGRAPHIC_BLOCK_MODE=zero python tools/vertical_grade_audit.py --zip 77396   # legacy scoring
```

Another ZIP needs `python tools/export_hcad_zip.py <zip>` first (requires the
HCAD DuckDB). ACS income defaults to the golden fixture for the ZIP when one
exists; pass `--income` otherwise.
