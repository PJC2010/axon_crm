"""
Diagnose why RentCast property lookups return no record.

The pipeline reports '0 ok / N fail' for a lookup the vendor answered but had
no record for. Until now a 4xx — an expired key, an unpaid plan, a malformed
parameter — was folded into that same bucket and logged only at DEBUG, so a
misconfiguration was indistinguishable from "this address is genuinely unknown"
while every row it touched got stamped as checked.

This script asks the question directly and prints the raw HTTP status, so the
two are told apart in a handful of calls instead of a whole billed sweep. It
also tries the request shapes the API may expect, since the pipeline sends a
bare street line plus a separate zipCode and the vendor documents `address` as
a full "street, city, state zip" string.

Costs at most a few lookups. Run it against one address you know exists:

    python tools/diagnose_rentcast.py --address "1234 YALE ST" --zip 77007
    python tools/diagnose_rentcast.py --account-id 14 --zip 77007   # pick one from the DB
"""
import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import RENTCAST_API_KEY, RENTCAST_BASE_URL   # noqa: E402


def _show(label: str, params: dict) -> None:
    if not RENTCAST_API_KEY:
        print("RENTCAST_API_KEY is not set — nothing to diagnose.")
        return
    try:
        r = requests.get(f"{RENTCAST_BASE_URL}/properties",
                         headers={"X-Api-Key": RENTCAST_API_KEY,
                                  "Accept": "application/json"},
                         params=params, timeout=20)
    except requests.RequestException as e:
        print(f"\n{label}\n  params: {params}\n  NO RESPONSE: {e}")
        return

    print(f"\n{label}\n  params: {params}\n  HTTP {r.status_code}")
    if r.status_code != 200:
        # The body is where RentCast explains a rejection.
        print(f"  body:   {(r.text or '')[:300]}")
        return
    try:
        data = r.json()
    except ValueError:
        print(f"  body:   (unparseable) {(r.text or '')[:200]}")
        return
    records = data if isinstance(data, list) else [data]
    print(f"  records: {len(records)}")
    if records:
        rec = records[0]
        print(f"  first:   {rec.get('formattedAddress') or rec.get('addressLine1')}")
        print(f"           yearBuilt={rec.get('yearBuilt')} "
              f"propertyType={rec.get('propertyType')} "
              f"garage={(rec.get('features') or {}).get('garageSpaces')} "
              f"owner={(rec.get('owner') or {}).get('names')}")


