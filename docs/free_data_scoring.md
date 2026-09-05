# Scoring on free data

Why the vertical profiles produce almost no A grades on an account that has not
bought the demographic append, what reweighting can and cannot do about it, and
the numbers behind each option. Every figure below was produced by
`tools/vertical_grade_audit.py` on the checked-in Harris County export for ZIP
77396 (20,160 parcels, 14,636 dwelling-shaped) as of 2026-09-05.

| | |
|---|---|
| Audit tool | `tools/vertical_grade_audit.py` |
| Weights | `config.DEFAULT_WEIGHTS`, `config.VERTICAL_WEIGHTS`, `config.REGIONAL_CALIBRATION_MATRIX` |
| Engine | `pipeline/scoring.py::_weighted_sum` (missing field scores 0 in the default `SCORE_MISSING_MODE=zero`) |
| Paid step | `pipeline/demographics.py` (`DEMO_PROVIDER` — Versium or BatchData demographic append) |
| Tests | `tests/test_vertical_grade_audit.py` |

---

## 1. Which signals need a paid step

Six signals read a column that only the demographic append writes. With
`DEMO_PROVIDER` unset they are NULL on every row, and a NULL scores 0, so the
weight on them is a **constant** subtracted from every lead's ceiling — it
ranks nobody.

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

## 2. The ceiling that leaves

Share of each profile spent on the paid block, and the best score a free-only
row can reach. A gate factor (`pool` for pool_maintenance) contributes no
points, so its weight is excluded before the share is read.

| Vertical | national paid share | ceiling | Houston paid share | ceiling |
|---|---|---|---|---|
| default | 0 | 100.0 | 0 | 100.0 |
| pressure_washing | 0.050 | 95.0 | 0.049 | 95.1 |
| epoxy_flooring | 0.080 | 92.0 | 0.071 | 92.9 |
| roofing | 0.100 | 90.0 | 0.088 | 91.2 |
| landscaping | 0.150 | 85.0 | 0.146 | 85.4 |
| hvac | 0.160 | 84.0 | 0.145 | 85.5 |
| fencing | 0.190 | 81.0 | 0.170 | 83.0 |
| pool_maintenance | 0.230 | 71.3 | 0.218 | 73.1 |
| solar | 0.280 | **72.0** | 0.202 | 79.8 |

Nationally a solar lead cannot be an A without the append; pool_maintenance
cannot either. Houston's regional layer softens this only because its `set`
pins (owner_occupied, home_size, hail, freeze) rescale the paid block down.

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
grade bands, weight on a signal that 93% of the book cannot earn is a ceiling
cut for those 93%, exactly like the paid block — the difference is that the 7%
who do earn it are genuinely the hottest leads, so this weight *does* rank.

## 4. Measured grade distributions

**As exported** (no extra-features, no storm data): zero A grades in every
profile, the default included (max 72.5). Roofing tops out at 49.9 because
`storm` + `hail` are 27% of its Houston profile.

**Typical enrichment scenario** — 2-car garage on every row, 12% of parcels
with a pool, a 1.75" hail storm 8 months ago and a freeze 20 months ago, both
ZIP-wide. `drop_paid` is the current profile with the paid block scaled to 0
and the rest rescaled (`regional.apply_weight_spec`). `proposal` additionally
moves weight off the sparse signals (see §5).

| Vertical (Houston) | current A | drop_paid A | proposal A | proposal p90 |
|---|---|---|---|---|
| default | 61 (0.4%) | — | 260 (1.8%) | 70.5 |
| roofing | 0 | 2 (0.0%) | 3,287 (22.5%) | 77.0 |
| hvac | 0 | 0 | 427 (2.9%) | 74.0 |
| solar | 0 | 146 (1.0%) | 324 (2.2%) | 70.1 |
| landscaping | 0 | 40 (0.3%) | 56 (0.4%) | 62.1 |
| epoxy_flooring | 0 | 0 | 0 | 64.5 |
| pool_maintenance | 0 | 45 (0.3%) | 305 (2.1%) | 66.8 |
| fencing | 0 | 1 (0.0%) | 10 (0.1%) | 58.6 |
| pressure_washing | 5 (0.0%) | 50 (0.3%) | 317 (2.2%) | 64.8 |

Nationally, solar goes 0 → 730 (5.0%) → 1,661 (11.3%) across the same three
columns, because the national profile puts 28% on the paid block.

