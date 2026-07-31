"""
Probe the Census batch geocoder to find its real working limits.

READ-ONLY: selects addresses, makes HTTP calls, writes nothing.

Answers three questions the production log left open:
  1. What batch size actually succeeds? (10,000 failed 4/4; 1,335 worked)
  2. How long does a working batch take? (sets a sane timeout)
  3. Does the endpoint tolerate concurrent batches? (decides parallelism)

Run from the Render shell:
    python probe_census.py
"""
import csv
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import requests

URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
ZIP = os.getenv("PROBE_ZIP", "77449")
# Generous, so a slow-but-working batch is not misread as a failure. The real
# production timeout gets derived from the measured latencies below.
TIMEOUT = int(os.getenv("PROBE_TIMEOUT", "420"))
LADDER = [int(x) for x in os.getenv("PROBE_LADDER", "500,1000,2000,3000,5000,10000").split(",")]


def fetch_addresses(limit):
    dsn = os.environ["DATABASE_URL"]
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, address, city, state, zip FROM properties "
            "WHERE zip = %s AND latitude IS NULL AND address IS NOT NULL "
            "  AND address <> '' AND archived_at IS NULL "
            "LIMIT %s",
            (ZIP, limit),
        )
        return [dict(zip(("id", "address", "city", "state", "zip"), r))
                for r in cur.fetchall()]


