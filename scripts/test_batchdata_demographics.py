#!/usr/bin/env python3
"""Smoke-test the BatchData demographics integration against one real address.

Calls the same `_batchdata_lookup` the pipeline's demographics step uses, so a
green run here means the live wiring (endpoint, auth, response shape) is correct
end to end — and the columns printed are exactly the ones that feed the ML model
(see pipeline/ml/features.py). No DB required.

Usage:
    # Reads DEMO_API_KEY (and optional DEMO_BASE_URL) from the env/.env:
    python scripts/test_batchdata_demographics.py \
        --address "1011 S Lincoln St" --city Boston --state MA --zip 02127 \
        --owner "John Doe"

    # --owner is optional; without it BatchData matches on the address alone.

Requires DEMO_API_KEY to be set and the account to have the demographic add-on.
Exits non-zero if the key isn't configured or no demographics are returned.
"""
import argparse
import sys
from pathlib import Path

# Allow running as a standalone script: make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DEMO_API_KEY, DEMO_BASE_URL  # noqa: E402
from pipeline.demographics import _batchdata_lookup, _BATCHDATA_DEMO_URL  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test BatchData demographics.")
    parser.add_argument("--address", required=True, help="Street address")
    parser.add_argument("--city", default="", help="City")
    parser.add_argument("--state", default="", help="State (2-letter)")
    parser.add_argument("--zip", default="", help="ZIP code")
    parser.add_argument("--owner", default="", help="Owner name (optional)")
    args = parser.parse_args()

    if not DEMO_API_KEY:
        print("ERROR: DEMO_API_KEY is not set. Add your BatchData token to .env "
              "(or export it) and retry.", file=sys.stderr)
        return 2

    endpoint = DEMO_BASE_URL or _BATCHDATA_DEMO_URL
    print(f"Calling BatchData demographics at {endpoint} …")

    row = {
        "owner_name": args.owner,
        "address": args.address,
        "city": args.city,
        "state": args.state,
        "zip": args.zip,
    }
    result = _batchdata_lookup(row)

    if result is None:
        print("No demographics returned (no match, the call failed, or the account "
              "lacks the demographic add-on — check the logs above for an HTTP error).")
        return 1

    print(f"Demographics found ({len(result)} fields populated):")
    for key in sorted(result):
        print(f"  {key:28} {result[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
