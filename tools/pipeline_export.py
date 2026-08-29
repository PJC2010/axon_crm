#!/usr/bin/env python3
"""
Pipeline test & export tool.

Loads enriched properties (from DB or sample data), re-runs scoring, and
exports a detailed CSV with per-signal breakdowns for every lead.

Modes
-----
  Live DB (default):
    python tools/pipeline_export.py --zip 77008
    python tools/pipeline_export.py --zip 77008 --vertical epoxy_flooring
    python tools/pipeline_export.py --zip 77008 --account-id 2 --out results.csv

  No-DB dry run (sample data, no database required):
    python tools/pipeline_export.py --dry-run
    python tools/pipeline_export.py --dry-run --vertical solar

Output columns
--------------
  address, city, state, zip, owner_name
  year_built, estimated_value, estimated_equity, last_sale_date
  garage_spaces, zip_median_income, permit_count_24mo
  has_pool, has_cracked_slab, neighborhood_value_ratio, neighborhood_value_basis
  contact_name, contact_phone, contact_email
  sig_age, sig_sale, sig_equity, sig_garage, sig_income,
  sig_permit, sig_neighborhood, sig_pool, sig_slab
  lead_score, score_grade, top_drivers
  [one column per factor: factor_<key>_contribution]
  null_fields  (comma-list of blank input fields)
"""
import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from pipeline import regional
from pipeline.profiles import resolve_profile
from pipeline.scoring import explain_score


# ── Signal helpers ─────────────────────────────────────────────────────────────

# The columns the per-signal table and CSV report, in display order. The
# functions come from the resolved profile rather than being bound here: a
# market overrides signal THRESHOLDS as well as weights, so a hardcoded map
# would print national signals beside a regional composite.
REPORTED_SIGNALS = ["age", "sale", "equity", "garage", "income", "permit",
                    "neighborhood", "pool", "slab"]


def _signal_map(profile) -> dict:
    """{key: (fn, row field)} for the signals this export reports."""
    return {key: (profile.signal_fns[key], profile.factor_meta[key]["field"])
            for key in REPORTED_SIGNALS}

_INPUT_FIELDS = [
    "address", "city", "state", "zip", "owner_name",
    "year_built", "square_footage", "estimated_value", "estimated_equity",
    "last_sale_date", "garage_spaces", "zip_median_income", "permit_count_24mo",
    "has_pool", "has_cracked_slab", "neighborhood_value_ratio",
    "neighborhood_value_basis", "contact_name", "contact_phone", "contact_email",
]


# ── Sample data (no-DB mode) ───────────────────────────────────────────────────

TODAY = date.today()

