#!/usr/bin/env python3
"""Give imported demo leads real property attributes, so they score across A–D.

The contact importer writes eleven columns and nothing else, so a CSV-imported
book of business has no `year_built`, `square_footage`, sale history, storm
exposure or permits — every weighted signal except equity reads NULL and the
whole account grades C/D. This backfills those columns for a demo account and
then scores the rows with the *real* scorer, so the grades on screen are ones
the product actually computed and a later "Rescore all" reproduces them.

How the spread is hit: each lead is assigned a target grade drawn from a
weighted mix, then a single quality parameter q in [0,1] drives every generated
attribute at once (older roof, more equity, recent hail, permit activity …).
The script scans q, scores each candidate through pipeline.scoring against the
row's own regional profile, and keeps the q whose score lands nearest the middle
of the target band. Nothing here reimplements the scoring math — if the weights
or thresholds move, the scan follows them.

Attributes stay internally consistent: `ownership_years` is derived from the
sale date, `last_sale_price` from the value and the years since sale, and
`zip_median_income` is a property of the ZIP rather than of the lead, so two
leads on the same street can't disagree about their neighborhood's income.

Usage:
    # See the achievable distribution without touching the database
    python scripts/enrich_demo_leads.py --dry-run --vertical roofing

    # Enrich the leads a CSV import created for one account
    DATABASE_URL=postgresql://... python scripts/enrich_demo_leads.py --account-id 3

    # Different mix, and include every unscored lead rather than just imports
    python scripts/enrich_demo_leads.py --account-id 3 --mix A:35,B:30,C:22,D:13 --all-leads

One caveat about rescoring afterwards. POST /api/pipeline/rescore-all calls
score_zip(zip, account, vertical=None), so it scores every lead with the DEFAULT
weight profile rather than the lead's own vertical — grades written here (fitted
against the row's vertical, the way a real pipeline run scores it) will move if
you trigger it. Use the per-ZIP POST /api/pipeline/rescore, which does carry the
vertical, or leave the scores this script wrote alone.

Run it AFTER the CSV import. Geocode first (free Census batch) if you want map
pins and neighborhood benchmarks:
    python run_pipeline.py --zip 77396 --account-id 3 --skip \\
        seed,census,hcad,select,property,permits,storm,promote,neighborhood,score,contact,demographics,signals
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import regional                       # noqa: E402
from pipeline.equity import estimate_equity         # noqa: E402
from pipeline.profiles import resolve_profile       # noqa: E402
from pipeline.scoring import compute_score, _grade  # noqa: E402

log = logging.getLogger("enrich_demo_leads")

GRADES = ["A", "B", "C", "D"]
DEFAULT_MIX = {"A": 28, "B": 30, "C": 25, "D": 17}

# Midpoint of each band (config.GRADE_BANDS: A>=75, B>=55, C>=35, D>=0) — the
# score the scan aims at, so a grade doesn't sit on a boundary where a later
# neighborhood recompute could tip it into the next band.
BAND_TARGET = {"A": 85.0, "B": 64.0, "C": 44.0, "D": 22.0}

# ZIP median household income (ACS-shaped, one value per ZIP — a fact about the
# place, not about the lead). Only ZIPs the generator emits need an entry;
# anything else falls back to the county figure.
HARRIS_MEDIAN_INCOME_DEFAULT = 75_000
ZIP_MEDIAN_INCOME = {
    "77005": 250_000, "77024": 224_000, "77401": 165_000, "77056": 118_000,
    "77027": 132_000, "77098": 121_000, "77008": 118_000, "77007": 116_000,
    "77025": 118_000, "77094": 152_000, "77079": 128_000, "77059": 137_000,
    "77345": 133_000, "77339": 108_000, "77389": 139_000, "77433": 127_000,
    "77450": 126_000, "77546": 118_000, "77377": 113_000, "77493": 112_000,
    "77375": 101_000, "77379":  98_000, "77346":  97_000, "77396":  88_000,
    "77388":  84_000, "77070":  83_000, "77095":  92_000, "77065":  82_000,
    "77064":  79_000, "77447":  95_000, "77009":  76_000, "77096":  86_000,
    "77035":  71_000, "77077":  79_000, "77505":  86_000, "77536":  87_000,
    "77532":  81_000, "77062":  92_000, "77058":  85_000, "77338":  62_000,
    "77373":  63_000, "77449":  71_000, "77084":  67_000, "77043":  70_000,
    "77055":  61_000, "77080":  58_000, "77082":  59_000, "77099":  57_000,
    "77089":  70_000, "77034":  59_000, "77504":  64_000, "77571":  71_000,
    "77521":  60_000, "77530":  58_000, "77598":  62_000, "77040":  64_000,
    "77090":  53_000,
}

LIFE_STAGES = ["new_mover", "established", "retiree", "other"]
CREDIT_GRADES = ["A", "B", "C", "D"]
# Non-hail storm types, used when the recorded stone size is too small to call
# the event a hailstorm — a "hurricane" carrying 0.6" hail reads as bad data.
NON_HAIL_STORMS = ["wind", "hurricane", "severe_thunderstorm", "tropical_storm"]
HAIL_MIN_IN = 1.0


def parse_mix(text: str) -> dict[str, int]:
    """Parse 'A:30,B:30,C:25,D:15' into a weight dict, rejecting junk loudly."""
    mix: dict[str, int] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            grade, weight = part.split(":")
        except ValueError:
            raise SystemExit(f"--mix entry must look like A:30, got {part!r}")
        grade = grade.strip().upper()
        if grade not in GRADES:
            raise SystemExit(f"--mix grade must be one of {GRADES}, got {grade!r}")
        mix[grade] = int(weight)
    if not mix or sum(mix.values()) <= 0:
        raise SystemExit("--mix must give at least one grade a positive weight")
    return mix


def pick_targets(rng: random.Random, n: int, mix: dict[str, int]) -> list[str]:
    """Deal out n target grades matching `mix` as closely as n allows.

    Dealt from a shuffled exact-count pool rather than sampled independently, so
    a 250-lead demo lands on the requested shape instead of on a draw from it.
    """
    total = sum(mix.values())
    counts = {g: n * w // total for g, w in mix.items()}
    # Hand out the rounding remainder to the largest fractional parts.
    remainder = n - sum(counts.values())
    order = sorted(mix, key=lambda g: (-(n * mix[g] % total), g))
    for g in order[:remainder]:
        counts[g] += 1
    pool = [g for g, c in counts.items() for _ in range(c)]
    rng.shuffle(pool)
    return pool


# Price per square foot by value band — Harris County runs roughly $115/sqft on
# entry-level suburban stock up to ~$290 inside the Loop, and a flat divisor put
# a $262k Spring home at 1,213 sqft ($216/sqft), which is not a house that
# exists there. (upper bound of value band, $/sqft)
PPSF_BANDS = [
    (200_000, 115), (350_000, 130), (600_000, 165),
    (1_000_000, 215), (float("inf"), 290),
]


def price_per_sqft(value: float) -> int:
    for ceiling, ppsf in PPSF_BANDS:
        if value <= ceiling:
            return ppsf
    return PPSF_BANDS[-1][1]


def house_sqft(row: dict, rng_state: dict) -> int:
    """Conditioned area for this home — a function of its value and nothing else.

    Deliberately NOT driven by the scan. square_footage is one of the three
    inputs to neighborhood_value_ratio (pipeline/neighborhood.py computes
    value-per-sqft against the geohash cell median), so if the fit could move it,
    the benchmark the fit scored against would no longer be the benchmark stored
    on the row — and the product's own "Rescore all", which recomputes the ratio
    first, would return different grades than this script wrote.
    """
    value = row.get("estimated_value") or 300_000
    return int(max(950, min(7500, (value / price_per_sqft(value))
                            * rng_state["sqft_factor"])))


def build_attrs(q: float, t: float, has_pool: bool, row: dict,
                rng_state: dict) -> dict:
    """Generated property attributes at quality `q` and tenure `t` (both 0–1).

    Two axes, not one, because sale recency and equity genuinely pull against
    each other in this scorer: a long-held home has paid its mortgage down and
    scores high on equity while scoring zero on recent-sale, so a single quality
    dial can never produce the weak end of the range — its floor is whichever of
    the two signals it cannot switch off. Tenure is a real, independent property
    of a homeowner anyway, so scanning it separately buys realism as well as
    reach: `t` near 0 is the just-bought owner with nothing paid down, `t` near 1
    the fifteen-year owner sitting on equity.

    `has_pool` is a third axis rather than a draw because pool is a *gate* for
    pool_maintenance: missing it multiplies the whole score by GATE_MISS_FACTOR
    (0.25), a cliff far wider than any grade band, so a lead whose pool flag was
    fixed in advance could be unable to land in the middle bands at all. Whether
    a house has a pool is independent of how good a lead it is anyway.

    `rng_state` holds the per-row random draws, taken once *outside* this
    function so the mapping (q, t, has_pool) -> attributes is deterministic: the
    scan compares candidates that differ only along those axes, not in noise.
    """
    today = date.today()
    n = rng_state
    value = row.get("estimated_value") or 300_000

    # ── Age: newer homes are weak roofing/HVAC leads, ~20 years is the sweet
    # spot. Runs from a 4-year-old build at q=0 to a 26-year-old one at q=1.
    age = 4 + (26 - 4) * q + n["age_jitter"]
    age = max(1, round(age))
    year_built = today.year - age

    # ── Sale recency and tenure ride the t axis. ownership_years is *derived*
    # from the sale date, so a lead card can never say "sold last spring" and
    # "owned fourteen years" at the same time.
    # Capped at the home's own age: the two axes are independent, so without
    # this a q near 0 (new build) and a t near 1 (long tenure) combine into a
    # house sold eight years before it was built — visible on the lead card.
    months_since_sale = max(2, round(3 + t * 197 + n["sale_jitter"]))
    months_since_sale = min(months_since_sale, age * 12)
    last_sale_date = today - timedelta(days=int(months_since_sale * 30.44))
    ownership_years = max(0, int(months_since_sale // 12))

    # ── Equity: derived through the same estimator the pipeline uses, from an
    # implied purchase price. The down payment varies (LTV 0.90 down to 0.35),
    # which is the honest way a recently-sold home can still hold real equity.
    appreciation = 1.0 + 0.045 * (months_since_sale / 12.0)
    ltv = 0.92 - 0.50 * q
    last_sale_price = max(20_000, int(value / appreciation))
    # No estimated_equity_is_fallback in the returned dict on purpose. That flag
    # is set by scorer.score_zip only when it had to *derive* equity for a row
    # that had none; a row this script has already filled never takes that path,
    # so carrying the flag here would score the lead differently than the
    # product's own rescore does.
    equity = estimate_equity(
        value,
        last_sale_price=int(last_sale_price * ltv / 0.8),  # implied original loan
        last_sale_date=last_sale_date,
    )

    # ── Storm / hail / freeze. Every date is *present* and its recency carries
    # the signal, rather than presence being rolled per lead. Two reasons: the
    # Gulf Coast really does take severe weather every year, so "no storm in
    # five years" is the unrealistic state; and a rolled presence puts a cliff
    # in the middle of the scan — storm+hail is 27% of the roofing profile, so
    # flipping it on jumps the score further than the whole B band is wide, and
    # some leads could then never land in B at any q. An event past its recency
    # window scores 0 on its own, which is the same contribution absence gives,
    # without the discontinuity.
    storm_months_ago = max(1, round(4 + (1 - q) * 56 + n["storm_jitter"]))
    last_storm_date = today - timedelta(days=int(storm_months_ago * 30.44))
    hail_size_in = round(0.55 + 1.55 * q + n["hail_jitter"], 2)
    freeze_months_ago = max(1, round(4 + (1 - q) * 58 + n["freeze_jitter"]))
    last_freeze_date = today - timedelta(days=int(freeze_months_ago * 30.44))

    # ── Owner behaviour and demographics.
    permit_count = int(n["permit_roll"] < 0.12 + 0.92 * q) + int(n["permit_roll2"] < 0.80 * q)
    refi_months_ago = max(1, round(3 + (1 - q) * 60 + n["refi_jitter"]))
    refi_date = today - timedelta(days=int(refi_months_ago * 30.44))
    credit_rating = CREDIT_GRADES[min(3, int((1 - q) * 4 + n["credit_jitter"]))]
    life_stage = ("new_mover" if months_since_sale <= 24
                  else "retiree" if n["life_roll"] < 0.22
                  else "established" if n["life_roll"] < 0.85 else "other")

    # ── Structure.
    sqft = house_sqft(row, n)
    # Capped by floor area: a 1,100 sqft house does not have a three-car garage.
    max_spaces = 1 if sqft < 1300 else 2 if sqft < 2400 else 3
    garage_spaces = min(max_spaces,
                        1 + int(n["garage_roll"] < 0.20 + 0.85 * q)
                        + int(n["garage_roll2"] < 0.80 * q))

    return {
        "year_built":           year_built,
        "square_footage":       sqft,
        "garage_spaces":        garage_spaces,
        "last_sale_date":       last_sale_date,
        "last_sale_price":      last_sale_price,
        "ownership_years":      ownership_years,
        "estimated_equity":     equity,
        "zip_median_income":    ZIP_MEDIAN_INCOME.get(row.get("zip"),
                                                      HARRIS_MEDIAN_INCOME_DEFAULT),
        "permit_count_24mo":    permit_count,
        "last_storm_date":      last_storm_date,
        "last_storm_type":      ("hail" if hail_size_in >= HAIL_MIN_IN
                                 else NON_HAIL_STORMS[n["storm_type"]]),
        "storm_count_24mo":     (1 if storm_months_ago <= 24 else 0),
        "hail_size_in":         hail_size_in,
        "last_freeze_date":     last_freeze_date,
        "freeze_count_24mo":    (1 if freeze_months_ago <= 24 else 0),
        "refi_date":            refi_date,
        "credit_rating":        credit_rating,
        "life_stage":           life_stage,
        "owner_occupied":       n["occupancy_roll"] < 0.18 + 0.86 * q,
        "home_improvement_flag": n["hi_roll"] < 0.08 + 0.95 * q,
        "gardening_flag":       n["garden_roll"] < 0.12 + 0.90 * q,
        "has_children":         n["kids_roll"] < 0.15 + 0.70 * q,
        "has_pool":             has_pool,
        "has_cracked_slab":     n["slab_roll"] < 0.06 + 0.95 * q,
        # Carried through from the row so the scorer sees a complete picture.
        "neighborhood_value_ratio": row.get("neighborhood_value_ratio"),
        "estimated_value":      value,
    }


def draw_noise(rng: random.Random) -> dict:
    """One row's random draws, fixed across the whole q scan."""
    return {
        "sqft_factor":    rng.uniform(0.82, 1.22),
        "age_jitter":     rng.uniform(-2.5, 2.5),
        "sale_jitter":    rng.uniform(-8, 8),
        "storm_jitter":   rng.uniform(-3, 3),
        "hail_jitter":    rng.uniform(-0.2, 0.2),
        "freeze_jitter":  rng.uniform(-3, 3),
        "refi_jitter":    rng.uniform(-4, 4),
        "credit_jitter":  rng.uniform(-0.4, 0.4),
        "storm_type":     rng.randrange(len(NON_HAIL_STORMS)),
        "permit_roll":    rng.random(),
        "permit_roll2":   rng.random(),
        "life_roll":      rng.random(),
        "garage_roll":    rng.random(),
        "garage_roll2":   rng.random(),
        "occupancy_roll": rng.random(),
        "hi_roll":        rng.random(),
        "garden_roll":    rng.random(),
        "kids_roll":      rng.random(),
        "slab_roll":      rng.random(),
    }


