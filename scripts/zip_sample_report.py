#!/usr/bin/env python3
"""Test the public ZIP-sample widget across many ZIP codes at once.

The landing page's ``ZipSampleWidget`` (frontend/components/ZipSampleWidget.tsx)
calls ``GET /api/public/zip-sample`` one ZIP at a time. This tool drives that
same endpoint for a whole list of ZIPs and tabulates how many results each
returns — so you can see coverage at a glance instead of typing ZIPs into the
widget by hand.

Two subcommands:

  report     Hit the real endpoint for each ZIP and print a table: status,
             properties scored, grade A / B counts, and how many masked leads
             the widget would show. Read-only — it forces ``PUBLIC_SAMPLE_AUTORUN``
             off so it never queues a pipeline run for an unscored ZIP.

  seed-demo  Populate a demo sample account with synthetic-but-self-consistent
             scored properties across a spread of Harris County ZIPs, so the
             widget (and ``report``) can be exercised locally without real HCAD
             data. Grades are computed by the real scorer, so they match what
             the endpoint recomputes. Idempotent (upsert on the
             (account_id, address, zip) key).

Both need ``DATABASE_URL``. ``report`` also needs the sample account id, taken
from ``--account-id`` or the ``PUBLIC_SAMPLE_ACCOUNT_ID`` env var (the very same
one the running API reads). Point ``DATABASE_URL`` at your real database and
``report`` reads real coverage numbers; there is no seeding involved in
``report``.

Usage:
    # 1. Seed a local demo account and note the account id it prints:
    DATABASE_URL=postgresql://... python scripts/zip_sample_report.py seed-demo

    # 2. Report coverage for the default Harris-County ZIP set:
    DATABASE_URL=postgresql://... PUBLIC_SAMPLE_ACCOUNT_ID=<id> \
        python scripts/zip_sample_report.py report

    # Specific ZIPs, a specific trade, or JSON for scripting:
    ... report 77007 77008 77396 --vertical roofing
    ... report --zips-from-db --json

Note: "properties scored", "grade A" and "grade B" are stored counts and do not
change with ``--vertical``; the trade only re-ranks which leads appear at the
top of the widget's masked list (a roofer and a pool company see the same rows
in a different order).
"""
import argparse
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2

# Standalone-script shim: make the repo root importable so `from config import
# ...` and `from api...` resolve regardless of the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── seed-demo ────────────────────────────────────────────────────────────────
# A spread of real Harris County, TX ZIP codes (the free county data the widget
# covers today) with deliberately different property counts and "temperatures"
# so each ZIP returns a different number of results. The values are synthetic;
# only the ZIPs are real.
#   (zip, city, n_props, temperature 0..1, zip_median_income, typical_value)
DEMO_ZIPS = [
    ("77007", "Houston", 28, 0.72,  95_000,   520_000),  # Heights — hot
    ("77008", "Houston", 22, 0.68,  88_000,   480_000),
    ("77019", "Houston", 16, 0.82, 140_000,   900_000),  # River Oaks — few, premium
    ("77024", "Houston", 20, 0.76, 160_000, 1_100_000),  # Memorial
    ("77025", "Houston", 24, 0.60,  92_000,   560_000),  # West U-ish
    ("77002", "Houston", 12, 0.50,  70_000,   400_000),  # Downtown — few
    ("77396", "Humble",  30, 0.45,  78_000,   320_000),  # suburban — many, cooler
    ("77433", "Cypress", 26, 0.55, 105_000,   380_000),
    ("77045", "Houston", 14, 0.35,  58_000,   240_000),  # cooler
]
# A ZIP the free county mirror covers but nobody has scored yet — exercises the
# widget's "supported but unscored" branch (hcad rows exist, no properties).
DEMO_SUPPORTED_UNSCORED_ZIP = "77571"  # La Porte
# `report` never seeds it, but note it here so the demo docs stay honest: a ZIP
# outside the county mirror (e.g. 90210) reports "unsupported".

_STREETS = [
    "Heights Blvd", "Yale St", "Westheimer Rd", "Bissonnet St", "Kirby Dr",
    "Shepherd Dr", "Ella Blvd", "Airline Dr", "Bingle Rd", "Gessner Rd",
    "Memorial Dr", "Washington Ave", "Bellaire Blvd", "Fry Rd", "Barker Cypress Rd",
]


