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


def _fetch_zip_page(zip_code: str, limit: int = 500, offset: int = 0) -> list[dict]:
    """One page of the ZIP scan — the same call pipeline/seed.py already makes."""
    r = requests.get(f"{RENTCAST_BASE_URL}/properties",
                     headers={"X-Api-Key": RENTCAST_API_KEY,
                              "Accept": "application/json"},
                     params={"zipCode": zip_code, "limit": limit, "offset": offset},
                     timeout=60)
    if r.status_code != 200:
        print(f"  ZIP scan failed at offset {offset}: "
              f"HTTP {r.status_code} {(r.text or '')[:200]}")
        return []
    data = r.json()
    return data if isinstance(data, list) else [data]


def _fetch_zip_all(zip_code: str, max_requests: int) -> list[dict]:
    """Every page of the ZIP scan, up to `max_requests` calls.

    Paginating matters for correctness, not just completeness. A single page
    compared against a partial book measures sampling overlap, not coverage:
    181 stored rows against 500 scanned records drawn from a 16k-parcel ZIP
    would collide on ~5 rows by chance alone, so a low match rate there says
    nothing about whether the vendor holds our parcels.
    """
    out: list[dict] = []
    for i in range(max_requests):
        page = _fetch_zip_page(zip_code, 500, offset=len(out))
        if not page:
            break
        out.extend(page)
        print(f"  page {i + 1}: +{len(page)} (total {len(out)})")
        if len(page) < 500:
            break            # last page
    return out


def _density(records: list[dict]) -> None:
    """How much the scan records actually carry.

    Coverage is only half the question: a record we can match but which holds
    no year built, property type or garage is not worth paying for either.
    """
    n = len(records) or 1

    def pct(fn) -> str:
        got = sum(1 for r in records if fn(r))
        return f"{got:>6,} ({100 * got / n:>5.1f}%)"

    print(f"\nField density across {len(records):,} scanned record(s):")
    print(f"  yearBuilt      {pct(lambda r: r.get('yearBuilt'))}")
    print(f"  propertyType   {pct(lambda r: r.get('propertyType'))}")
    print(f"  squareFootage  {pct(lambda r: r.get('squareFootage'))}")
    print(f"  garageSpaces   {pct(lambda r: (r.get('features') or {}).get('garageSpaces'))}")
    print(f"  owner.names    {pct(lambda r: (r.get('owner') or {}).get('names'))}")
    print(f"  lastSaleDate   {pct(lambda r: r.get('lastSaleDate'))}")


def address_format_test(zip_code: str) -> None:
    """Try the shapes neither earlier test covered, on a record known to exist.

    Test [5] proved the per-address endpoint 404s on RentCast's own
    `addressLine1`. But that was sent as a bare street plus a `zipCode`
    parameter, and the documented form is a single full string that carries a
    comma before the ZIP ("5500 Grand Lake Dr, San Antonio, TX, 78244"). Until
    that exact shape is tried against a record the vendor demonstrably holds,
    "the endpoint is unusable" is an inference rather than a finding.
    """
    print(f"\n{'=' * 70}\nADDRESS FORMAT TEST — on a record the scan just returned\n{'=' * 70}")
    records = _fetch_zip_page(zip_code, limit=1)
    if not records:
        print("Scan returned nothing; cannot test.")
        return
    rec = records[0]
    line = (rec.get("addressLine1") or "").strip()
    formatted = (rec.get("formattedAddress") or "").strip()
    city, state = rec.get("city") or "", rec.get("state") or ""
    zc = rec.get("zipCode") or zip_code
    print(f"\nUsing: addressLine1={line!r}\n       formattedAddress={formatted!r}")

    _show("[A] formattedAddress verbatim", {"address": formatted, "limit": 1})
    _show("[B] rebuilt WITH comma before ZIP (documented form)",
          {"address": f"{line}, {city}, {state}, {zc}", "limit": 1})
    _show("[C] rebuilt WITHOUT comma before ZIP",
          {"address": f"{line}, {city}, {state} {zc}", "limit": 1})
    _show("[D] bare street + city/state/zip params",
          {"address": line, "city": city, "state": state, "zipCode": zc, "limit": 1})
    print("\n  Any 200 here names the format the detail step must send.")
    print("  All 404 → the per-address endpoint cannot retrieve this vendor's")
    print("  own records, and scan-and-match is the only workable path.")

    # Which component actually carries the lookup, and how much a wrong one
    # costs. This is not academic: HCAD-seeded rows take `city` from the OWNER'S
    # mailing city (pipeline/seed.py::_normalize_hcad), and the geocode step
    # reads `city` without ever writing back the one Google resolved. So for an
    # absentee owner — the most valuable lead — the stored city names the wrong
    # town. If a wrong city still resolves, the fix is to pass what we hold; if
    # it does not, the fix must first learn each property's real city.
    print(f"\n{'-' * 70}\nWHICH PARAMETER CARRIES THE LOOKUP\n{'-' * 70}")
    _show("[E] state + zip, NO city",
          {"address": line, "state": state, "zipCode": zc, "limit": 1})
    _show("[F] city + zip, NO state",
          {"address": line, "city": city, "zipCode": zc, "limit": 1})
    _show("[G] city + state, NO zip",
          {"address": line, "city": city, "state": state, "limit": 1})
    _show("[H] WRONG city (absentee-owner case), right state + zip",
          {"address": line, "city": "Dallas", "state": state,
           "zipCode": zc, "limit": 1})
    _show("[I] WRONG city inside the full address string",
          {"address": f"{line}, Dallas, {state} {zc}", "limit": 1})

    print("\n  [E] 200            → city is not required; pass state+zip and we are done.")
    print("  [H]/[I] 200        → a wrong city is tolerated; stored mail_city is safe to send.")
    print("  [H]/[I] 404        → the city must be RIGHT, so the geocode step has to")
    print("                       persist the city Google already resolves.")