SAMPLE_LEADS = [
    {
        "address": "412 Maple Grove Dr", "city": "Marietta", "state": "GA", "zip": "30066",
        "owner_name": "Robert & Susan Hargrove",
        "year_built": TODAY.year - 22,
        "square_footage": 2340, "estimated_value": 385_000,
        "estimated_equity": 142_000,
        "last_sale_date": TODAY - timedelta(days=180),
        "garage_spaces": 2, "zip_median_income": 81_000, "permit_count_24mo": 2,
        "has_pool": False, "has_cracked_slab": False,
        "neighborhood_value_ratio": 1.25, "neighborhood_value_basis": "cell",
        "contact_name": None, "contact_phone": None, "contact_email": None,
    },
    {
        "address": "89 Whitfield Ln", "city": "Smyrna", "state": "GA", "zip": "30082",
        "owner_name": "James Calloway",
        "year_built": TODAY.year - 18,
        "square_footage": 1850, "estimated_value": 298_000,
        "estimated_equity": 38_000,
        "last_sale_date": TODAY - timedelta(days=60),
        "garage_spaces": 2, "zip_median_income": 74_000, "permit_count_24mo": 1,
        "has_pool": False, "has_cracked_slab": False,
        "neighborhood_value_ratio": 1.05, "neighborhood_value_basis": "cell",
        "contact_name": None, "contact_phone": None, "contact_email": None,
    },
    {
        "address": "2201 Ridgemont Blvd", "city": "Kennesaw", "state": "GA", "zip": "30144",
        "owner_name": "Patricia Sutton",
        "year_built": TODAY.year - 44,
        "square_footage": 2800, "estimated_value": 510_000,
        "estimated_equity": 210_000,
        "last_sale_date": TODAY - timedelta(days=400),
        "garage_spaces": 2, "zip_median_income": 69_000, "permit_count_24mo": 1,
        "has_pool": True, "has_cracked_slab": False,
        "neighborhood_value_ratio": 1.4, "neighborhood_value_basis": "cell",
        "contact_name": None, "contact_phone": None, "contact_email": None,
    },
    {
        "address": "5 Summit Park Ct", "city": "Acworth", "state": "GA", "zip": "30101",
        "owner_name": "Tyler & Megan Rhodes",
        "year_built": TODAY.year - 2,
        "square_footage": 2100, "estimated_value": 440_000,
        "estimated_equity": 15_000,
        "last_sale_date": TODAY - timedelta(days=30),
        "garage_spaces": 2, "zip_median_income": 92_000, "permit_count_24mo": 0,
        "has_pool": False, "has_cracked_slab": False,
        "neighborhood_value_ratio": 0.95, "neighborhood_value_basis": "cell",
        "contact_name": None, "contact_phone": None, "contact_email": None,
    },
    {
        "address": "770 Creekside Way", "city": "Woodstock", "state": "GA", "zip": "30189",
        "owner_name": "Frank & Donna Bellamy",
        "year_built": TODAY.year - 26,
        "square_footage": 1980, "estimated_value": 320_000,
        "estimated_equity": 88_000,
        "last_sale_date": TODAY - timedelta(days=900),
        "garage_spaces": 1, "zip_median_income": 67_000, "permit_count_24mo": 0,
        "has_pool": False, "has_cracked_slab": True,
        "neighborhood_value_ratio": 1.1, "neighborhood_value_basis": "zip",
        "contact_name": None, "contact_phone": None, "contact_email": None,
    },
    {
        "address": "3318 Hearthstone Trl", "city": "Milton", "state": "GA", "zip": "30004",
        "owner_name": "Charles & Lisa Merritt",
        "year_built": TODAY.year - 20,
        "square_footage": 4100, "estimated_value": 920_000,
        "estimated_equity": 95_000,
        "last_sale_date": TODAY - timedelta(days=270),
        "garage_spaces": 3, "zip_median_income": 115_000, "permit_count_24mo": 3,
        "has_pool": True, "has_cracked_slab": False,
        "neighborhood_value_ratio": 1.5, "neighborhood_value_basis": "cell",
        "contact_name": None, "contact_phone": None, "contact_email": None,
    },
    {
        "address": "44 Oak Hill Rd", "city": "Canton", "state": "GA", "zip": "30114",
        "owner_name": None,
        "year_built": None, "square_footage": None, "estimated_value": None,
        "estimated_equity": None, "last_sale_date": None,
        "garage_spaces": None, "zip_median_income": 58_000, "permit_count_24mo": None,
        "has_pool": None, "has_cracked_slab": None,
        "neighborhood_value_ratio": None, "neighborhood_value_basis": None,
        "contact_name": None, "contact_phone": None, "contact_email": None,
    },
]


# ── DB loader ──────────────────────────────────────────────────────────────────

def load_from_db(zip_code: str, account_id: int) -> list[dict]:
    from pipeline.db import get_conn
    conn = get_conn()
    cols = ", ".join(_INPUT_FIELDS + ["lead_score", "score_grade", "vertical"])
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {cols} FROM properties "
            f"WHERE zip = %s AND account_id = %s "
            f"ORDER BY lead_score DESC NULLS LAST",
            (zip_code, account_id),
        )
        rows = cur.fetchall()
        col_names = [_INPUT_FIELDS + ["lead_score", "score_grade", "vertical"]][0] + \
                    ["lead_score", "score_grade", "vertical"]
        col_names = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(col_names, row)) for row in rows]


# ── Core scoring & export ──────────────────────────────────────────────────────

GRADE_COLORS = {"A": "\033[92m", "B": "\033[94m", "C": "\033[93m", "D": "\033[91m"}
RESET = "\033[0m"
BOLD  = "\033[1m"


def _null_fields(row: dict, signal_fns: dict) -> str:
    signal_inputs = {field for _, field in signal_fns.values()}
    blanks = [f for f in signal_inputs if row.get(f) is None]
    return ",".join(sorted(blanks))


def _bar(signal: float, width: int = 8) -> str:
    filled = round(max(0.0, min(1.0, signal)) * width)
    return "█" * filled + "░" * (width - filled)