SCAN_Q_STEPS = 41   # quality resolution
SCAN_T_STEPS = 13   # tenure resolution


def fit_row(row: dict, target: str, profile, rng: random.Random) -> tuple[dict, float, str]:
    """Find the attribute set whose real score lands nearest the target band.

    A grid scan rather than a bisection on purpose: the signals genuinely fight
    each other, so score is monotonic in neither axis and a bisection would
    converge on the wrong side of a local dip.
    """
    noise = draw_noise(rng)
    aim = BAND_TARGET[target]
    best = None
    for i in range(SCAN_Q_STEPS):
        q = i / (SCAN_Q_STEPS - 1)
        for j in range(SCAN_T_STEPS):
            t = j / (SCAN_T_STEPS - 1)
            for has_pool in (False, True):
                attrs = build_attrs(q, t, has_pool, row, noise)
                score = compute_score({**row, **attrs}, profile)
                # Prefer a candidate inside the band; among those, the closest
                # to its midpoint. Outside, minimize distance to the midpoint.
                in_band = _grade(score) == target
                rank = (0 if in_band else 1, abs(score - aim))
                if best is None or rank < best[0]:
                    best = (rank, attrs, score)
    _, attrs, score = best
    return attrs, round(score, 1), _grade(score)


# Coarse grid for the reachability pass — it only needs each row's approximate
# ceiling, not a fitted score, so it runs at a fraction of the full scan's cost.
PROBE_Q_STEPS = 9
PROBE_T_STEPS = 5


