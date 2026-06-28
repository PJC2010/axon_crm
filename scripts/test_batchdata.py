#!/usr/bin/env python3
"""Smoke-test the BatchData skip-trace integration against one real address.

Calls the same `_batchdata_lookup` the pipeline and the per-lead Enrich button
use, so a green run here means the live wiring (endpoint, auth, response shape)
is correct end to end — no DB required.

Usage:
    # Reads CONTACT_API_KEY (and optional CONTACT_BASE_URL) from the env/.env:
    python scripts/test_batchdata.py \
        --address "1011 S Lincoln St" --city Boston --state MA --zip 02127 \
        --owner "John Doe"

    # --owner is optional; without it BatchData matches on the address alone.

Requires CONTACT_API_KEY to be set (CONTACT_PROVIDER is not needed for this
direct call). Exits non-zero if the provider isn't configured or the call fails.
"""
import argparse
import sys
from pathlib import Path

# Allow running as a standalone script: make the repo root importable so the
# `config`/`pipeline` imports resolve regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONTACT_API_KEY, CONTACT_BASE_URL  # noqa: E402
from pipeline.contact import _batchdata_lookup, _BATCHDATA_SKIPTRACE_URL  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test BatchData skip-trace.")
    parser.add_argument("--address", required=True, help="Street address")
    parser.add_argument("--city", default="", help="City")
    parser.add_argument("--state", default="", help="State (2-letter)")
    parser.add_argument("--zip", default="", help="ZIP code")
    parser.add_argument("--owner", default="", help="Owner name (optional)")
    args = parser.parse_args()

    if not CONTACT_API_KEY:
        print("ERROR: CONTACT_API_KEY is not set. Add your BatchData token to .env "
              "(or export it) and retry.", file=sys.stderr)
        return 2

    endpoint = CONTACT_BASE_URL or _BATCHDATA_SKIPTRACE_URL
    print(f"Calling BatchData skip-trace at {endpoint} …")

    row = {
        "owner_name": args.owner,
        "address": args.address,
        "city": args.city,
        "state": args.state,
        "zip": args.zip,
    }
    result = _batchdata_lookup(row)

    if result is None:
        print("No match (provider returned nothing, or the call failed — check the "
              "logs above for an HTTP error).")
        return 1

    print("Match found:")
    print(f"  contact_name:  {result.get('contact_name')}")
    print(f"  contact_phone: {result.get('contact_phone')}")
    print(f"  contact_email: {result.get('contact_email')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
