"""
Per-field coverage reporting — shows which lead columns are well-populated for a
ZIP and which are weak. Used to measure enrichment before/after a run.

  python -m pipeline.coverage --zip 77002

Also called by the pipeline runner to embed a `coverage` block in
pipeline_runs.result_json so the frontend can surface weak columns.
"""
import argparse

import psycopg2.extras

from pipeline.db import get_conn

# Columns whose fill rate is worth tracking (data the enrichment pipeline owns).
TRACKED_FIELDS = [
    "latitude", "longitude", "year_built", "square_footage", "garage_spaces",
    "garage_type", "lot_size", "property_type", "estimated_value",
    "estimated_equity", "last_sale_date", "last_sale_price", "owner_name",
    "owner_occupied", "ownership_years", "zip_median_income", "permit_count_24mo",
    "has_pool", "has_cracked_slab", "contact_name", "contact_phone",
    "contact_email", "lead_score",
]


def compute_fill_rates(rows: list[dict], fields: list[str] | None = None) -> dict:
    """Pure: given row dicts, return {field: {filled, total, pct}}. Testable."""
    fields = fields or TRACKED_FIELDS
    total = len(rows)
    out = {}
    for f in fields:
        filled = sum(1 for r in rows if r.get(f) is not None)
        pct = round(100 * filled / total, 1) if total else 0.0
        out[f] = {"filled": filled, "total": total, "pct": pct}
    return out


def fill_rates(conn, zip_code: str, fields: list[str] | None = None) -> dict:
    """Compute fill rates for `zip_code` straight from the DB."""
    fields = fields or TRACKED_FIELDS
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM properties WHERE zip = %s", (zip_code,))
        rows = [dict(r) for r in cur.fetchall()]
    return compute_fill_rates(rows, fields)


def _print_table(zip_code: str, rates: dict) -> None:
    total = next(iter(rates.values()), {}).get("total", 0)
    print(f"\nCoverage for ZIP {zip_code} — {total} properties\n")
    print(f"  {'field':22}  {'filled':>7}  {'pct':>6}")
    print(f"  {'-' * 22}  {'-' * 7}  {'-' * 6}")
    for field, r in sorted(rates.items(), key=lambda kv: kv[1]["pct"]):
        print(f"  {field:22}  {r['filled']:>7}  {r['pct']:>5}%")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-field coverage for a ZIP")
    ap.add_argument("--zip", required=True)
    args = ap.parse_args()
    conn = get_conn()
    try:
        rates = fill_rates(conn, args.zip)
    finally:
        conn.close()
    _print_table(args.zip, rates)


if __name__ == "__main__":
    main()
