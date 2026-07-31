#!/usr/bin/env python3
"""
Smart CRM — Data Acquisition Pipeline
Usage:
    python run_pipeline.py --zip 30066
    python run_pipeline.py --zip 30066 --vertical epoxy_flooring
    python run_pipeline.py --zip-file zips.txt --vertical epoxy_flooring
    python run_pipeline.py --zip 30066 --seed-csv /path/to/addresses.csv
    python run_pipeline.py --zip 30066 --permit-csv /path/to/permits.csv
    python run_pipeline.py --zip 30066 --skip seed,geocode
    python run_pipeline.py --zip 30066 --force-seed   # re-seed even if ZIP already exists
"""
import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _fmt_counters(counters: dict) -> str:
    """Render per-source property counters compactly for logs."""
    parts = []
    for src, c in counters.items():
        if c.get("skipped_no_key"):
            parts.append(f"{src}=skipped(no key)")
        else:
            parts.append(f"{src}: {c.get('updated', 0)} updated "
                         f"({c.get('ok', 0)} ok/{c.get('fail', 0)} fail)")
    return "; ".join(parts) or "nothing to do"


def _log_coverage(zip_code: str, account_id: int, stage: str) -> None:
    """Log per-field null counts for the ZIP so the gap the next (paid) step
    would spend money on is visible before it runs."""
    from pipeline.coverage import fill_rates
    from pipeline.db import get_conn
    conn = get_conn()
    try:
        rates = fill_rates(conn, zip_code, account_id)
    finally:
        conn.close()
    total = next(iter(rates.values()), {}).get("total", 0)
    lines = [f"Coverage after {stage} — ZIP {zip_code}, {total} properties:"]
    lines.append(f"    {'field':22}  {'null':>6}  {'filled':>7}")
    for f, r in sorted(rates.items(), key=lambda kv: kv[1]["pct"]):
        lines.append(f"    {f:22}  {r['total'] - r['filled']:>6}  {r['pct']:>6.1f}%")
    log.info("%s", "\n".join(lines))


def _resolved_config(skip: set) -> dict:
    """Which providers this run will actually use.

    Logged up front because whether a serial per-property HTTP loop runs at all
    is the single biggest factor in how long a run takes, and that depends on
    env vars rather than on anything in the repo. Booleans only — key values are
    never logged.
    """
    from config import (
        SEED_SOURCE, RENTCAST_API_KEY, GOOGLE_GEOCODE_KEY, CENSUS_API_KEY,
        CONTACT_PROVIDER, PROPERTY_FIELD_SOURCES,
    )
    from pipeline import hcad_store
    return {
        "seed_source":      SEED_SOURCE or "rentcast",
        "hcad_source":      "duckdb" if hcad_store.db_exists() else "postgres",
        "rentcast":         bool(RENTCAST_API_KEY),
        "google_geocode":   bool(GOOGLE_GEOCODE_KEY),
        "census_key":       bool(CENSUS_API_KEY),
        "contact_provider": CONTACT_PROVIDER or None,
        "property_sources": list(PROPERTY_FIELD_SOURCES),
        "skip":             sorted(skip),
    }


def _zip_already_seeded(zip_code: str, account_id: int) -> bool:
    """Return True if the ZIP already has properties for this org in the DB."""
    from pipeline.db import get_conn
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM properties WHERE zip = %s AND account_id = %s LIMIT 1", (zip_code, account_id))
        exists = cur.fetchone() is not None
    conn.close()
    return exists


def run_zip(zip_code: str, args) -> None:
    """Run the full step sequence for one ZIP, always reporting timings.

    The table is emitted from a `finally` so a step that raises still says where
    the time went — a run that dies partway is exactly when that matters most.
    """
    from pipeline.db import UpsertProbe
    from pipeline.timing import StepTimer

    # Same instrumentation the scheduler uses, so a Render Shell run and a
    # UI-triggered run produce directly comparable tables. The gap between them
    # is what in-process contention on the web dyno costs.
    timer = StepTimer(probe=UpsertProbe.install())
    try:
        _run_zip_steps(zip_code, args, timer)
    finally:
        UpsertProbe.uninstall()
        log.info("%s", timer.format_table(title=f"ZIP {zip_code}"))