**Quiet weather** (same scenario, no storm or freeze in the window): roofing
and hvac have zero A grades under every variant — roofing max 57.4, hvac max
68.3 with the proposal. That is the profile working as designed: roofing demand
is storm-driven, and the audit's ZIP-wide storm is generous (production matches
reports within one mile, so a real event lifts a swath, not a ZIP).

## 5. The levers, in order

### 5.1 Drop the paid block where it is structurally absent — safe

Because every paid field is NULL on every un-appended row, removing those
weights and rescaling multiplies each score by `live / (live − paid)`. Rank
order is untouched; only the labels move. The audit prints the residual (≤ 0.02
points, from rounding the rescaled weights to four places) as proof, and
`tests/test_vertical_grade_audit.py::test_drop_paid_is_a_pure_rescale` pins it.

Two ways to ship it:

* **Profile-level**, when `DEMO_PROVIDER` is empty: build every property
  profile in `pipeline/profiles.py` through
  `regional.apply_weight_spec(weights, {"scale": {k: 0.0 for k in PAID}})`.
  Small, mechanical, and the explain UI follows automatically because
  `describe_vertical(vertical, profile)` reads the profile it is handed.
* **Row-level block renormalization** (the better version): in
  `_weighted_sum`, when *every* field in the demographic block is NULL on the
  row, leave the block out of the denominator for that row. This also covers
  deployments that *do* run the append, where the block is still constant for
  almost the whole book: the step is capped at `DEMO_MAX_ROWS_PER_ZIP` (200)
  per run and grade-gated by `DEMO_MIN_GRADE`, so on a 14,636-row ZIP 98.6% of
  rows are un-appended after a run. An appended row keeps the full formula, so
  a bad credit grade or no refi still costs it points relative to its
  un-appended neighbours — the append revealed something.

Either way, expect ≤ 1% A grades in Houston afterwards. This lever restores the
top of the scale; it does not by itself fill it.

### 5.2 Move weight from sparse to dense free signals — a product decision

The `proposal` column above trims `permit` (×0.35–0.5) and `sale` (×0.6–0.7)
and, for roofing and hvac, pins `home_size` at 0.06 (roof plane and duct run
scale with floor area — a per-home fact, so it passes the regional layer's
rule). The freed weight flows to `age`, `equity`, `tenure`, `storm`/`hail`/
`freeze` and `owner_occupied`, all dense on a county roll. Resulting weights,
Houston roofing:

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
`REGIONAL_CALIBRATION_MATRIX` (or a national one in `VERTICAL_WEIGHTS`) and
regenerate the goldens; `scripts/regen_golden.py` shows which factor moved each
corpus row.

### 5.3 Thresholds — small effects, real trade-offs

* `GARAGE_TARGET` is 3 in Texas, so the modal 2-car garage scores 0.67: a
  third of the garage weight (4.5 points on the default profile, 7.7 on epoxy)
  is out of reach for most of the book. It was set there so the signal ranks
  the 3-car suburbs — a target the mode saturates ranks nobody. Under absolute
  bands, ranking calibration and grade attainability pull in opposite
  directions; that tension is the whole reason this document exists.
* `SALE_RECENCY_MAX_MO` 24 → 36 (`--threshold SALE_RECENCY_MAX_MO=36`) lifts
  roofing's max from 70.4 to 71.6 and landscaping's `drop_paid` A count from 40
  to 94. Marginal.
* `AGE_*` and `EQUITY_TARGET` already carry Texas overrides
  (`docs/regional_calibration.md`) and are not the constraint.

### 5.4 What not to do

* **`SCORE_MISSING_MODE=renormalize`** gives Houston roofing 15.7% A grades
  (`--renormalize`), but for the wrong reason: `permit_count_24mo` is NULL, not
  0, on a parcel with no permit (`pipeline/permits.py` only writes matches), so
  renormalize treats "no permit" as "unknown" and drops 10.5% of the profile
  from 99% of rows. It also inflates any row lacking garage or pool data. It is
  a blunt instrument, not a reweight.
* **Lowering `GRADE_BANDS`.** `CONTACT_MIN_GRADE` / `DEMO_MIN_GRADE`, the
  dialer's A-first queue and the reveal quota all key on the letter, so more
  A's by fiat means more paid appends and more revealed leads per month.

### 5.5 If the goal is "a workable A list"

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
```

Another ZIP needs `python tools/export_hcad_zip.py <zip>` first (requires the
HCAD DuckDB). ACS income defaults to the golden fixture for the ZIP when one
exists; pass `--income` otherwise.