def _zip_parcel_count(zip_code: str) -> int | None:
    """How many parcels the ZIP actually holds, for the sampling check.

    Prefers the shared cache, falling back to the raw HCAD mirror; returns None
    when neither is available rather than guessing a denominator.
    """
    from pipeline.db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for sql in ("SELECT COUNT(*) FROM parcels WHERE zip = %s",
                        "SELECT COUNT(*) FROM hcad_properties WHERE site_zip = %s"):
                try:
                    cur.execute(sql, (zip_code,))
                    n = cur.fetchone()[0]
                    if n:
                        return int(n)
                except Exception:
                    conn.rollback()
    finally:
        conn.close()
    return None


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
    print(f"Paginating the ZIP scan (cap {limit} request(s), 500 records each)…")
    records = _fetch_zip_all(zip_code, limit)
    print(f"\nZIP scan returned {len(records):,} record(s).")
    if not records:
        return

    _density(records)

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

    # Guard against reading a sampling artefact as a coverage finding. If the
    # scan stopped short of the ZIP's parcel count, our rows and the scanned
    # records are two partial, independently-ordered samples of the same
    # population, and some overlap is expected from chance alone. Comparing the
    # observed count against that expectation is what separates "the vendor
    # does not hold our parcels" from "we did not scan far enough".
    parcel_total = _zip_parcel_count(zip_code)
    if parcel_total and len(records) < parcel_total:
        expected = len(rows) * len(records) / parcel_total
        print(f"\n  ⚠ PARTIAL SCAN: {len(records):,} of ~{parcel_total:,} parcels "
              f"in this ZIP.")
        print(f"    Overlap expected from chance alone: ~{expected:.1f} row(s). "
              f"Observed: {len(hits)}.")
        if len(hits) <= expected * 1.5:
            print("    → This match rate is NOT evidence about coverage. "
                  "Raise --scan-limit\n      until the scan is complete before "
                  "drawing any conclusion.")
        else:
            print("    → Observed exceeds chance; coverage looks real, but "
                  "finish the scan\n      for a trustworthy rate.")
    elif parcel_total:
        print(f"\n  Scan is complete for this ZIP ({len(records):,} of "
              f"~{parcel_total:,} parcels) — this match rate is meaningful.")

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
    ap.add_argument("--format-test", action="store_true", dest="format_test",
                    help="Try each address format against a record the scan "
                         "just returned")
    ap.add_argument("--scan-limit", type=int, default=40, dest="scan_limit",
                    help="Max ZIP-scan REQUESTS for --match-test (500 records "
                         "each; 40 covers ~20k parcels). Default 40.")
    args = ap.parse_args()

    if args.format_test:
        address_format_test(args.zip_code)
        return

    if args.match_test:
        if args.account_id is None:
            raise SystemExit("--match-test requires --account-id.")
        if args.scan_limit > 100:
            raise SystemExit(f"--scan-limit {args.scan_limit} would make up to "
                             f"{args.scan_limit} billed requests. Cap is 100.")
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