def reachable_range(row: dict, profile, rng: random.Random) -> tuple[float, float]:
    """(floor, ceiling) this row can be scored at, over a coarse (q, t, pool) probe.

    Some inputs are fixed before the fit ever runs — the home's value came from
    the CSV, ZIP median income is a fact about the place, and the neighborhood
    ratio was benchmarked against the rows around it. Those three are 25% of the
    landscaping profile's weight, so a modest home on a below-median block
    genuinely cannot be an A lead no matter what else is generated for it.
    """
    noise = draw_noise(rng)
    scores = [
        compute_score({**row, **build_attrs(i / (PROBE_Q_STEPS - 1),
                                            j / (PROBE_T_STEPS - 1),
                                            has_pool, row, noise)}, profile)
        for i in range(PROBE_Q_STEPS)
        for j in range(PROBE_T_STEPS)
        for has_pool in (False, True)
    ]
    return min(scores), max(scores)


def enrich(rows: list[dict], mix: dict[str, int], seed: int,
           vertical_override: str | None) -> list[dict]:
    """Fit every row and return it with attributes, score and grade attached.

    Targets are dealt by reachable range rather than at random, from both ends:
    the A slots go to the rows with the highest ceilings, and the D slots to the
    rows with the lowest floors. Both halves are needed — the two are only loosely
    correlated, so dealing on the ceiling alone hands D to rows that merely cannot
    score *well*, when what a D needs is a row that can score *badly*.

    Dealing at random instead leaves a share of the book targeting a grade its
    fixed inputs put out of range, and the requested mix quietly comes up short.
    It is also the more honest demo — the leads this product would really grade A
    are the valuable homes on strong blocks, so the A list survives being clicked
    into.
    """
    rng = random.Random(seed)
    prepared = []
    for row in rows:
        vertical = vertical_override or row.get("vertical")
        region = regional.resolve_region(row.get("zip"), row.get("state") or "TX")
        profile = resolve_profile(vertical, region)
        key = f"{seed}:{row.get('id') or row.get('address')}"
        floor, ceiling = reachable_range(row, profile, random.Random(key))
        prepared.append({"floor": floor, "ceiling": ceiling, "row": row,
                         "vertical": vertical, "profile": profile,
                         "rng": random.Random(key)})

    counts = {g: 0 for g in GRADES}
    for g in pick_targets(rng, len(rows), mix):
        counts[g] += 1

    # Deal from both ends inward: the highest ceilings take A, the lowest floors
    # take D, and B then C fill the middle by descending ceiling.
    pool = list(prepared)
    assigned: list[tuple[dict, str]] = []
    pool.sort(key=lambda p: -p["ceiling"])
    for item in pool[:counts["A"]]:
        assigned.append((item, "A"))
    pool = pool[counts["A"]:]
    pool.sort(key=lambda p: p["floor"])
    for item in pool[:counts["D"]]:
        assigned.append((item, "D"))
    pool = pool[counts["D"]:]
    pool.sort(key=lambda p: -p["ceiling"])
    for item in pool[:counts["B"]]:
        assigned.append((item, "B"))
    for item in pool[counts["B"]:]:
        assigned.append((item, "C"))

    out = []
    for item, target in assigned:
        attrs, score, grade = fit_row(item["row"], target, item["profile"], item["rng"])
        out.append({**item["row"], **attrs, "vertical": item["vertical"],
                    "lead_score": score, "score_grade": grade, "_target": target})
    return out


