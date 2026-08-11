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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--address", help="Street line to test, e.g. '1234 YALE ST'")
    ap.add_argument("--zip", dest="zip_code", required=True)
    ap.add_argument("--city", default="Houston")
    ap.add_argument("--state", default="TX")
    ap.add_argument("--account-id", type=int, default=None, dest="account_id",
                    help="Pick a real seeded address from this account instead")
    args = ap.parse_args()

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
