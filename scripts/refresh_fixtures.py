#!/usr/bin/env python
"""Re-record the golden corpus's vendor payloads from the live vendors.

For each address in tests/golden/fixtures/addresses.yaml this fetches the raw
RentCast / ACS / Census-geocoder / HCAD payloads (tests/golden/recording.py —
the same request shapes production uses), then before ANYTHING touches disk:

  * strips API keys and auth material (keys never appear in response bodies,
    but the sanitizer allowlists rather than trusts that);
  * strips owner PII from RentCast and HCAD payloads — owner names, mailing
    addresses, phones, skip-trace fields. These are real parcels tied to real
    people and fixtures live in git history permanently (TX SB 2121 makes
    this a hard requirement). Only fields the scored factors and the
    address/parcel verification checks consume survive the allowlist;
  * serializes canonically (sorted keys, floats pinned to 6 decimals) so a
    re-record produces a reviewable diff instead of churn.

Successful recordings are registered in tests/golden/fixtures/recorded.json;
only registered slugs are drift-checked by the nightly contract job (a
synthetic baseline can't measure vendor drift).

After recording, regenerate and REVIEW the goldens:
    python scripts/regen_golden.py            # inspect the diff table
    python scripts/regen_golden.py --confirm  # then commit both together

Usage:
    python scripts/refresh_fixtures.py                 # dry run: fetch + report
    python scripts/refresh_fixtures.py --confirm       # write fixtures
    python scripts/refresh_fixtures.py --confirm --only 4614-pin-oak-forest-dr-77070
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.golden import harness, recording, sanitize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true",
                        help="write sanitized fixtures to disk")
    parser.add_argument("--only", action="append", default=None,
                        metavar="SLUG", help="limit to specific slug(s)")
    args = parser.parse_args()

    entries = harness.corpus_entries()
    if args.only:
        unknown = set(args.only) - {e["slug"] for e in entries}
        if unknown:
            parser.error(f"unknown slug(s): {sorted(unknown)}")
        entries = [e for e in entries if e["slug"] in args.only]

    state = {}
    if harness.RECORDED_STATE.exists():
        state = json.loads(harness.RECORDED_STATE.read_text())

    wrote = 0
    for entry in entries:
        slug = entry["slug"]
        payloads, skips = recording.fetch_all(entry)
        for kind, reason in sorted(skips.items()):
            print(f"  {slug}: {kind} SKIPPED — {reason}")
        if "rentcast" not in payloads and "hcad" not in payloads:
            print(f"  {slug}: no property source reachable — nothing recorded")
            continue

        clean = {}
        if "rentcast" in payloads:
            clean["rentcast"] = sanitize.sanitize_rentcast(payloads["rentcast"])
        if "hcad" in payloads:
            clean["hcad"] = sanitize.sanitize_hcad(payloads["hcad"])
        if "acs" in payloads:
            clean["acs"] = payloads["acs"]
        if "geocode" in payloads:
            clean["geocode"] = payloads["geocode"]

        for kind, payload in sorted(clean.items()):
            path = harness.vendor_path(kind, slug)
            text = sanitize.canonical_json(payload)
            changed = (not path.exists()) or path.read_text() != text
            status = "would write" if not args.confirm else "wrote"
            if changed:
                print(f"  {slug}: {status} {path.relative_to(harness.GOLDEN_DIR)}")
            if args.confirm and changed:
                sanitize.write_fixture(path, payload)
                wrote += 1

        if args.confirm:
            # Merge with any earlier partial recording rather than replacing,
            # and register the slug as a drift baseline ONLY once its RentCast
            # half is real: the nightly job re-fetches RentCast live, and
            # measuring "drift" against a still-synthetic RentCast fixture
            # would manufacture phantom vendor-drift issues.
            prev = state.get(slug, {})
            sources = sorted(set(prev.get("sources", [])) | set(clean))
            if "rentcast" not in sources:
                print(f"  {slug}: NOT registered as a drift baseline — its "
                      f"RentCast fixture is still synthetic "
                      f"({skips.get('rentcast', 'not recorded')})")
                continue
            state[slug] = {"recorded_at": date.today().isoformat(),
                           "sources": sources}

    if args.confirm:
        harness.RECORDED_STATE.write_text(sanitize.canonical_json(state))
        print(f"\nWrote {wrote} fixture file(s); recording state -> "
              f"{harness.RECORDED_STATE}.")
        print("Now regenerate + review the goldens: "
              "python scripts/regen_golden.py --confirm")
    else:
        print("\nDry run — nothing written. Re-run with --confirm to record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
