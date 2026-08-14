#!/usr/bin/env python3
"""
Bulk-load Harris County parcel centroids from the county's public ArcGIS
parcels layer into the Postgres `hcad_parcel_centroids` mirror.

hcad_properties carries no coordinates; this mirror is the free geocoding
source that fills the gap: ~1.53M WGS84 centroids keyed by the same 13-digit
HCAD account, pulled in ~770 keyset-paginated requests — no API key, no quota.
Accounts are stored pre-normalized by pipeline/parcel_id.py::sql_normalize_apn,
the same expression that writes parcels.parcel_apn, so the cache fill
(pipeline/parcels.py::fill_coords_from_centroids) is plain equality.

The download spools to a local CSV with a checkpoint, so an interrupted run
resumes where it left off (Ctrl-C is safe; just rerun). The DB load is a
single atomic TRUNCATE + reload — the slow network phase never holds a lock —
and rerunning end-to-end changes nothing.

Prerequisites: run migrations on the target DB first (`python db/migrate.py`).

Usage:
    # Loads into DATABASE_URL by default:
    python tools/load_parcel_centroids.py

    # Explicit target (use Render's EXTERNAL database URL from your machine):
    python tools/load_parcel_centroids.py --dsn "postgresql://user:pass@host/db"

    # Interrupted? Just rerun — it resumes. --fresh discards the spool instead.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import HCAD_PARCELS_ARCGIS_URL  # noqa: E402
from pipeline.http import get_json  # noqa: E402
from pipeline.parcel_centroids import (  # noqa: E402
    ARCGIS_PAGE_SIZE, ArcGISError, count_params, parse_count, parse_page,
    query_params,
)
from pipeline.parcel_id import sql_normalize_apn  # noqa: E402

PROGRESS_EVERY = 25   # pages between progress lines (~50k rows)


def _pg_table_exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (table,))
    return cur.fetchone()[0] is not None


def _query_parsed(url: str, params: dict, parser):
    """One request through the shared retry/backoff helper, parsed or fatal.

    Both failure modes end the run with the checkpoint intact — an incomplete
    mirror must never look complete — and a rerun resumes the download.
    """
    data = get_json(url.rstrip("/") + "/query", params=params, timeout=60)
    if data is None:
        sys.exit("error: ArcGIS request failed after retries (network or "
                 "service outage). Checkpoint kept — rerun to resume.")
    try:
        return parser(data)
    except ArcGISError as e:
        sys.exit(f"error: ArcGIS answered with a problem: {e}. "
                 f"Checkpoint kept — rerun to resume.")


def _write_checkpoint(path: Path, ckpt: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ckpt))
    os.replace(tmp, path)   # atomic: a kill mid-write cannot corrupt it


def download(url: str, workdir: Path, page_size: int, fresh: bool,
             max_pages: int | None) -> tuple[Path, dict]:
    """Page the whole layer into workdir/spool.csv, checkpointed for resume."""
    workdir.mkdir(parents=True, exist_ok=True)
    spool, ckpt_path = workdir / "spool.csv", workdir / "checkpoint.json"

    ckpt = None
    if not fresh and ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text())
        if ckpt.get("url") != url or ckpt.get("page_size") != page_size:
            sys.exit(f"error: {ckpt_path} was written for a different URL or "
                     f"page size — rerun with --fresh to restart the download.")
        if ckpt.get("done"):
            print(f"Download already complete ({ckpt['rows']:,} rows spooled) "
                  f"— skipping to load. Use --fresh to re-download.",
                  flush=True)
            return spool, ckpt
    if ckpt is None:
        for stale in (spool, ckpt_path):
            if stale.exists():
                stale.unlink()
        ckpt = {"url": url, "page_size": page_size, "last_objectid": 0,
                "rows": 0, "pages": 0, "no_acct": 0, "no_centroid": 0,
                "done": False}
        with spool.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(["objectid", "acct_raw", "lon", "lat"])

    ckpt["server_total"] = _query_parsed(url, count_params(), parse_count)
    print(f"ArcGIS layer reports {ckpt['server_total']:,} features "
          f"(resuming after OBJECTID {ckpt['last_objectid']:,}; "
          f"{ckpt['rows']:,} rows already spooled)", flush=True)

    pages_this_run = 0
    while True:
        if max_pages is not None and pages_this_run >= max_pages:
            print(f"--max-pages {max_pages} reached; download incomplete — "
                  f"rerun to continue.", flush=True)
            break
        rows, meta = _query_parsed(
            url, query_params(ckpt["last_objectid"], page_size), parse_page)
        if meta["features"] == 0:
            ckpt["done"] = True
            _write_checkpoint(ckpt_path, ckpt)
            break
        with spool.open("a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        ckpt["last_objectid"] = meta["last_objectid"]
        ckpt["rows"] += len(rows)
        ckpt["pages"] += 1
        ckpt["no_acct"] += meta["no_acct"]
        ckpt["no_centroid"] += meta["no_centroid"]
        _write_checkpoint(ckpt_path, ckpt)
        pages_this_run += 1
        if ckpt["pages"] % PROGRESS_EVERY == 0:
            print(f"  page {ckpt['pages']}: {ckpt['rows']:,} rows spooled "
                  f"(last OBJECTID {ckpt['last_objectid']:,})", flush=True)

    print(f"Spooled {ckpt['rows']:,} rows over {ckpt['pages']} page(s); "
          f"skipped {ckpt['no_acct']:,} without an account and "
          f"{ckpt['no_centroid']:,} without a centroid.", flush=True)
    return spool, ckpt


def load(dsn: str, spool: Path, ckpt: dict) -> None:
    """Atomic TRUNCATE + reload of hcad_parcel_centroids from the spool."""
    if not spool.exists():
        sys.exit(f"error: no spool at {spool} — run the download first "
                 f"(drop --load-only).")
    if not ckpt.get("done"):
        print("WARNING: the download is incomplete — loading a PARTIAL mirror. "
              "Rerun without --max-pages to finish, then load again.",
              flush=True)

    pg = psycopg2.connect(dsn)
    try:
        with pg.cursor() as cur:
            if not _pg_table_exists(cur, "hcad_parcel_centroids"):
                sys.exit("error: target table hcad_parcel_centroids is missing "
                         "— run `python db/migrate.py` against this database "
                         "first.")
            # Stage first: the slow COPY targets a temp table, so the ACCESS
            # EXCLUSIVE lock TRUNCATE takes is held only for the fast INSERT.
            print("Staging spool ...", flush=True)
            cur.execute(
                "CREATE TEMP TABLE _centroid_stage ("
                "objectid BIGINT, acct_raw TEXT, "
                "lon DOUBLE PRECISION, lat DOUBLE PRECISION)"
            )
            with spool.open("r", encoding="utf-8") as fh:
                cur.copy_expert(
                    "COPY _centroid_stage (objectid, acct_raw, lon, lat) "
                    "FROM STDIN WITH (FORMAT CSV, HEADER TRUE)", fh)
            cur.execute("SELECT COUNT(*) FROM _centroid_stage")
            staged = cur.fetchone()[0]

            print("Loading hcad_parcel_centroids ...", flush=True)
            cur.execute("TRUNCATE hcad_parcel_centroids")
            # Normalize with the SAME expression that writes parcels.parcel_apn
            # (that shared rule is what makes the fill join exact); keep-first
            # by OBJECTID makes the rare duplicate account deterministic. The
            # migration's CHECK constraints re-validate every coordinate here.
            cur.execute(f"""
                INSERT INTO hcad_parcel_centroids (acct, latitude, longitude)
                SELECT DISTINCT ON (norm) norm, lat, lon
                FROM (SELECT {sql_normalize_apn('acct_raw')} AS norm,
                             lat, lon, objectid
                      FROM _centroid_stage) s
                WHERE norm IS NOT NULL
                ORDER BY norm, objectid
                """)
            inserted = cur.rowcount
            cur.execute("ANALYZE hcad_parcel_centroids")
        pg.commit()   # one transaction: the TRUNCATE never lands without its reload

        with pg.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM hcad_properties")
            hcad_total = cur.fetchone()[0]
            overlap = None
            if hcad_total:
                cur.execute(f"""
                    SELECT COUNT(*) FROM hcad_properties h
                    WHERE EXISTS (SELECT 1 FROM hcad_parcel_centroids c
                                  WHERE c.acct = {sql_normalize_apn('h.acct')})
                    """)
                overlap = cur.fetchone()[0]
    finally:
        pg.close()

    print("\nCount parity:", flush=True)
    if ckpt.get("server_total") is not None:
        print(f"  ArcGIS server count:      {ckpt['server_total']:>12,}",
              flush=True)
    print(f"  spooled rows:             {ckpt.get('rows', staged):>12,}   "
          f"(skipped: {ckpt.get('no_acct', 0):,} no account, "
          f"{ckpt.get('no_centroid', 0):,} no centroid)", flush=True)
    print(f"  staged rows:              {staged:>12,}", flush=True)
    print(f"  inserted (unique accts):  {inserted:>12,}   "
          f"(dedupe/all-zero dropped {staged - inserted:,})", flush=True)
    print(f"  hcad_properties rows:     {hcad_total:>12,}", flush=True)
    if overlap is not None:
        print(f"  hcad accts with centroid: {overlap:>12,}   "
              f"({overlap / hcad_total * 100:.1f}%)", flush=True)
    else:
        print("  hcad_properties is empty — load it "
              "(tools/load_hcad_to_postgres.py) and rerun for overlap parity.",
              flush=True)
    print("\nDone. Next: python tools/build_parcel_cache.py", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Load Harris County parcel centroids (ArcGIS) into Postgres")
    p.add_argument("--dsn", default=os.getenv("DATABASE_URL"),
                   help="Target Postgres DSN (default: $DATABASE_URL). Use "
                        "Render's EXTERNAL database URL from your machine.")
    p.add_argument("--url", default=HCAD_PARCELS_ARCGIS_URL,
                   help="ArcGIS FeatureServer layer URL "
                        "(default: config.HCAD_PARCELS_ARCGIS_URL)")
    p.add_argument("--workdir", default="hcad_centroids_work",
                   help="Spool/checkpoint directory (default: %(default)s)")
    p.add_argument("--page-size", type=int, default=ARCGIS_PAGE_SIZE,
                   help="Features per request (default: %(default)s, the "
                        "layer's maxRecordCount)")
    p.add_argument("--max-pages", type=int, default=None,
                   help="Stop after N pages this run (smoke tests; a later "
                        "run resumes)")
    p.add_argument("--fresh", action="store_true",
                   help="Discard the existing spool/checkpoint and re-download")
    p.add_argument("--download-only", action="store_true",
                   help="Spool only; skip the DB load")
    p.add_argument("--load-only", action="store_true",
                   help="Skip the download; load the existing spool")
    args = p.parse_args()
    if not args.download_only and not args.dsn:
        p.error("no target database: pass --dsn or set DATABASE_URL")

    workdir = Path(args.workdir)
    if args.load_only:
        spool = workdir / "spool.csv"
        ckpt_path = workdir / "checkpoint.json"
        ckpt = json.loads(ckpt_path.read_text()) if ckpt_path.exists() else {}
    else:
        spool, ckpt = download(args.url, workdir, args.page_size, args.fresh,
                               args.max_pages)
    if args.download_only:
        return
    load(args.dsn, spool, ckpt)


if __name__ == "__main__":
    main()
