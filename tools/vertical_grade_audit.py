#!/usr/bin/env python3
"""Audit vertical grade distributions on FREE data — no skip-trace, no demographic append.

Scores a real county export (tools/hcad_export/properties_<zip>.csv plus
permits_<zip>.csv, written by tools/export_hcad_zip.py) through the production
scoring profiles and reports, per vertical × market:

  * which weighted signals read a field only a PAID provider writes
    (pipeline/demographics.py — Versium / BatchData demographic append), and the
    ceiling that leaves on an account that has not bought the append;
  * the hit-rate of every signal on the ZIP — how many rows have the field at
    all, how many score above zero on it, how many saturate it;
  * the A/B/C/D distribution under the current weights next to the same profile
    with the paid-only signals dropped and the remainder rescaled — the exact
    transform pipeline/regional.py::apply_weight_spec performs for scale=0.0, and
    therefore something a region block could ship as-is.

Nothing here re-implements scoring: rows go through pipeline.scoring.compute_score
against the profile pipeline.profiles.resolve_profile returns for the ZIP's
market, so if a weight or threshold moves, the audit follows it.

The export carries the assessor roll only. Signals the roll does not feed
(garage/pool/slab come from HCAD extra-features, storm/hail/freeze from NOAA)
read NULL unless supplied as a scenario flag, and the report labels them so.

Usage:
    python tools/vertical_grade_audit.py --zip 77396
    python tools/vertical_grade_audit.py --zip 77396 --region us
    python tools/vertical_grade_audit.py --zip 77396 --vertical roofing --vertical hvac
    python tools/vertical_grade_audit.py --zip 77396 --garage 2 \
        --storm-months 8 --hail-in 1.75 --freeze-months 20
    python tools/vertical_grade_audit.py --zip 77396 --threshold SALE_RECENCY_MAX_MO=36
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config                                    # noqa: E402  (path set above)
from pipeline import regional, scoring           # noqa: E402
from pipeline.equity import estimate_equity      # noqa: E402
from pipeline.profiles import resolve_profile    # noqa: E402

EXPORT_DIR = ROOT / "tools" / "hcad_export"
ACS_FIXTURES = ROOT / "tests" / "golden" / "fixtures" / "vendor_responses" / "acs"

# Row fields that ONLY pipeline/demographics.py writes. With DEMO_PROVIDER unset
# every one of them is NULL on every row, so a signal reading one is a constant
# zero — weight spent on it is a ceiling cut, not a ranking.
PAID_FIELDS = frozenset({
    "home_improvement_flag", "refi_date", "credit_rating",
    "has_children", "gardening_flag", "life_stage",
})

# Fields the assessor-roll export cannot carry; supplied by scenario flags.
SCENARIO_FIELDS = {
    "garage_spaces":    "--garage",
    "has_pool":         "--pool-share",
    "has_cracked_slab": "(not modelled)",
    "last_storm_date":  "--storm-months",
    "hail_size_in":     "--hail-in",
    "last_freeze_date": "--freeze-months",
}

GRADES = [g for _t, g in config.GRADE_BANDS]


# ── Export parsing ────────────────────────────────────────────────────────────

def _num(value) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _date(value) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _months_ago(today: date, months: int) -> date:
    """Calendar-month subtraction, matching the SQL `INTERVAL n MONTH` the
    permit query uses rather than a 30.44-day approximation."""
    month = today.month - months
    year = today.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, min(today.day, 28))


def fixture_income(zip_code: str) -> int | None:
    """ZIP median income from a golden ACS fixture for the ZIP, if one exists."""
    for path in sorted(ACS_FIXTURES.glob(f"*-{zip_code}.json")):
        try:
            payload = json.loads(path.read_text())
            return int(payload[1][0])
        except (ValueError, IndexError, TypeError, json.JSONDecodeError):
            continue
    return None


def load_permit_counts(zip_code: str, today: date) -> Counter:
    """{acct: permits issued in the last 24 months}, the pipeline's window
    (pipeline/hcad_store.py::query_permits)."""
    path = EXPORT_DIR / f"permits_{zip_code}.csv"
    counts: Counter = Counter()
    if not path.exists():
        return counts
    since = _months_ago(today, 24)
    with path.open(newline="") as fh:
        for rec in csv.DictReader(fh):
            issued = _date(rec.get("issue_date"))
            if issued and since <= issued <= today:
                counts[(rec.get("acct") or "").strip()] += 1
    return counts


def _stable_fraction(key: str) -> float:
    """A stable pseudo-random number in [0, 1) per parcel, so a `--pool-share`
    assignment is reproducible run to run."""
    digest = hashlib.md5(key.encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def build_rows(zip_code: str, today: date, args) -> tuple[list[dict], dict]:
    """The rows as the free pipeline would leave them before scoring.

    Mirrors pipeline/hcad_enrichment.py: equity is the flat fallback from the
    appraised value (Texas is non-disclosure, so there is never a sale price),
    ownership tenure derives from the latest deed date, and permit_count_24mo is
    NULL (not 0) on a parcel with no recent permit — that distinction matters in
    SCORE_MISSING_MODE=renormalize.
    """
    path = EXPORT_DIR / f"properties_{zip_code}.csv"
    if not path.exists():
        sys.exit(f"no export for ZIP {zip_code}: expected {path} "
                 f"(run tools/export_hcad_zip.py {zip_code})")

    permit_counts = load_permit_counts(zip_code, today)
    storm_date = (today - timedelta(days=round(args.storm_months * 30.44))
                  if args.storm_months is not None else None)
    freeze_date = (today - timedelta(days=round(args.freeze_months * 30.44))
                   if args.freeze_months is not None else None)

    rows: list[dict] = []
    total = 0
    with path.open(newline="") as fh:
        for rec in csv.DictReader(fh):
            total += 1
            acct = (rec.get("acct") or "").strip()
            year_built = _num(rec.get("year_built"))
            year_built = int(year_built) if year_built and year_built > 1800 else None
            sqft = _num(rec.get("building_sqft"))
            sqft = sqft if sqft and sqft > 0 else None
            value = _num(rec.get("tot_appr_val"))
            value = value if value and value > 0 else None
            sale = _date(rec.get("last_sale_date"))
            occ = (rec.get("likely_owner_occupied") or "").strip().lower()

            if not args.all_parcels and not (year_built and sqft and value):
                continue

            has_pool = None
            if args.pool_share is not None and _stable_fraction(acct) < args.pool_share:
                # HCAD extra-features only ever write has_pool = TRUE; a parcel
                # with no pool feature stays NULL (pipeline/hcad_enrichment.py).
                has_pool = True

            rows.append({
                "acct":               acct,
                "address":            rec.get("site_address"),
                "zip":                zip_code,
                "state":              "TX",
                "year_built":         year_built,
                "square_footage":     sqft,
                "estimated_value":    value,
                "last_sale_date":     sale,
                "ownership_years":    (today - sale).days // 365 if sale else None,
                "estimated_equity":   estimate_equity(value, last_sale_date=sale),
                "owner_occupied":     True if occ == "true" else False if occ == "false" else None,
                "zip_median_income":  args.income,
                "permit_count_24mo":  permit_counts.get(acct) or None,
                "garage_spaces":      args.garage,
                "has_pool":           has_pool,
                "has_cracked_slab":   None,
                "last_storm_date":    storm_date,
                "hail_size_in":       args.hail_in if storm_date else None,
                "last_freeze_date":   freeze_date,
            })

    # Neighborhood benchmark on its ZIP-median fallback basis
    # (pipeline/neighborhood.py: value-per-sqft ÷ the median of the group).
    vps = [r["estimated_value"] / r["square_footage"] for r in rows
           if r["estimated_value"] and r["square_footage"]]
    median_vps = statistics.median(vps) if vps else None
    for r in rows:
        if median_vps and r["estimated_value"] and r["square_footage"]:
            r["neighborhood_value_ratio"] = (r["estimated_value"] / r["square_footage"]) / median_vps
        else:
            r["neighborhood_value_ratio"] = None

    meta = {"total_parcels": total, "scored": len(rows),
            "recent_permit_parcels": sum(1 for c in permit_counts.values() if c)}
    return rows, meta


# ── Scoring variants ──────────────────────────────────────────────────────────

def paid_signals(profile) -> list[str]:
    return [k for k, w in profile.weights.items()
            if w and profile.factor_meta[k]["field"] in PAID_FIELDS]


def free_ceiling(profile) -> tuple[float, float, float]:
    """(paid-only weight, live weight, ceiling) for a free-only row.

    A gate factor (pipeline/scoring.py::_weighted_sum) contributes no points —
    the engine renormalizes over the non-gate weights — so the scale a profile
    actually ranks on is `live = 1 − Σgates`, and the paid-only share must be
    read against that, not against 1.0.
    """
    gate_weight = sum(profile.weights.get(g, 0.0) for g in profile.gates)
    dead = sum(profile.weights[k] for k in paid_signals(profile))
    live = 1.0 - gate_weight
    ceiling = 100.0 * (live - dead) / live if live > 0 else 0.0
    return dead, live, ceiling


def build_variants(profile, region: str, profile_key: str, overrides: dict,
                   proposal: dict | None = None) -> list[tuple]:
    """[(name, profile)] — the current profile; when it carries paid-only
    signals, the same profile with them dropped and the rest rescaled; and,
    when a proposal was given, the current profile with that {scale, set}
    delta applied (the shape a REGIONAL_CALIBRATION_MATRIX block takes)."""
    fns = profile.signal_fns
    if overrides:
        fns = scoring.build_signal_fns({**regional.thresholds_for(region, profile_key), **overrides})
    base = dataclasses.replace(profile, signal_fns=fns)
    variants = [("current", base)]
    paid = paid_signals(profile)
    if paid:
        weights = regional.apply_weight_spec(profile.weights, {"scale": {k: 0.0 for k in paid}})
        scoring.validate_weights(weights, profile.factor_meta, fns)
        variants.append(("drop_paid", dataclasses.replace(base, weights=weights)))
    if proposal:
        weights = regional.apply_weight_spec(profile.weights, proposal)
        scoring.validate_weights(weights, profile.factor_meta, fns)
        variants.append(("proposal", dataclasses.replace(base, weights=weights)))
    return variants


def score_all(rows: list[dict], profile, missing_mode: str | None = None) -> list[float]:
    saved = config.SCORE_MISSING_MODE
    if missing_mode:
        config.SCORE_MISSING_MODE = missing_mode
    try:
        return [scoring.compute_score(r, profile) for r in rows]
    finally:
        config.SCORE_MISSING_MODE = saved


def summarize(scores: list[float]) -> dict:
    n = len(scores)
    grades = Counter(scoring._grade(s) for s in scores)
    ordered = sorted(scores)
    return {
        "n": n,
        **{g: grades.get(g, 0) for g in GRADES},
        "a_pct": 100.0 * grades.get("A", 0) / n if n else 0.0,
        "p50": ordered[n // 2] if n else 0.0,
        "p90": ordered[int(n * 0.9)] if n else 0.0,
        "max": ordered[-1] if n else 0.0,
    }


# ── Report ────────────────────────────────────────────────────────────────────

def print_hit_rates(rows: list[dict], profile, uniform_fields: set[str]) -> None:
    print(f"  {'signal':16s} {'weight':>6s}  {'field':26s} {'present':>7s} {'>0':>6s} {'sat.':>6s} "
          f"{'mean':>5s} {'pts':>5s}  note")
    n = len(rows)
    for key, weight in profile.weights.items():
        if not weight:
            continue
        field = profile.factor_meta[key]["field"]
        fn = profile.signal_fns[key]
        signals = [fn(r.get(field)) for r in rows]
        present = sum(1 for r in rows if r.get(field) is not None)
        nonzero = sum(1 for s in signals if s > 0)
        saturated = sum(1 for s in signals if s >= 0.999)
        mean = sum(signals) / n if n else 0.0
        if field in PAID_FIELDS:
            note = "PAID-ONLY (demographic append) — constant 0 without a provider"
        elif field in SCENARIO_FIELDS and present == 0:
            note = f"not in export; supply with {SCENARIO_FIELDS[field]}"
        elif field in uniform_fields:
            note = "uniform across the ZIP — shifts every score, ranks nobody"
        else:
            note = ""
        print(f"  {key:16s} {weight:6.3f}  {field:26s} {100*present/n:6.1f}% {100*nonzero/n:5.1f}% "
              f"{100*saturated/n:5.1f}% {mean:5.2f} {100*weight*mean:5.1f}  {note}")


def print_distribution(name: str, s: dict, extra: str = "") -> None:
    print(f"  {name:22s} A {s['A']:6d} ({s['a_pct']:5.1f}%)  B {s['B']:6d}  C {s['C']:6d}  D {s['D']:6d}"
          f"   p50 {s['p50']:5.1f}  p90 {s['p90']:5.1f}  max {s['max']:5.1f}  {extra}")


def run(args) -> None:
    today = date.today()
    zip_code = str(args.zip).strip()
    region = args.region or regional.region_for_zip(zip_code, "TX")
    if args.income is None:
        args.income = fixture_income(zip_code)

    rows, meta = build_rows(zip_code, today, args)
    if not rows:
        sys.exit("no scorable rows")

    uniform = {"zip_median_income"}
    if args.storm_months is not None:
        uniform |= {"last_storm_date", "hail_size_in"}
    if args.freeze_months is not None:
        uniform.add("last_freeze_date")
    if args.garage is not None:
        uniform.add("garage_spaces")

    overrides = {}
    for item in args.threshold or []:
        key, _, value = item.partition("=")
        if key not in scoring.DEFAULT_THRESHOLDS:
            sys.exit(f"unknown threshold {key!r}; choose from {sorted(scoring.DEFAULT_THRESHOLDS)}")
        overrides[key] = float(value)

    print(f"ZIP {zip_code}  market {regional.label(region)} ({region})  as of {today}")
    print(f"  parcels in export {meta['total_parcels']}, scored {meta['scored']}"
          f"{'' if args.all_parcels else ' (dwelling-shaped: year built, floor area and appraised value present)'}"
          f", {meta['recent_permit_parcels']} with a permit in 24 months")
    print(f"  assumptions: zip_median_income={args.income}  garage_spaces={args.garage}  "
          f"pool_share={args.pool_share}  storm_months={args.storm_months}  hail_in={args.hail_in}  "
          f"freeze_months={args.freeze_months}  thresholds={overrides or 'profile defaults'}")
    print(f"  equity is the flat fallback (value × {config.EQUITY_FALLBACK_PCT}) exactly as "
          f"pipeline/hcad_enrichment.py stores it; grade bands "
          + "  ".join(f"{g}≥{t}" for t, g in config.GRADE_BANDS if t))

    proposal: dict = {}
    for item in args.scale or []:
        key, _, value = item.partition("=")
        proposal.setdefault("scale", {})[key] = float(value)
    for item in args.set or []:
        key, _, value = item.partition("=")
        proposal.setdefault("set", {})[key] = float(value)
    if proposal:
        print(f"  proposal delta: {proposal}")

    verticals = args.vertical or ["default", *config.VERTICAL_WEIGHTS]
    for vertical in verticals:
        key = None if vertical == "default" else vertical
        profile = resolve_profile(key, region)
        profile_key = vertical if vertical in config.VERTICAL_WEIGHTS else "default"
        paid = paid_signals(profile)
        dead, live, ceiling = free_ceiling(profile)

        print()
        print(f"── {vertical}  [{profile.region_label}]  paid-only weight {dead:.4f} "
              f"→ free-data ceiling {ceiling:.1f}"
              + (f"  ({', '.join(f'{k}={profile.weights[k]:.3f}' for k in paid)})" if paid else "")
              + (f"  [gate: {', '.join(profile.gates)} — contributes no points]" if profile.gates else ""))
        try:
            variants = build_variants(profile, region, profile_key, overrides, proposal)
        except ValueError as exc:
            # A proposal names a signal this profile does not carry — report
            # and move on, the way apply_weight_spec refuses a silent no-op.
            print(f"  proposal not applicable: {exc}")
            variants = build_variants(profile, region, profile_key, overrides)
        if args.hit_rates:
            print_hit_rates(rows, dataclasses.replace(profile, signal_fns=variants[0][1].signal_fns), uniform)

        results = {}
        for name, prof in variants:
            results[name] = score_all(rows, prof)
            print_distribution(name, summarize(results[name]))
        if "drop_paid" in results:
            # Every paid field is NULL on every row, so dropping the signals and
            # rescaling is a pure multiplication by live/(live − dead): rank
            # order is unchanged; only the labels move. Report the residual
            # from weight rounding as proof.
            scale = live / (live - dead)
            deviation = max(abs(b - a * scale)
                            for a, b in zip(results["current"], results["drop_paid"]))
            print(f"  {'':22s} drop_paid == current × {scale:.4f} (max residual "
                  f"{deviation:.3f} pts) — same ranking, A needs ≥ {75 / scale:.1f} today")
        if "proposal" in results:
            prof = dict(variants)["proposal"]
            print(f"  {'':22s} proposal weights: "
                  + ", ".join(f"{k}={w:.3f}" for k, w in prof.weights.items() if w))
            moved = sum(1 for a, b in zip(results["current"], results["proposal"])
                        if scoring._grade(a) != scoring._grade(b))
            print(f"  {'':22s} proposal changes the grade of {moved} rows ({100 * moved / len(rows):.1f}%)"
                  " — a reweight, so ranking moves too")
        if args.renormalize:
            print_distribution("current@renormalize", summarize(score_all(rows, variants[0][1], "renormalize")),
                               "(SCORE_MISSING_MODE=renormalize — inflates thin rows too)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, help="ZIP with an export under tools/hcad_export/")
    parser.add_argument("--region", choices=sorted(config.REGIONAL_CALIBRATION_MATRIX),
                        help="score in this market instead of the ZIP's own")
    parser.add_argument("--vertical", action="append",
                        choices=["default", *config.VERTICAL_WEIGHTS],
                        help="restrict to these verticals (repeatable; default: all)")
    parser.add_argument("--income", type=int,
                        help="ZIP median household income (default: the golden ACS fixture for the ZIP, if any)")
    parser.add_argument("--garage", type=int, help="assume this many garage spaces on every row")
    parser.add_argument("--pool-share", type=float, help="share of parcels (0–1) to mark has_pool")
    parser.add_argument("--storm-months", type=float, help="a damage storm this many months ago, ZIP-wide")
    parser.add_argument("--hail-in", type=float, help="hail size (inches) for that storm")
    parser.add_argument("--freeze-months", type=float, help="a freeze event this many months ago, ZIP-wide")
    parser.add_argument("--threshold", action="append", metavar="KEY=VALUE",
                        help="override a signal threshold (repeatable), e.g. SALE_RECENCY_MAX_MO=36")
    parser.add_argument("--scale", action="append", metavar="SIGNAL=FACTOR",
                        help="proposal: multiply a weight the profile carries (0 removes it); repeatable")
    parser.add_argument("--set", action="append", metavar="SIGNAL=WEIGHT",
                        help="proposal: pin a signal to an exact share (introduces one the profile lacks); repeatable")
    parser.add_argument("--all-parcels", action="store_true",
                        help="score every parcel, not just dwelling-shaped ones")
    parser.add_argument("--no-hit-rates", dest="hit_rates", action="store_false",
                        help="omit the per-signal hit-rate table")
    parser.add_argument("--renormalize", action="store_true",
                        help="also show SCORE_MISSING_MODE=renormalize for comparison")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
