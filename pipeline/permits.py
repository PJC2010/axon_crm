"""
Step 5 — Permit activity enrichment.

County permit portals vary widely by jurisdiction. This module provides:
  1. A configurable adapter dict (COUNTY_ADAPTERS) for common counties.
  2. A generic CSV import path for jurisdictions that publish bulk exports.
  3. A stub adapter used when no county-specific adapter is registered.

Adding a new county:
  - Implement a function matching the signature:
      def fetch(zip_code: str) -> dict[str, int]  # address → permit_count
  - Register it in COUNTY_ADAPTERS keyed by zip prefix or county FIPS.
"""
import csv
import logging
from pathlib import Path

from pipeline.db import get_conn, fetch_by_zip, upsert_properties

log = logging.getLogger(__name__)


# ── County adapter registry ───────────────────────────────────────────────────
# Map ZIP prefix (first 3 digits) → callable(zip_code) -> {address: count}
COUNTY_ADAPTERS: dict[str, callable] = {}

def register_adapter(zip_prefix: str, fn):
    COUNTY_ADAPTERS[zip_prefix] = fn


# ── Main enrichment function ──────────────────────────────────────────────────

def enrich_permits(zip_code: str, csv_path: str | None = None) -> int:
    conn = get_conn()

    if csv_path:
        permit_map = _load_csv(csv_path, zip_code)
    else:
        adapter = COUNTY_ADAPTERS.get(zip_code[:3])
        if adapter:
            permit_map = adapter(zip_code)
        else:
            log.warning(
                "No permit adapter for ZIP %s — permit_count_24mo will remain NULL. "
                "Provide a CSV export or implement a county adapter.",
                zip_code,
            )
            conn.close()
            return 0

    if not permit_map:
        conn.close()
        return 0

    rows = fetch_by_zip(conn, zip_code)
    updates = []
    for row in rows:
        addr = row["address"].lower()
        count = permit_map.get(addr)
        if count is not None:
            updates.append({
                "address":          row["address"],
                "zip":              zip_code,
                "permit_count_24mo": count,
                "enrichment_flags": {"permits": "county"},
            })

    n = upsert_properties(conn, updates)
    conn.close()
    log.info("Updated permit counts for %d properties in ZIP %s", n, zip_code)
    return n


# ── CSV import ────────────────────────────────────────────────────────────────

def _load_csv(csv_path: str, zip_code: str) -> dict[str, int]:
    """
    Load permit counts from a county CSV export.
    Expected columns: address, zip, permit_count  (case-insensitive).
    Returns {normalized_address: count}.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(csv_path)

    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = {h.lower().strip() for h in reader.fieldnames or []}
        count_col = next(
            (h for h in ["permit_count", "permits", "permit_count_24mo"] if h in headers),
            None
        )
        if not count_col:
            log.error("CSV %s missing a permit count column", csv_path)
            return {}
        for row in reader:
            r = {k.lower().strip(): v for k, v in row.items()}
            if r.get("zip") != zip_code:
                continue
            addr = r.get("address", "").lower()
            try:
                result[addr] = int(r[count_col])
            except (ValueError, KeyError):
                pass
    return result