# ── Database side ─────────────────────────────────────────────────────────────

# Columns fit_row produces that are real properties columns. estimated_value is
# already set by the import, neighborhood_value_ratio is computed by
# pipeline/neighborhood.py, and estimated_equity_is_fallback is a scoring hint
# rather than a column — none of the three are written here.
WRITE_COLS = [
    "year_built", "square_footage", "garage_spaces", "last_sale_date",
    "last_sale_price", "ownership_years", "estimated_equity", "zip_median_income",
    "permit_count_24mo", "last_storm_date", "last_storm_type", "storm_count_24mo",
    "hail_size_in", "last_freeze_date", "freeze_count_24mo", "refi_date",
    "credit_rating", "life_stage", "owner_occupied", "home_improvement_flag",
    "gardening_flag", "has_children", "has_pool", "has_cracked_slab",
    "vertical", "lead_score", "score_grade",
]

READ_COLS = ["id", "address", "zip", "state", "estimated_value", "vertical",
             "neighborhood_value_ratio", "square_footage", "geohash"]


def fetch_rows(conn, account_id: int, all_leads: bool, limit: int | None) -> list[dict]:
    """The demo account's leads to enrich — CSV imports by default.

    Scoped by account_id like every other tenant query in the codebase. The
    default filter is the import's own provenance stamp
    (enrichment_flags = {"source": "csv_import"}), so this cannot walk over
    pipeline-seeded rows carrying real county data.
    """
    import psycopg2.extras

    where = ["account_id = %s", "archived_at IS NULL"]
    params: list = [account_id]
    if not all_leads:
        where.append("enrichment_flags->>'source' = 'csv_import'")
    sql = (f"SELECT {', '.join(READ_COLS)} FROM properties "
           f"WHERE {' AND '.join(where)} ORDER BY id")
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def write_rows(conn, account_id: int, rows: list[dict], batch: int = 200) -> int:
    """Write the fitted attributes back, scoped by account_id, in batches.

    Batched because the same process serves the API: one statement per batch
    keeps each statement's cost proportional to the batch rather than to the
    account, the same reason api/routes/admin.py batches its deletes.
    """
    assignments = ", ".join(f"{c} = %s" for c in WRITE_COLS)
    sql = (f"UPDATE properties SET {assignments}, score_updated_at = NOW() "
           f"WHERE id = %s AND account_id = %s")
    written = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), batch):
            for row in rows[start:start + batch]:
                cur.execute(sql, [row.get(c) for c in WRITE_COLS]
                            + [row["id"], account_id])
                written += cur.rowcount
            conn.commit()
    return written