def _run_zip_steps(zip_code: str, args, timer) -> None:
    skip = set(s.strip() for s in (args.skip or "").split(",") if s.strip())
    account_id = args.account_id
    top_n = getattr(args, "top_n", None)
    radius_mi = getattr(args, "radius", None)
    center_address = getattr(args, "address", None)
    capped = bool(top_n or (center_address and radius_mi))
    log.info("━━━  ZIP %s  ━━━", zip_code)
    log.info("Config: %s", _resolved_config(skip))

    if "seed" not in skip:
        from pipeline.seed import seed
        if not args.force_seed and _zip_already_seeded(zip_code, account_id):
            log.info("[1/7] Seed: skipped (ZIP already in DB — use --force-seed to re-fetch)")
        else:
            with timer.step("seed") as s:
                n = seed(zip_code, account_id, csv_path=args.seed_csv, limit=args.limit,
                         seed_source=getattr(args, "seed_source", None))
                s.rows = n
            log.info("[1/7] Seed: %d records", n)
    else:
        log.info("[1/7] Seed: skipped")

    if "census" not in skip:
        from pipeline.census import enrich_census
        with timer.step("census") as s:
            n = enrich_census(zip_code, account_id)
            s.rows = n
        log.info("[2/7] Census: %d updated", n)
    else:
        log.info("[2/7] Census: skipped")

    if "geocode" not in skip:
        from pipeline.geocode import enrich_geocode
        with timer.step("geocode") as s:
            n = enrich_geocode(zip_code, account_id)
            s.rows = n
        log.info("[3/7] Geocode: %d updated", n)
    else:
        log.info("[3/7] Geocode: skipped")

    # HCAD runs BEFORE RentCast — it's free (local DuckDB) and fills many
    # of the same fields (year_built, square_footage, estimated_value, etc.).
    # Running it first means fewer properties will have NULL fields, so RentCast
    # sees a smaller work queue and makes fewer paid API calls.
    if "hcad" not in skip:
        from pipeline.hcad_enrichment import enrich_hcad
        with timer.step("hcad") as s:
            n = enrich_hcad(zip_code, account_id)
            s.rows = n
        log.info("[4/7] HCAD (free): %d fields backfilled", n)
        # Checkpoint: what the free steps left NULL — i.e. what RentCast
        # would be paid to fill. Inspect this before an unskipped paid run.
        with timer.step("coverage:after_hcad"):
            _log_coverage(zip_code, account_id, "HCAD (free steps done, before paid)")
    else:
        log.info("[4/7] HCAD: skipped")

    # Selection (volume control) — marks the subset that proceeds to the paid
    # steps below. It cannot move ahead of geocode: radius narrowing filters on
    # the coordinates geocode produces (pipeline/select.py::_within_radius), so
    # geocode is capped at the provider level instead (free Census batch, paid
    # Google limited to GEOCODE_FALLBACK_MAX misses).
    if capped and "select" not in skip:
        from pipeline.db import get_conn
        from pipeline.select import select_for_enrichment
        from pipeline.geocode import geocode_address
        center = None
        if center_address and radius_mi:
            center = geocode_address(center_address)
            if center is None:
                log.warning("Could not geocode --address %r — radius filter skipped",
                            center_address)
        conn = get_conn()
        try:
            with timer.step("select"):
                res = select_for_enrichment(conn, zip_code, account_id, top_n=top_n, center=center,
                                            radius_mi=radius_mi, vertical=args.vertical)
        finally:
            conn.close()
        log.info("[4.5/8] Selection: %s", res)

    if "property" not in skip:
        from pipeline.property import enrich_property
        with timer.step("property") as s:
            counters = enrich_property(zip_code, account_id, selected_only=capped)
            # Rows here means properties the paid source was actually called for
            # — the number that drives both the time and the bill.
            s.rows = sum(c.get("ok", 0) + c.get("fail", 0) for c in counters.values())
        log.info("[5/8] Property detail (RentCast): %s",
                 _fmt_counters(counters))
        # Checkpoint: what RentCast refined and what is still NULL for the
        # skip-trace/demographics (BatchData) steps further down.
        with timer.step("coverage:after_property"):
            _log_coverage(zip_code, account_id, "property detail (before skip-trace)")
    else:
        log.info("[5/8] Property detail: skipped")

    if "permits" not in skip:
        from pipeline.permits import enrich_permits
        with timer.step("permits") as s:
            n = enrich_permits(zip_code, account_id, csv_path=args.permit_csv)
            s.rows = n
        log.info("[6/8] Permits: %d updated", n)
    else:
        log.info("[6/8] Permits: skipped")

    # Storm/hail enrichment runs after geocode (needs lat/lng), before scoring.
    if "storm" not in skip:
        from pipeline.storm import enrich_storm
        with timer.step("storm") as s:
            n = enrich_storm(zip_code, account_id)
            s.rows = n
        log.info("[6.5/8] Storm: %d matched", n)
    else:
        log.info("[6.5/8] Storm: skipped")

    if "score" not in skip:
        from pipeline.scorer import score_zip
        with timer.step("score") as s:
            n = score_zip(zip_code, account_id, vertical=args.vertical)
            s.rows = n
        log.info("[7/8] Scoring: %d scored", n)
    else:
        log.info("[7/8] Scoring: skipped")

    # Precision trim: cut the over-sampled selection back to exactly top_n using
    # the now-available real scores, before the paid skip-trace step.
    if capped and top_n and "score" not in skip:
        from pipeline.db import get_conn
        from pipeline.select import trim_to_top_n
        conn = get_conn()
        try:
            with timer.step("trim") as s:
                kept = trim_to_top_n(conn, zip_code, account_id, top_n)
                s.rows = kept
        finally:
            conn.close()
        log.info("[7.5/8] Trim: kept top %d", kept)

    # Contact runs after scoring so the optional min-grade gate can apply.
    if "contact" not in skip:
        from pipeline.contact import enrich_contact
        with timer.step("contact") as s:
            c = enrich_contact(zip_code, account_id, selected_only=capped)
            s.rows = c.get("ok", 0) + c.get("fail", 0)
        log.info("[8/8] Contact: %d filled%s", c.get("updated", 0),
                 " (skipped: no provider)" if c.get("skipped_no_key") else "")
    else:
        log.info("[8/8] Contact: skipped")

    # Demographics enrichment runs after scoring so the grade gate can apply.
    if "demographics" not in skip:
        from pipeline.demographics import enrich_demographics
        with timer.step("demographics") as s:
            c = enrich_demographics(zip_code, account_id, selected_only=capped)
            s.rows = c.get("ok", 0) + c.get("fail", 0)
        log.info("[demo] Demographics: %d filled%s", c.get("updated", 0),
                 " (skipped: no provider)" if c.get("skipped_no_key") else "")
    else:
        log.info("[demo] Demographics: skipped")

    # Timing signals run last: diff sale/permit/storm fields against the previous
    # run's baseline, record signal_events, fire signal_event workflow rules.
    if "signals" not in skip:
        from pipeline.signals import detect_signals
        with timer.step("signals"):
            signals = detect_signals(zip_code, account_id)
        log.info("[signals] %s", signals)
    else:
        log.info("[signals] skipped")

    if "score" not in skip:
        from pipeline.coverage import fill_rates
        from pipeline.db import get_conn
        conn = get_conn()
        try:
            with timer.step("coverage:final"):
                weak = sorted(
                    ((f, r["pct"]) for f, r in fill_rates(conn, zip_code, account_id).items()),
                    key=lambda kv: kv[1],
                )[:5]
        finally:
            conn.close()
        log.info("Weakest columns for ZIP %s: %s", zip_code,
                 ", ".join(f"{f} {p}%" for f, p in weak))