def _grade_of(score: float) -> str:
    from config import GRADE_BANDS
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return "D"


def _make_row(rng: random.Random, temp: float, income: int, base_value: int) -> dict:
    """Generate one property's scoring fields from a per-ZIP temperature.

    Higher temperature shifts every signal upward (sweet-spot age, recent sale,
    equity, garage, permits), so a hot ZIP yields more A/B grades than a cold
    one. Ranges are keyed to the scorer's targets in config.py so the spread is
    realistic when the real scorer grades it.
    """
    h = min(1.0, max(0.0, rng.gauss(temp, 0.22)))  # this property's heat 0..1
    age = int(round(70 - 50 * h + rng.uniform(-5, 5)))          # hot → sweet spot (~20y)
    age = min(80, max(4, age))
    months_since_sale = int(round((1 - h) * 48 + rng.uniform(-6, 6)))
    months_since_sale = max(0, months_since_sale)
    sale_date = date.today() - timedelta(days=months_since_sale * 30)
    equity = int(max(0, h * 160_000 + rng.uniform(-25_000, 25_000)))
    garage = 3 if h > 0.8 else 2 if h > 0.5 else 1 if h > 0.25 else 0
    permits = rng.randint(1, 3) if h > 0.6 else (1 if h > 0.4 else 0)
    ratio = round(0.9 + h * 0.6 + rng.uniform(-0.05, 0.05), 2)   # ~0.9..1.5
    value = int(base_value * (0.7 + 0.6 * h))
    return {
        "year_built": date.today().year - age,
        "last_sale_date": sale_date,
        "last_sale_price": int(value * rng.uniform(0.6, 0.95)),
        "estimated_value": value,
        "estimated_equity": equity,
        "garage_spaces": garage,
        "zip_median_income": income,
        "neighborhood_value_ratio": ratio,
        "permit_count_24mo": permits,
        "owner_occupied": h > 0.35,
        "ownership_years": max(0, int(months_since_sale / 12)),
    }