def seed_square_footage(conn, account_id: int, rows: list[dict], seed: int) -> int:
    """Write each home's square footage before the benchmark is computed.

    Order matters and this is the whole reason for the extra pass. A freshly
    imported lead has no square_footage, so recompute_neighborhood_values leaves
    its ratio NULL — the metric is value-per-sqft and a row missing either half
    is left unbenchmarked rather than mixed in. Writing footage first means the
    benchmark exists before the fit scores against it, and because footage is a
    function of value alone (see house_sqft) the fit cannot then move it and
    invalidate the ratio it was scored under.
    """
    written = 0
    with conn.cursor() as cur:
        for row in rows:
            noise = draw_noise(random.Random(f"{seed}:{row['id']}"))
            cur.execute(
                "UPDATE properties SET square_footage = %s "
                "WHERE id = %s AND account_id = %s",
                (house_sqft(row, noise), row["id"], account_id),
            )
            written += cur.rowcount
    conn.commit()
    return written


def recompute_neighborhood(conn, account_id: int) -> int:
    """Refresh neighborhood_value_ratio, so the scan scores against the same
    benchmark a later 'Rescore all' recomputes. Rows without coordinates stay
    unbenchmarked (ratio NULL, signal 0) — geocode first if you want the map
    pins and this signal."""
    from pipeline.neighborhood import recompute_neighborhood_values
    return recompute_neighborhood_values(conn, account_id)