def score_and_export(rows: list[dict], profile, out_path: str | None, vertical: str | None) -> None:
    weights = profile.weights
    all_keys = list(weights.keys())
    signal_fns = _signal_map(profile)
    csv_rows = []

    print(f"\n{BOLD}{'Address':<38} {'Grade':>6} {'Score':>6}  {'Age':>5} {'Sale':>5} {'Equity':>6} {'Garage':>6} {'Income':>6} {'Permit':>6} {'Nbhd':>5}  Nulls{RESET}")
    print("─" * 110)

    for row in rows:
        explained = explain_score(row, weights, profile=profile)
        score     = explained["score"]
        grade     = explained["grade"]
        factors   = {f["key"]: f for f in explained["factors"]}

        def sig(key):
            fn, field = signal_fns[key]
            return fn(row.get(field))

        color = GRADE_COLORS.get(grade, "")
        nulls = _null_fields(row, signal_fns)
        addr  = str(row.get("address", ""))[:37]

        print(
            f"{addr:<38} "
            f"{color}{BOLD}{grade}{RESET} {color}{score:5.1f}{RESET}  "
            f"{sig('age'):5.2f} "
            f"{sig('sale'):5.2f} "
            f"{sig('equity'):6.2f} "
            f"{sig('garage'):6.2f} "
            f"{sig('income'):6.2f} "
            f"{sig('permit'):6.2f} "
            f"{sig('neighborhood'):5.2f}  "
            f"{nulls or '—'}"
        )

        csv_row = {f: row.get(f, "") for f in _INPUT_FIELDS}
        csv_row["lead_score"]  = round(score, 2)
        csv_row["score_grade"] = grade
        csv_row["top_drivers"] = ",".join(explained["top_drivers"])
        csv_row["null_fields"] = nulls

        for key in REPORTED_SIGNALS:
            fn, field = signal_fns[key]
            csv_row[f"sig_{key}"] = round(fn(row.get(field)), 4)

        for key in all_keys:
            csv_row[f"factor_{key}_contribution"] = factors[key]["contribution"] if key in factors else 0.0

        csv_rows.append(csv_row)

    print("─" * 110)
    print(f"\n{len(rows)} properties scored.")
    if vertical:
        print(f"Vertical: {vertical}")
    print(f"Weights: " + "  ".join(f"{k}={v:.0%}" for k, v in weights.items() if v))
    print(f"Market:  {profile.region_label} ({profile.region})")
    print(f"Grades:  A ≥75  B ≥55  C ≥35  D <35\n")

    if not out_path:
        return

    sig_cols  = [f"sig_{k}" for k in REPORTED_SIGNALS]
    cont_cols = [f"factor_{k}_contribution" for k in all_keys]
    fieldnames = _INPUT_FIELDS + ["lead_score", "score_grade", "top_drivers"] + sig_cols + cont_cols + ["null_fields"]

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Exported {len(csv_rows)} rows → {out_path}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score pipeline properties and export to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--zip",        help="ZIP code to load from DB (e.g. 77008)")
    parser.add_argument("--account-id", type=int, default=1, dest="account_id",
                        help="Account/org ID (default: 1)")
    parser.add_argument("--vertical",   choices=list(config.VERTICAL_WEIGHTS.keys()), default=None,
                        help="Apply vertical-specific weights")
    parser.add_argument("--out",        default=None,
                        help="CSV output path (default: pipeline_export_<zip>.csv)")
    parser.add_argument("--region",     choices=sorted(config.REGIONAL_CALIBRATION_MATRIX),
                        default=None,
                        help="Force a market calibration; default is derived from --zip "
                             "(see docs/regional_calibration.md)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Use built-in sample data instead of a database connection")
    args = parser.parse_args()

    if not args.dry_run and not args.zip:
        parser.error("Provide --zip <code> to load from DB, or use --dry-run for sample data.")

    # --dry-run has no ZIP to derive a market from, so it scores nationally
    # unless --region says otherwise.
    region = args.region or regional.resolve_region(args.zip)
    profile = resolve_profile(args.vertical, region)

    if args.dry_run:
        rows    = SAMPLE_LEADS
        out     = args.out or "pipeline_export_sample.csv"
        label   = "sample data"
    else:
        rows    = load_from_db(args.zip, args.account_id)
        out     = args.out or f"pipeline_export_{args.zip}.csv"
        label   = f"ZIP {args.zip} / account {args.account_id}"

    if not rows:
        print(f"No properties found for {label}.")
        sys.exit(0)

    print(f"\nLoaded {len(rows)} properties from {label}.")
    score_and_export(rows, profile, out, args.vertical)


if __name__ == "__main__":
    main()