def build_payload(rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow([r["id"],
                    " ".join(str(r["address"] or "").split()),
                    " ".join(str(r["city"] or "").split()),
                    " ".join(str(r["state"] or "").split()),
                    " ".join(str(r["zip"] or "").split())])
    return buf.getvalue()


def count_matches(text):
    n = 0
    for row in csv.reader(io.StringIO(text or "")):
        if len(row) >= 6 and row[2].strip() == "Match":
            n += 1
    return n


def one_batch(rows, label=""):
    """Single attempt, no retries — we want the raw signal."""
    payload = build_payload(rows)
    started = time.perf_counter()
    try:
        resp = requests.post(
            URL,
            files={"addressFile": ("addresses.csv", payload, "text/csv")},
            data={"benchmark": BENCHMARK},
            timeout=TIMEOUT,
        )
        elapsed = time.perf_counter() - started
        if resp.status_code != 200:
            return {"ok": False, "why": f"HTTP {resp.status_code}", "secs": elapsed,
                    "n": len(rows), "matched": 0, "label": label}
        matched = count_matches(resp.text)
        return {"ok": True, "why": "", "secs": elapsed, "n": len(rows),
                "matched": matched, "label": label}
    except requests.RequestException as e:
        return {"ok": False, "why": type(e).__name__, "secs": time.perf_counter() - started,
                "n": len(rows), "matched": 0, "label": label}


def slice_at(pool, start, size):
    """`size` rows beginning at `start`, wrapping around the pool.

    Wrapping means the ladder and the concurrency test always get a full-size
    batch regardless of how many ungeocoded addresses are left, and each worker
    starts somewhere different. Repeats across workers are harmless here — this
    measures throughput and tolerance, and nothing is written back.
    """
    n = len(pool)
    return [pool[(start + k) % n] for k in range(size)]


def show(r):
    rate = f"{r['n'] / r['secs']:.0f}/s" if r["ok"] and r["secs"] else "—"
    pct = f"{100 * r['matched'] / r['n']:.1f}%" if r["ok"] and r["n"] else "—"
    status = "OK  " if r["ok"] else "FAIL"
    print(f"  {status} size={r['n']:>6,}  {r['secs']:>7.1f}s  {rate:>8}  "
          f"matched={r['matched']:>6,} ({pct:>6})  {r['why']}")
    sys.stdout.flush()


def main():
    need = max(LADDER) * 2
    print(f"Fetching up to {need:,} ungeocoded addresses from ZIP {ZIP}…")
    pool = fetch_addresses(need)
    print(f"got {len(pool):,}\n")
    if not pool:
        print("No ungeocoded addresses found — nothing to probe.")
        return

    # ── 1. Size ladder: 2 trials each, stop after a size fails twice ─────────
    print("=== batch size ladder (2 trials each, no retries) ===")
    results = {}
    largest_ok = 0
    for size in LADDER:
        trials = []
        for t in range(2):
            r = one_batch(slice_at(pool, t * size, size), label=f"size{size}")
            show(r)
            trials.append(r)
        results[size] = trials
        if any(t["ok"] for t in trials):
            largest_ok = max(largest_ok, size)
        else:
            print(f"  -> {size:,} failed both trials; stopping the ladder here.")
            break

    if not largest_ok:
        print("\nNo batch size succeeded. The endpoint may be down; retry later.")
        return

    # ── 2. Concurrency at the largest working size ──────────────────────────
    # 41,335 addresses at ~166s per 1,335 (from the production log) is over an
    # hour sequentially, so parallelism matters as much as batch size.
    print(f"\n=== concurrency at size={largest_ok:,} ===")
    best_throughput = (0.0, 1)
    for workers in (2, 4, 8):
        batches = [slice_at(pool, i * largest_ok, largest_ok) for i in range(workers)]
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            rs = list(ex.map(one_batch, batches))
        wall = time.perf_counter() - started
        ok = sum(1 for r in rs if r["ok"])
        done = sum(r["n"] for r in rs if r["ok"])
        thru = done / wall if wall else 0
        print(f"  {workers} parallel: {ok}/{workers} ok, {done:,} addresses in "
              f"{wall:.1f}s  ({thru:.0f}/s overall)")
        for r in rs:
            if not r["ok"]:
                print(f"      failure: {r['why']}")
        if thru > best_throughput[0]:
            best_throughput = (thru, workers)
        if ok < workers:
            print(f"  -> {workers} workers is too many; back off.")
            break

    # ── 3. Recommendation ───────────────────────────────────────────────────
    # Each line maps to one production constant, so the config follows from
    # measurement rather than from the documented limit that already misled us.
    oks = [t for trials in results.values() for t in trials if t["ok"]]
    if not oks:
        return
    slowest = max(t["secs"] for t in oks)
    thru, workers = best_throughput
    total = 41335

    print("\n" + "=" * 62)
    print("SUMMARY — paste this back")
    print("=" * 62)
    # Floored: a fast sample must not produce a timeout so tight that a normal
    # slow-but-healthy batch gets killed. The failure mode we are fixing came
    # from a timeout that was far too generous, but too tight is its own bug.
    suggested_timeout = max(120, int(slowest * 2.5))
    print(f"  MAX_BATCH             = {largest_ok:,}       (largest size that worked)")
    print(f"  CENSUS_BATCH_TIMEOUT  = {suggested_timeout}s      "
          f"(2.5x slowest success of {slowest:.0f}s, floored at 120s)")
    print(f"  batch concurrency     = {workers}          (best observed throughput)")
    print(f"  observed throughput   = {thru:.0f} addr/s")
    if thru:
        print(f"  => {total:,} addresses would take ~{total / thru / 60:.1f} min "
              f"(was 83 min, mostly failing)")
    match_rates = [100 * t["matched"] / t["n"] for t in oks if t["n"]]
    if match_rates:
        print(f"  match rate            = {min(match_rates):.1f}–{max(match_rates):.1f}% "
              f"(production log saw 99.3%)")
    print("=" * 62)
    print("\n  per-size detail:")
    for size, trials in sorted(results.items()):
        ok_n = sum(1 for t in trials if t["ok"])
        secs = [f"{t['secs']:.0f}s" for t in trials]
        whys = {t["why"] for t in trials if t["why"]}
        print(f"    {size:>6,}: {ok_n}/{len(trials)} ok  [{', '.join(secs)}]"
              + (f"  {', '.join(whys)}" if whys else ""))


if __name__ == "__main__":
    main()
