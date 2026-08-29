"""
Demo: run sample property records through the scoring engine and print a breakdown.
No database required — uses pipeline.scoring directly.

Usage:
    python tools/score_demo.py
    python tools/score_demo.py --vertical solar
    python tools/score_demo.py --vertical epoxy_flooring
    python tools/score_demo.py --vertical pool_maintenance
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure repo root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from config import DEFAULT_WEIGHTS, VERTICAL_WEIGHTS
from pipeline import regional
from pipeline.profiles import resolve_profile
from pipeline.scoring import compute_score, score_property, _compute_score, _grade
from pipeline.scoring import (
    _age_signal, _sale_signal, _equity_signal,
    _garage_signal, _income_signal, _permit_signal,
)

# ── Sample leads ──────────────────────────────────────────────────────────────

TODAY = date.today()

SAMPLE_LEADS = [
    {
        "_label":           "Prime candidate",
        "address":          "412 Maple Grove Dr",
        "city":             "Marietta", "state": "GA", "zip": "30066",
        "owner_name":       "Robert & Susan Hargrove",
        "year_built":       TODAY.year - 22,        # sweet spot
        "last_sale_date":   TODAY - timedelta(days=180),  # 6 mo ago
        "estimated_equity": 142_000,
        "garage_spaces":    2,
        "zip_median_income": 81_000,
        "permit_count_24mo": 2,
        "square_footage":   2_340,
        "estimated_value":  385_000,
    },
    {
        "_label":           "Good — recent sale, low equity",
        "address":          "89 Whitfield Ln",
        "city":             "Smyrna", "state": "GA", "zip": "30082",
        "owner_name":       "James Calloway",
        "year_built":       TODAY.year - 18,
        "last_sale_date":   TODAY - timedelta(days=60),   # 2 mo ago
        "estimated_equity": 38_000,
        "garage_spaces":    2,
        "zip_median_income": 74_000,
        "permit_count_24mo": 1,
        "square_footage":   1_850,
        "estimated_value":  298_000,
    },
    {
        "_label":           "Older home, strong equity",
        "address":          "2201 Ridgemont Blvd",
        "city":             "Kennesaw", "state": "GA", "zip": "30144",
        "owner_name":       "Patricia Sutton",
        "year_built":       TODAY.year - 44,        # old — decaying signal
        "last_sale_date":   TODAY - timedelta(days=400),  # 13 mo ago
        "estimated_equity": 210_000,
        "garage_spaces":    2,
        "zip_median_income": 69_000,
        "permit_count_24mo": 1,
        "square_footage":   2_800,
        "estimated_value":  510_000,
    },
    {
        "_label":           "Brand new build — poor candidate",
        "address":          "5 Summit Park Ct",
        "city":             "Acworth", "state": "GA", "zip": "30101",
        "owner_name":       "Tyler & Megan Rhodes",
        "year_built":       TODAY.year - 2,         # too new
        "last_sale_date":   TODAY - timedelta(days=30),
        "estimated_equity": 15_000,
        "garage_spaces":    2,
        "zip_median_income": 92_000,
        "permit_count_24mo": 0,
        "square_footage":   2_100,
        "estimated_value":  440_000,
    },
    {
        "_label":           "Stale sale — no recent activity",
        "address":          "770 Creekside Way",
        "city":             "Woodstock", "state": "GA", "zip": "30189",
        "owner_name":       "Frank & Donna Bellamy",
        "year_built":       TODAY.year - 26,
        "last_sale_date":   TODAY - timedelta(days=900),  # 30 mo — dead signal
        "estimated_equity": 88_000,
        "garage_spaces":    1,
        "zip_median_income": 67_000,
        "permit_count_24mo": 0,
        "square_footage":   1_980,
        "estimated_value":  320_000,
    },
    {
        "_label":           "High-income, active permits",
        "address":          "3318 Hearthstone Trl",
        "city":             "Milton", "state": "GA", "zip": "30004",
        "owner_name":       "Charles & Lisa Merritt",
        "year_built":       TODAY.year - 20,
        "last_sale_date":   TODAY - timedelta(days=270),
        "estimated_equity": 95_000,
        "garage_spaces":    3,
        "zip_median_income": 115_000,
        "permit_count_24mo": 3,
        "square_footage":   4_100,
        "estimated_value":  920_000,
    },
    {
        "_label":           "Missing most data",
        "address":          "44 Oak Hill Rd",
        "city":             "Canton", "state": "GA", "zip": "30114",
        "owner_name":       None,
        "year_built":       None,
        "last_sale_date":   None,
        "estimated_equity": None,
        "garage_spaces":    None,
        "zip_median_income": 58_000,
        "permit_count_24mo": None,
        "square_footage":   None,
        "estimated_value":  None,
    },
    {
        "_label":           "Mid-tier — all signals at 50%",
        "address":          "1820 Driftwood Cir",
        "city":             "Roswell", "state": "GA", "zip": "30075",
        "owner_name":       "Angela Torres",
        "year_built":       TODAY.year - 7,         # young → ~47% signal
        "last_sale_date":   TODAY - timedelta(days=365),  # 12 mo → ~50%
        "estimated_equity": 50_000,                 # 50% of target
        "garage_spaces":    1,                      # 50% of target
        "zip_median_income": 37_500,                # 50% of target
        "permit_count_24mo": 1,                     # 50% of target
        "square_footage":   1_650,
        "estimated_value":  270_000,
    },
]

# ── Formatting ────────────────────────────────────────────────────────────────

GRADE_COLORS = {"A": "\033[92m", "B": "\033[94m", "C": "\033[93m", "D": "\033[91m"}
RESET = "\033[0m"
BOLD  = "\033[1m"

def grade_str(grade: str, score: float) -> str:
    color = GRADE_COLORS.get(grade, "")
    return f"{color}{BOLD}{grade}{RESET} {color}{score:5.1f}{RESET}"

def bar(signal: float, width: int = 12) -> str:
    filled = round(max(0.0, min(1.0, signal)) * width)
    return "█" * filled + "░" * (width - filled)

def fmt_date(d) -> str:
    if d is None:
        return "—"
    return str(d)[:10]

# ── Main ──────────────────────────────────────────────────────────────────────

def run(vertical: str | None = None, region: str = regional.NATIONAL) -> None:
    # Resolve through the same registry production uses, so the demo can never
    # print national weights for a market that scores on different ones.
    profile = resolve_profile(vertical, region)
    weights = profile.weights

    header = f"Lead Scoring Demo"
    if vertical:
        header += f"  [vertical: {vertical}]"
    if profile.region != regional.NATIONAL:
        header += f"  [market: {profile.region_label}]"
    print(f"\n{BOLD}{header}{RESET}")
    print("─" * 100)

    col_h = f"{'Address / Label':<38}{'Grade':>7}  {'Age':>5}  {'Sale':>5}  {'Equity':>6}  {'Garage':>6}  {'Income':>6}  {'Permit':>6}  {'Signals'}"
    print(f"{BOLD}{col_h}{RESET}")
    print("─" * 100)

    # The market's own signal functions, not the module-level national ones —
    # a market overrides thresholds as well as weights, and a table showing
    # national signals beside a regional composite would not add up.
    fns = profile.signal_fns

    for lead in SAMPLE_LEADS:
        age_s    = fns["age"](lead.get("year_built"))
        sale_s   = fns["sale"](lead.get("last_sale_date"))
        equity_s = fns["equity"](lead.get("estimated_equity"))
        garage_s = fns["garage"](lead.get("garage_spaces"))
        income_s = fns["income"](lead.get("zip_median_income"))
        permit_s = fns["permit"](lead.get("permit_count_24mo"))

        score = compute_score(lead, profile)
        grade = _grade(score)
        label = lead.get("_label", lead.get("address", "?"))[:37]

        signals = (
            f"age={bar(age_s,6)} "
            f"sale={bar(sale_s,6)} "
            f"eq={bar(equity_s,6)} "
            f"gar={bar(garage_s,4)} "
            f"inc={bar(income_s,6)} "
            f"prm={bar(permit_s,4)}"
        )

        print(
            f"{label:<38}"
            f"{grade_str(grade, score):>18}  "
            f"{age_s:5.2f}  {sale_s:5.2f}  {equity_s:6.2f}  "
            f"{garage_s:6.2f}  {income_s:6.2f}  {permit_s:6.2f}  "
            f"{signals}"
        )

    print("─" * 100)
    print(f"\nWeights used: " + "  ".join(f"{k}={v:.0%}" for k, v in weights.items() if v))
    print(f"Market:       {profile.region_label} ({profile.region})")
    print(f"Grade bands:  A ≥75  B ≥55  C ≥35  D <35\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score sample leads without a database.")
    parser.add_argument("--vertical", choices=list(VERTICAL_WEIGHTS.keys()), default=None,
                        help="Apply vertical-specific weights")
    parser.add_argument("--region", choices=sorted(config.REGIONAL_CALIBRATION_MATRIX),
                        default=regional.NATIONAL,
                        help="Apply a market calibration (see docs/regional_calibration.md)")
    args = parser.parse_args()
    run(args.vertical, args.region)