def main():
    parser = argparse.ArgumentParser(description="Smart CRM data pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--zip",      help="Single ZIP code to process")
    group.add_argument("--zip-file", help="Path to a file with one ZIP per line")

    parser.add_argument("--account-id", type=int, required=True, dest="account_id",
                        help="Organization (account) id that owns the leads produced by this run")
    parser.add_argument("--vertical",   default=None,
                        help="Scoring vertical (e.g. epoxy_flooring, pool_maintenance, solar)")
    parser.add_argument("--seed-csv",   default=None,
                        help="CSV file to seed addresses from (instead of RentCast API)")
    parser.add_argument("--seed-source", default=None, dest="seed_source",
                        choices=["rentcast", "hcad"],
                        help="Where step 1 gets addresses: 'rentcast' (paid, default) or "
                             "'hcad' (free local Harris County data). Overrides SEED_SOURCE env.")
    parser.add_argument("--permit-csv", default=None,
                        help="CSV file with permit counts (address, zip, permit_count)")
    parser.add_argument("--skip",       default="",
                        help="Comma-separated steps to skip: seed,census,geocode,hcad,select,property,permits,storm,score,contact,demographics,signals")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Cap the number of seeded records (useful for testing)")
    parser.add_argument("--top-n",      type=int, default=None, dest="top_n",
                        help="Keep only the top N leads per ZIP before paid enrichment "
                             "(cuts RentCast/skip-trace cost)")
    parser.add_argument("--address",    default=None,
                        help="Center address for radius narrowing (with --radius)")
    parser.add_argument("--radius",     type=float, default=None,
                        help="Miles from --address; only homes inside the circle are enriched")
    parser.add_argument("--force-seed", action="store_true", default=False,
                        help="Re-fetch from RentCast even if the ZIP already has properties in the DB")

    args = parser.parse_args()

    if args.zip:
        zips = [args.zip.strip()]
    else:
        with open(args.zip_file) as f:
            zips = [line.strip() for line in f if line.strip()]

    if not zips:
        log.error("No ZIP codes provided.")
        sys.exit(1)

    start = time.time()
    for z in zips:
        run_zip(z, args)
    elapsed = time.time() - start
    log.info("Done. Processed %d ZIP(s) in %.1fs", len(zips), elapsed)


if __name__ == "__main__":
    main()
