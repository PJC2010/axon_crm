# Regional scoring calibration

How Axon scores a lead differently in Houston than in Chicago, and why the
answer is a layer rather than a second model.

Source research: *Axon Scoring Engine — Regional Calibration: Houston, Texas,
and the Texas Region*, the companion to the national weight-matrix report. Every
figure quoted below comes from it.

| | |
|---|---|
| Data | `config.REGIONAL_CALIBRATION_MATRIX`, `config.REGION_PARENTS`, `config.TX_GULF_ZIP3` |
| Math | `pipeline/regional.py` |
| Profiles | `pipeline/profiles.py::resolve_profile(vertical, region)` |
| Signals | `pipeline/scoring.py::build_signal_fns` |
| Tests | `tests/test_regional.py`, `tests/golden/` |
| Kill switch | `REGIONAL_CALIBRATION=off` |

---

## 1. The rule that decides what belongs here

> **A regional factor earns a weight only if it varies between two homes in the
> same market.**

This is the whole discipline, and it is the one thing to get right when reading
the research into config. The research states a national weight matrix on a 0–5
scale and then a Texas column of deviations. Some of those rows are properties
of a *home*; the rest are properties of a *market*:

| Research row | Varies within a market? | Where it lands in Axon |
|---|---|---|
| Component / home age | yes | weight (`age`) |
| Storm exposure, hail severity | yes | weight (`storm`, `hail`) |
| Freeze / hurricane events | yes | weight (`freeze`, `storm`) |
| Garage count, floor area, pool | yes | weight (`garage`, `home_size`, `pool`) |
| Owner-occupancy | yes | weight (`owner_occupied`) |
| Permit activity, equity | yes | weight (`permit`, `equity`) |
| Cooling degree days / climate | **no** | base rate + age runtime factor |
| Electricity price | **no** | base rate (documents why solar reweights) |
| Net-metering policy, rebates | **no** | base rate |
| Growing-season length | **no** | job value (annual customer value) |
| Relative humidity | **no** | job value (moisture-barrier systems) |

Weighting a market constant looks like calibration and is not. Houston's cooling
season is nine months for every house in Houston, so a `climate: 5` weight adds
the same number of points to every lead in the market: no lead moves past any
other, and the only visible effect is that the grade distribution inflates.
Ranking is a *within-market* problem. Cross-market demand differences are real
and belong in `base_rates` (how many homes buy per year) and `job_value` (what
the ticket is worth) — numbers used for forecasting and pipeline value, never
for a lead's rank.

`tests/test_regional.py::test_every_weighted_signal_reads_a_property_field`
enforces this mechanically: a weighted signal must read a column that exists per
property.

## 2. Mechanics

### Resolution

Region is derived from the ZIP being scored, per ZIP3 prefix, with the row's own
`state` as a cross-check — a mistyped ZIP on a Louisiana row must not pick up
Texas hail calibration. `pipeline/scorer.py` resolves it once per run, because a
run is per-ZIP and the whole batch shares one market.

```
750–799, 885xx          → tx
770–777 (Gulf Coast)    → tx_houston   (Houston metro, Galveston, Beaumont)
everything else         → us
```

The Texas/Gulf split is not cosmetic. One state holds the country's most humid
major metro and a desert, and at least one calibration in the research (turf
removal and water stress) points in opposite directions across it.

`REGIONAL_CALIBRATION` controls the whole layer: `auto` (default) derives from
the ZIP, `off` scores every market nationally, and any region key pins all
scoring to that market — which is how you reproduce a customer's numbers locally.

### Inheritance

Regions form a chain — `us ▸ tx ▸ tx_houston` — and deltas merge root-to-leaf.
Houston states only what it does differently from Texas. A national
recalibration therefore propagates into every market instead of being
re-litigated per region, which is the entire reason this is a layer and not a
fork.

### Two kinds of weight delta

```python
"roofing": {
    "scale": {"storm": 1.15, "absentee": 0.0},
    "set":   {"hail": 0.07, "owner_occupied": 0.06},
}
```

* **`scale`** multiplies a weight the national profile already carries. It is
  *relative*, so it survives a national recalibration: "storm matters ~15% more
  in Texas" stays true whatever storm's national share becomes. `0.0` removes a
  signal. Scaling a signal the base profile doesn't carry raises — that's a typo,
  not a no-op, and it would otherwise fail silently forever.
* **`set`** pins an exact final share, and is the only way to introduce a signal
  the national profile doesn't weight at all. Everything unpinned rescales to
  fill `1 − Σset`, preserving the national profile's internal proportions.

The result is rounded to 4 decimals (weights are read by humans in the
explanation UI and diffed in review) with the residual pushed onto the largest
weight, so it still sums to exactly 1.0 and `validate_weights` accepts it.

### Thresholds