# ── Dry run ───────────────────────────────────────────────────────────────────

def rows_from_csv(path: str) -> list[dict]:
    """Read the generator's CSV as scoreable rows, so a dry run measures the
    real file rather than a stand-in for it."""
    import csv
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=1):
            value = r.get("estimated_value", "").replace(",", "").replace("$", "").strip()
            out.append({
                "id": i,
                "address": r.get("address"),
                "zip": r.get("zip"),
                "state": r.get("state") or "TX",
                "estimated_value": int(float(value)) if value else None,
                "vertical": r.get("vertical"),
                "neighborhood_value_ratio": None,
            })
    return out


def synth_rows(n: int, seed: int, vertical: str) -> list[dict]:
    """Stand-in rows when no CSV is given — enough to measure the distribution."""
    rng = random.Random(seed)
    zips = sorted(ZIP_MEDIAN_INCOME)
    return [{"id": i, "address": f"{1000 + i} Demo St", "zip": rng.choice(zips),
             "state": "TX", "estimated_value": rng.randrange(150_000, 900_000, 5_000),
             "vertical": vertical, "neighborhood_value_ratio": None}
            for i in range(1, n + 1)]


def simulate_neighborhood(rows: list[dict], seed: int) -> None:
    """Fill neighborhood_value_ratio in-place for a dry run.

    The real ratio is value-per-sqft against the median of the home's geohash-6
    cell (pipeline/neighborhood.py). A dry run has no coordinates, so ZIP stands
    in for the cell — the same metric over a coarser grouping. Without this the
    ratio is NULL for every row, its signal scores 0, and the report understates
    the reachable A ceiling by the profile's whole neighborhood weight (13.7% of
    landscaping, 9.2% of solar).
    """
    rng = random.Random(seed)
    per_zip: dict[str, list[float]] = {}
    for r in rows:
        noise = draw_noise(random.Random(f"{seed}:{r.get('id') or r.get('address')}"))
        r["_ppsf"] = (r.get("estimated_value") or 300_000) / house_sqft(r, noise)
        per_zip.setdefault(r.get("zip"), []).append(r["_ppsf"])
    medians = {}
    for zip_code, values in per_zip.items():
        values.sort()
        medians[zip_code] = values[len(values) // 2]
    for r in rows:
        median = medians.get(r.get("zip")) or r["_ppsf"]
        r["neighborhood_value_ratio"] = round(r.pop("_ppsf") / median, 4) if median else None


def report(rows: list[dict]) -> None:
    """Print requested vs. achieved grade mix and the score spread."""
    from collections import Counter
    got = Counter(r["score_grade"] for r in rows)
    want = Counter(r["_target"] for r in rows)
    print(f"\n{len(rows)} leads")
    print(f"{'grade':>6} {'wanted':>7} {'got':>6} {'hit':>6}")
    for g in GRADES:
        hit = sum(1 for r in rows if r["_target"] == g and r["score_grade"] == g)
        print(f"{g:>6} {want.get(g, 0):>7} {got.get(g, 0):>6} {hit:>6}")
    scores = sorted(r["lead_score"] for r in rows)
    if scores:
        mid = scores[len(scores) // 2]
        print(f"score  min {scores[0]:.1f}  median {mid:.1f}  max {scores[-1]:.1f}")
    missed = sum(1 for r in rows if r["_target"] != r["score_grade"])
    if missed:
        print(f"note: {missed} lead(s) could not reach their target band — "
              f"the profile's reachable score range is the limit, not the scan")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--account-id", type=int, help="account whose leads to enrich")
    default_mix = ",".join(f"{g}:{w}" for g, w in DEFAULT_MIX.items())
    p.add_argument("--mix", default=default_mix,
                   help=f"target grade mix (default {default_mix})")
    p.add_argument("--vertical", help="force this vertical on every lead")
    p.add_argument("--all-leads", action="store_true",
                   help="enrich every lead, not just rows tagged source=csv_import")
    p.add_argument("--limit", type=int, help="cap how many leads are touched")
    p.add_argument("--seed", type=int, default=20260903, help="RNG seed (reproducible)")
    p.add_argument("--skip-neighborhood", action="store_true",
                   help="don't refresh neighborhood_value_ratio before fitting")
    p.add_argument("--dry-run", action="store_true",
                   help="fit and report the distribution without touching the DB")
    p.add_argument("--from-csv", help="dry-run against this CSV instead of the DB")
    p.add_argument("--rows", type=int, default=250,
                   help="synthetic row count for a dry run with no --from-csv")
    args = p.parse_args()

    mix = parse_mix(args.mix)

    if args.dry_run or args.from_csv:
        rows = (rows_from_csv(args.from_csv) if args.from_csv
                else synth_rows(args.rows, args.seed, args.vertical or "roofing"))
        simulate_neighborhood(rows, args.seed)
        fitted = enrich(rows, mix, args.seed, args.vertical)
        report(fitted)
        print("\ndry run — nothing written")
        return 0

    if not args.account_id:
        p.error("--account-id is required unless --dry-run")

    from pipeline.db import get_conn
    conn = get_conn()
    try:
        rows = fetch_rows(conn, args.account_id, args.all_leads, args.limit)
        if not rows:
            print("No leads matched — did the CSV import run for this account?")
            return 1
        if not args.skip_neighborhood:
            log.info("Seeded square footage on %d lead(s)",
                     seed_square_footage(conn, args.account_id, rows, args.seed))
            log.info("Refreshed neighborhood benchmarks for %d lead(s)",
                     recompute_neighborhood(conn, args.account_id))
            rows = fetch_rows(conn, args.account_id, args.all_leads, args.limit)
        log.info("Fitting %d lead(s)…", len(rows))
        fitted = enrich(rows, mix, args.seed, args.vertical)
        written = write_rows(conn, args.account_id, fitted)
        log.info("Updated %d lead(s)", written)
        report(fitted)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