def _ensure_demo_account(cur, account_id: int | None) -> int:
    if account_id is not None:
        cur.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
        if not cur.fetchone():
            raise SystemExit(f"Error: account id {account_id} does not exist")
        return account_id
    # Reuse a prior demo account if one is already there, else create one.
    name = "Public ZIP Sample (demo)"
    cur.execute("SELECT id FROM accounts WHERE name = %s ORDER BY id LIMIT 1", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO accounts (name) VALUES (%s) RETURNING id", (name,))
    return cur.fetchone()[0]


def seed_demo(conn, account_id: int | None, seed: int) -> int:
    """Seed synthetic scored properties + a county-mirror row per demo ZIP.

    Returns the account id the data landed in. Reruns refresh scores in place
    (ON CONFLICT DO UPDATE), so it is safe to run repeatedly.
    """
    from pipeline.scoring import score_property
    from config import DEFAULT_WEIGHTS

    rng = random.Random(seed)
    n_props = 0
    with conn.cursor() as cur:
        account_id = _ensure_demo_account(cur, account_id)

        for zipc, city, n, temp, income, base_value in DEMO_ZIPS:
            house_no = 1000
            for _ in range(n):
                house_no += rng.randint(4, 22)
                fields = _make_row(rng, temp, income, base_value)
                score, grade = score_property(fields, DEFAULT_WEIGHTS)
                address = f"{house_no} {rng.choice(_STREETS)}"
                cur.execute(
                    """INSERT INTO properties
                           (account_id, address, city, state, zip, status, vertical,
                            year_built, last_sale_date, last_sale_price,
                            estimated_value, estimated_equity, garage_spaces,
                            zip_median_income, neighborhood_value_ratio,
                            permit_count_24mo, owner_occupied, ownership_years,
                            lead_score, score_grade, score_updated_at)
                       VALUES (%s,%s,%s,'TX',%s,'new','roofing',
                               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                       ON CONFLICT (account_id, address, zip) DO UPDATE SET
                           year_built=EXCLUDED.year_built,
                           last_sale_date=EXCLUDED.last_sale_date,
                           estimated_value=EXCLUDED.estimated_value,
                           estimated_equity=EXCLUDED.estimated_equity,
                           garage_spaces=EXCLUDED.garage_spaces,
                           zip_median_income=EXCLUDED.zip_median_income,
                           neighborhood_value_ratio=EXCLUDED.neighborhood_value_ratio,
                           permit_count_24mo=EXCLUDED.permit_count_24mo,
                           lead_score=EXCLUDED.lead_score,
                           score_grade=EXCLUDED.score_grade,
                           score_updated_at=NOW()""",
                    (account_id, address, city, zipc,
                     fields["year_built"], fields["last_sale_date"],
                     fields["last_sale_price"], fields["estimated_value"],
                     fields["estimated_equity"], fields["garage_spaces"],
                     fields["zip_median_income"], fields["neighborhood_value_ratio"],
                     fields["permit_count_24mo"], fields["owner_occupied"],
                     fields["ownership_years"], round(score, 2), grade),
                )
                n_props += 1
            # County-mirror rows so `_zip_supported` sees the ZIP as covered.
            _seed_hcad(cur, zipc, 3)

        # A covered-but-unscored ZIP: mirror rows only, no scored properties.
        _seed_hcad(cur, DEMO_SUPPORTED_UNSCORED_ZIP, 3)

    conn.commit()
    print(f"✓ account_id={account_id}: seeded {n_props} scored properties "
          f"across {len(DEMO_ZIPS)} ZIPs (+ 1 supported-but-unscored ZIP "
          f"{DEMO_SUPPORTED_UNSCORED_ZIP}).")
    print(f"  Point the API at this account:  export PUBLIC_SAMPLE_ACCOUNT_ID={account_id}")
    return account_id


def _seed_hcad(cur, zipc: str, count: int) -> None:
    """Minimal county-mirror rows (acct PK + site_zip) so the ZIP reads as
    covered. `acct` values are namespaced so they never collide with real data."""
    for i in range(count):
        cur.execute(
            "INSERT INTO hcad_properties (acct, site_zip) VALUES (%s, %s) "
            "ON CONFLICT (acct) DO NOTHING",
            (f"DEMO-{zipc}-{i}", zipc),
        )


# ── report ───────────────────────────────────────────────────────────────────
def _classify(res: dict) -> str:
    if not res.get("configured"):
        return "not-configured"
    if res.get("available"):
        return "available"
    if res.get("queued"):
        return "queued (scoring)"
    if res.get("supported") is False:
        return "unsupported"
    return "supported (unscored)"


def _discover_zips(account_id: int) -> list[str]:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT zip FROM properties WHERE account_id = %s "
                "AND lead_score IS NOT NULL AND zip IS NOT NULL "
                "GROUP BY zip ORDER BY COUNT(*) DESC",
                (account_id,),
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def run_report(zips: list[str], vertical: str | None, as_json: bool) -> None:
    # Force autorun off *before* importing the route module: it binds
    # PUBLIC_SAMPLE_AUTORUN at import time, and a read-only report must never
    # kick off a pipeline run for an unscored ZIP.
    os.environ["PUBLIC_SAMPLE_AUTORUN"] = "false"

    from fastapi import FastAPI  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    from api.routes import zip_sample as zs  # noqa: E402

    # Lift the per-IP browsing cap so a long ZIP list doesn't self-throttle;
    # this is a local test harness, not a public caller.
    zs.zip_sample_limiter.max_calls = 10 ** 9

    app = FastAPI()
    app.include_router(zs.public_router, prefix="/api")
    client = TestClient(app)

    rows = []
    for zipc in zips:
        params = {"zip": zipc}
        if vertical:
            params["vertical"] = vertical
        r = client.get("/api/public/zip-sample", params=params)
        if r.status_code != 200:
            rows.append({"zip": zipc, "status": f"HTTP {r.status_code}",
                         "total": None, "a": None, "b": None, "shown": None,
                         "top": r.json().get("detail", "")[:40] if r.headers.get(
                             "content-type", "").startswith("application/json") else ""})
            continue
        res = r.json()
        leads = res.get("leads") or []
        top = ""
        if leads:
            L = leads[0]
            top = f"{L['grade']} {L['score']:>3} {L['address']}"
        rows.append({
            "zip": zipc,
            "status": _classify(res),
            "total": res.get("total_scored"),
            "a": res.get("grade_a"),
            "b": res.get("grade_b"),
            "shown": len(leads),
            "top": top,
            "_raw": res,
        })

    if as_json:
        print(json.dumps([{k: v for k, v in r.items() if k != "_raw"} for r in rows],
                         indent=2))
        return

    _print_table(rows, vertical)


def _print_table(rows: list[dict], vertical: str | None) -> None:
    def s(v):
        return "" if v is None else str(v)

    headers = ["ZIP", "STATUS", "SCORED", "A", "B", "SHOWN", "TOP LEAD (masked)"]
    keys = ["zip", "status", "total", "a", "b", "shown", "top"]
    data = [[s(r[k]) for k in keys] for r in rows]
    widths = [max(len(headers[i]), *(len(row[i]) for row in data)) if data
              else len(headers[i]) for i in range(len(headers))]
    # Cap the free-text top-lead column.
    widths[-1] = min(widths[-1], 40)

    def fmt(cells):
        return "  ".join(c[:widths[i]].ljust(widths[i]) for i, c in enumerate(cells))

    trade = vertical or "any trade"
    print(f"\nZIP-sample coverage  ·  trade: {trade}  ·  {len(rows)} ZIP(s)")
    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    for row in data:
        print(fmt(row))

    scored = [r for r in rows if r["status"] == "available"]
    total_props = sum(r["total"] or 0 for r in scored)
    print("  ".join("-" * w for w in widths))
    print(f"{len(scored)}/{len(rows)} ZIP(s) return results  ·  "
          f"{total_props:,} properties scored across them")
    print("\nSTATUS legend: available = has scored leads · "
          "supported (unscored) = county data covers it, nothing scored yet · "
          "queued (scoring) = a run is in progress · "
          "unsupported = outside the free county data · "
          "not-configured = PUBLIC_SAMPLE_ACCOUNT_ID unset")


# ── CLI ──────────────────────────────────────────────────────────────────────
def _resolve_account_id(arg_account_id: int | None) -> int:
    if arg_account_id is not None:
        return arg_account_id
    env = os.environ.get("PUBLIC_SAMPLE_ACCOUNT_ID", "").strip()
    if not env:
        raise SystemExit(
            "No sample account: pass --account-id or set PUBLIC_SAMPLE_ACCOUNT_ID "
            "(the same env var the API uses). Run `seed-demo` first for a local "
            "demo account.")
    return int(env)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test the public ZIP-sample widget across many ZIPs at once.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="Tabulate results per ZIP (read-only).")
    p_report.add_argument("zips", nargs="*", help="ZIP codes to test (default: the demo set).")
    p_report.add_argument("--account-id", type=int, default=None,
                          help="Sample account id (default: PUBLIC_SAMPLE_ACCOUNT_ID).")
    p_report.add_argument("--vertical", default=None,
                          help="Trade to rank by (e.g. roofing, hvac). Default: any.")
    p_report.add_argument("--zips-from-db", action="store_true",
                          help="Use every ZIP the sample account has scored.")
    p_report.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")

    p_seed = sub.add_parser("seed-demo", help="Seed a local demo sample account.")
    p_seed.add_argument("--account-id", type=int, default=None,
                        help="Seed into this account id (default: reuse/create a demo account).")
    p_seed.add_argument("--seed", type=int, default=42, help="RNG seed (reproducible data).")

    args = parser.parse_args()

    if "DATABASE_URL" not in os.environ:
        parser.error("DATABASE_URL environment variable is not set")

    if args.command == "seed-demo":
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        try:
            seed_demo(conn, args.account_id, args.seed)
        finally:
            conn.close()
        return

    # report
    account_id = _resolve_account_id(args.account_id)
    # The route reads PUBLIC_SAMPLE_ACCOUNT_ID at import time — set it before
    # the route module is imported inside run_report().
    os.environ["PUBLIC_SAMPLE_ACCOUNT_ID"] = str(account_id)

    if args.zips_from_db:
        zips = _discover_zips(account_id)
        if not zips:
            raise SystemExit(f"account {account_id} has no scored ZIPs to report.")
    elif args.zips:
        zips = args.zips
    else:
        zips = [z[0] for z in DEMO_ZIPS] + [DEMO_SUPPORTED_UNSCORED_ZIP, "90210"]

    run_report(zips, args.vertical, args.json)


if __name__ == "__main__":
    main()