A market can override any entry in `scoring.DEFAULT_THRESHOLDS`, region-wide or
per vertical (vertical wins). Overrides build a complete, independent set of
signal functions rather than mutating module globals, so two markets can score in
the same process — a per-ZIP pipeline run and a per-lead explanation for a
different ZIP can be in flight at once.

**A threshold is a calibration knob, not a constant.** A target that every home
in a market clears is a signal with no ranking information left in it. Three of
the four Texas threshold changes below exist purely for that reason.

## 3. The Texas calibration

### Region-wide

| Threshold | National | Texas | Why |
|---|---|---|---|
| `AGE_DECAY_YEARS` | 20 | 35 | TX median home age ~30 vs ~41 nationally; Houston's median build year is 1989, so the modal home sits past the national sweet spot where the curve is already decaying it toward zero |
| `AGE_DECAY_FLOOR` | 0.0 | 0.20 (0.25 Houston) | An old home in a high-runtime climate never leaves the market — it cycles |
| `EQUITY_TARGET` | $100k | $150k | Harris County median property value ~$277k on ~47% state price appreciation since 2020; at $100k the median owner-occupant pins the signal at 1.0 |
| `GARAGE_TARGET` | 2 | 3 | The West South Central division builds 72% of new homes with a two-car garage — two spaces is the mode, not the standout |
| `STORM_HAIL_TARGET_IN` | 1.5″ | 1.75″ | Greater Houston takes golf-ball hail nearly every spring; 1.5″ grades a routine spring the same as a roof-replacing one |
| `HOME_SIZE_TARGET_SQFT` | 3,000 | 2,900 (Houston) | ≈1.4× the ~2,040 sqft Harris County median existing single-family home, so the modal home lands near 0.7 and the signal keeps its spread |

**Decay before floor, in that order.** An early draft used a floor alone. The
golden suite caught it: at the national 20-year decay a floor of 0.35 binds from
age 43, tying a 1983 build and a 1930 build at one number across a large minority
of Houston's stock. Stretching the decay to 35 years keeps them ordered (1989 →
0.83, 1980 → 0.54, 1970 → 0.26) and the floor then catches only genuinely ancient
stock.

### Per vertical

**Roofing** — Texas logged ~811,000 hail claims over three years, nearly double
second-place Colorado, and 2024 added the May derecho and Hurricane Beryl
straight through Harris County. `storm` scales ×1.15 and gains `hail` at 0.07:
adjusters approve a full replacement on granule loss, which is a function of
stone size, not of the fact that it hailed. The age curve gets a 1.15 runtime
factor (hail and UV age a roof faster) with a 0.40 floor.

**HVAC** — a nine-month cooling season, so equipment reaches end of life earlier
in calendar years. This is modelled as `AGE_RUNTIME_FACTOR: 1.20` rather than a
hand-shifted band, so one number carries the research's whole "effective
component age" claim: ten calendar years on a Houston condenser is roughly twelve
of Midwest wear, and replacement propensity peaks 1–3 years earlier. Hail does
not sell an HVAC system; freezes and hurricanes do, so `storm` scales to 0.80 and
`freeze` enters at 0.09.

**Solar** — Texas power is ~25% below the national average and the state has no
net-metering mandate, yet payback still beats the nation because consumption is
enormous: Houston solar shoppers average 1,864 kWh/month and $288 bills. Rate and
policy are market constants and get no weight. What varies house to house is how
much power the house burns, so the consumption proxies are what rise: `home_size`
0.10 and `pool` 0.04, with `income` scaled to 0.70. `freeze` and `storm` enter at
0.04 each as the *resilience* proxy — after Uri's 42-hour average outages and
Beryl's 2.2-million-customer blackout, battery-attached solar is a resilience
purchase here as much as an economic one. The age curve inverts: peak moves to
5–20 years because panels need a roof with life left, and Houston's 1990s–2000s
cohort increasingly needs re-roofing first.

**Epoxy flooring** — the sweet spot is the newer master-planned suburbs (Katy,
Cypress, Spring, the Conroe corridor): big garages, high equity, no legacy
coating. `garage` ×1.15, `equity` ×1.10, age band moved to 8–25 years. Humidity
above 75% year-round is what closes the sale, but it is identical for every
garage in the market, so it moves the ticket (job value ×1.25), not the rank.

**Landscaping** — a ~9-month growing season and ~33 mowing visits a year against
~26 nationally. Both are market constants: they raise annual customer value (job
value ×1.25 in Houston, which more than absorbs the below-average 7,131 sqft
median lot) and change no lead's rank. `gardening` ×1.20 and the occupancy swap
are the only weight moves.

**Fencing / pool maintenance / pressure washing** — the occupancy swap, plus
`storm` ×1.15 for fencing and ×1.10 for pressure washing.

### The occupancy swap

This is the research's sharpest deviation and the one most worth validating
against real outcomes.