def _pick_address(account_id: int, zip_code: str) -> tuple[str, str, str]:
    """Grab one seeded address the sweep would actually have asked about."""
    from pipeline.db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT address, COALESCE(city, ''), COALESCE(state, 'TX')
                FROM properties
                WHERE account_id = %s AND zip = %s
                  AND address !~ '^0+(\\s|$)'
                  AND COALESCE(square_footage, 0) > 0
                ORDER BY id LIMIT 1
                """,
                (account_id, zip_code),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise SystemExit(f"No usable address found for account {account_id} "
                         f"in ZIP {zip_code}.")
    return row


def _fetch_zip_page(zip_code: str, limit: int = 500) -> list[dict]:
    """One page of the ZIP scan — the same call pipeline/seed.py already makes."""
    r = requests.get(f"{RENTCAST_BASE_URL}/properties",
                     headers={"X-Api-Key": RENTCAST_API_KEY,
                              "Accept": "application/json"},
                     params={"zipCode": zip_code, "limit": limit}, timeout=60)
    if r.status_code != 200:
        print(f"  ZIP scan failed: HTTP {r.status_code} {(r.text or '')[:200]}")
        return []
    data = r.json()
    return data if isinstance(data, list) else [data]


def match_test(account_id: int, zip_code: str, limit: int) -> None:
    """Does a bulk ZIP scan cover the rows the per-address lookup 404s on?

    The per-address endpoint answering 404 does not mean RentCast holds nothing
    for the ZIP — the scan may still carry the same parcels under its own
    address strings. This measures the overlap against what we actually store,
    using the one normalization rule (pipeline/addr.py), and so answers whether
    switching the detail step to scan-and-match would fill anything.

    One scan request per `limit` records, versus one request per property for
    the per-address lookup.
    """
    from pipeline.addr import normalize
    from pipeline.db import get_conn

    print(f"\n{'=' * 70}\nMATCH TEST — bulk ZIP scan vs. stored rows\n{'=' * 70}")
    records = _fetch_zip_page(zip_code, limit)
    print(f"\nZIP scan returned {len(records)} record(s) in 1 request.")
    if not records:
        return

    # Does a RentCast-supplied address resolve through the per-address endpoint?
    # If even its own string 404s, the endpoint is not an address lookup we can
    # use at all; if it resolves, the gap is purely one of address vocabulary.
    own = (records[0].get("addressLine1") or "").strip()
    if own:
        _show("[5] Per-address lookup using RENTCAST'S OWN address string",
              {"address": own, "zipCode": zip_code, "limit": 1})

    remote = {}
    for rec in records:
        line = (rec.get("addressLine1") or "").strip()
        if line:
            remote.setdefault(normalize(line), rec)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT address,
                       (year_built IS NULL) AS needs_year,
                       (property_type IS NULL) AS needs_type,
                       (garage_spaces IS NULL) AS needs_garage
                FROM properties
                WHERE account_id = %s AND zip = %s AND address !~ '^0+(\\s|$)'
                """,
                (account_id, zip_code),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"\nNo stored rows with a real address for account {account_id} "
              f"in ZIP {zip_code} — nothing to match against.")
        return

    hits = [r for r in rows if normalize(r[0]) in remote]
    print(f"\nStored rows with a real address: {len(rows)}")
    print(f"Matched by the scan:             {len(hits)} "
          f"({100 * len(hits) / len(rows):.1f}%)")
    if hits:
        fillable = sum(1 for r in hits if r[1] or r[2] or r[3])
        print(f"…of those, still missing year/type/garage: {fillable}")
        print("\nSample matches:")
        for r in hits[:5]:
            rec = remote[normalize(r[0])]
            print(f"  {r[0]:<34} -> {rec.get('addressLine1')} "
                  f"(yearBuilt={rec.get('yearBuilt')}, "
                  f"type={rec.get('propertyType')})")
    else:
        print("\nNo overlap. Sample of each side, to compare vocabulary:")
        for r in rows[:5]:
            print(f"  ours:      {r[0]!r}  -> norm {normalize(r[0])!r}")
        for rec in records[:5]:
            line = rec.get("addressLine1")
            print(f"  rentcast:  {line!r}  -> norm {normalize(line or '')!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--address", help="Street line to test, e.g. '1234 YALE ST'")
    ap.add_argument("--zip", dest="zip_code", required=True)
    ap.add_argument("--city", default="Houston")
    ap.add_argument("--state", default="TX")
    ap.add_argument("--account-id", type=int, default=None, dest="account_id",
                    help="Pick a real seeded address from this account instead")
    ap.add_argument("--match-test", action="store_true", dest="match_test",
                    help="Compare a bulk ZIP scan against stored rows "
                         "(requires --account-id)")
    ap.add_argument("--scan-limit", type=int, default=500, dest="scan_limit")
    args = ap.parse_args()

    if args.match_test:
        if args.account_id is None:
            raise SystemExit("--match-test requires --account-id.")
        match_test(args.account_id, args.zip_code, args.scan_limit)
        return

    address, city, state = args.address, args.city, args.state
    if not address:
        if args.account_id is None:
            raise SystemExit("Pass --address or --account-id.")
        address, db_city, db_state = _pick_address(args.account_id, args.zip_code)
        city = db_city or city
        state = db_state or state
        print(f"Testing seeded address: {address!r} (city={city!r} state={state!r})")

    print(f"\nKey configured: {bool(RENTCAST_API_KEY)}  "
          f"base: {RENTCAST_BASE_URL}")
    print("=" * 70)

    # 1. Exactly what the pipeline sends today.
    _show("[1] CURRENT pipeline shape — bare street + zipCode",
          {"address": address, "zipCode": args.zip_code, "limit": 1})

    # 2. Full single-string address, the documented shape.
    _show("[2] Full address string",
          {"address": f"{address}, {city}, {state} {args.zip_code}", "limit": 1})

    # 3. Components as separate parameters.
    _show("[3] Street + city + state + zip as separate params",
          {"address": address, "city": city, "state": state,
           "zipCode": args.zip_code, "limit": 1})

    # 4. No address at all — proves whether the key/plan can read this endpoint.
    _show("[4] CONTROL: ZIP-only query (does the key work at all?)",
          {"zipCode": args.zip_code, "limit": 1})

    print("\n" + "=" * 70)
    print("How to read this:")
    print("  [4] non-200          → key, plan or billing problem, not addresses.")
    print("  [4] 200 but [1] 0    → the request shape is wrong; use whichever of")
    print("                         [2]/[3] returned a record.")
    print("  all 200 with records → the address really is unknown to RentCast.")


if __name__ == "__main__":
    main()