Nationally Axon weights `absentee` — at a 65% homeownership rate, absentee
ownership is the rarer and therefore more informative state, and a landlord is a
genuine buyer of exterior and systems work. Texas replaces it with
`owner_occupied` in every trade. Harris County is 53.8% owner-occupied and
falling (down from 55.2%, a loss of ~19,000 owner households in one year), and
the City of Houston proper is only ~42%. At that split occupancy carries its
maximum discriminative power, and the research says it points the other way:
landlord-owned stock buys the same job on price-shopped, lower-quality economics.

The two signals read the same column and disagree about which way it points, so
no profile may weight both — that would pay every lead the same regardless of the
answer. `tests/test_regional.py::test_no_profile_weights_both_occupancy_signals`
enforces it.

### Market priors

`base_rates` are annual purchase incidence, share of owner homes buying per year.
They are **priors from published research, not fitted values**, and they never
touch a lead's rank.

| Vertical | National | Texas |
|---|---|---|
| Roofing | 5.5% | 7.5% |
| HVAC | 6.0% | 7.5% |
| Solar | 1.0% | 1.0% |
| Landscaping | 28% | 35% |
| Epoxy | 2.0% | 2.8% |

Solar does not move: Texas ranks #1 in new installations and only #4 in
residential, because utility-scale farms dominate the headline number.

`job_value` multiplies `JOB_VALUE_MODEL`'s output. **`us` is not a neutral
baseline here** — that model's numbers were written as rough Houston-market
defaults, so a Texas multiplier above 1.0 claims a market is dearer *than Houston
already is*, not dearer than the nation. Only landscaping and epoxy carry one,
because those are the two the research separates from that baseline on grounds
other than home size.

## 4. Data-layer changes this required

**Freeze events** (migration 0081, `pipeline/storm.py`). The HVAC calibration is
only as good as its input, and until now the storm layer had no vocabulary for a
freeze. `last_freeze_date` and `freeze_count_24mo` are separate columns from
`last_storm_date`, and must stay that way: Houston logged 120 SNOW reports in
January 2025 against 122 HAIL reports over the same 24 months, so one shared
column would have blanked the storm signal for every roofing lead in the market.
The freeze window (`FREEZE_RECENCY_MAX_MO`, 36 months) is wider than the storm
window because a hard freeze kills equipment on a delay.

**Hurricane wind** (`_TYPE_MAP`). `TROPICAL CYCLONE` now maps to `wind`. The
flood types stay excluded, and that exclusion is load-bearing rather than
incidental: Beryl produced `TROPICAL CYCLONE`, `NON-TSTM WND GST`, `STORM SURGE`,
`FLASH FLOOD` and `COASTAL FLOOD` in one window, and only the wind half drives
roofing work — hurricane flood damage runs through NFIP and buys no roof. Keying
storm exposure to a hurricane *path* rather than to wind and hail would score the
flooded side of the storm as demand.

**Hail severity is now scored.** `hail_size_in` and `STORM_HAIL_TARGET_IN` both
already existed; nothing read them. The `hail` signal wires them in.

**Home size is now scored.** `square_footage` was stored, and used for job value,
but never as a signal.

## 5. Known gaps

* **Split permitting.** Work inside the City of Houston runs through the Houston
  Permitting Center; unincorporated Harris County runs through the county's
  e-Permits system, and post-storm contractors routinely file in the wrong one.
  Axon's permit backbone (`pipeline/permits.py`) reads the HCAD permit table and
  does not query either system directly, so replacements are likely undercounted
  and the suppression logic misfires accordingly. `COUNTY_ADAPTERS` is the
  extension point.
* **Grid resilience is a proxy, not a measurement.** The research asks for an
  outage-history modifier keyed to service territory. There is no outage feed;
  `freeze` and `storm` recency stand in for it. A CenterPoint outage-history
  layer is the upgrade path.
* **Every number here is a prior.** None of it is fitted to Axon's own outcome
  data. The research's own closing advice is that Texas is the fastest region in
  the country to validate empirically — permit-rich and event-dense. The
  score-snapshot feedback loop (`pipeline/score_snapshots.py`) already records
  which region calibrated each lead, so re-fitting is a join away.

## 6. Adding a region

1. Add the key to `REGION_PARENTS`, `REGION_LABELS`, and the ZIP3 resolver.
2. Add a block to `REGIONAL_CALIBRATION_MATRIX` stating only what differs.
3. Add its state to `regional.REGION_STATES` so the ZIP cross-check works.
4. `tests/test_regional.py` parametrizes over every region in the matrix, so the
   profile invariants cover it for free. Add the market's own claims as explicit
   tests alongside `TestTexasCalibration`.
5. Run `python scripts/regen_golden.py` and **read the diff** — the golden corpus
   is Harris County, so a non-Texas region should move nothing.
