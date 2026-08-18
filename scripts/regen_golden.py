#!/usr/bin/env python
"""Regenerate tests/golden/expected/scores.json from the committed fixtures.

The rule that makes goldens worth having: a changed golden file is a
reviewable diff in a PR, never an automatic update. If a score moves, a human
looks at why. Accordingly:

  * ``--confirm`` is required — running without it prints the diff and writes
    nothing.
  * This script refuses to run in CI (any of CI/GITHUB_ACTIONS set). CI's job
    is to *compare* against the committed goldens, never to move them.

Usage:
    python scripts/regen_golden.py            # dry run: show what would change
    python scripts/regen_golden.py --confirm  # write expected/scores.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.golden import harness              # noqa: E402
from tests.golden.sanitize import canonical_json  # noqa: E402


def _num(value, spec: str) -> str:
    """Format a possibly-missing numeric side; a factor/field present on only
    one side (weight-profile changes do this) renders as '-', not a crash."""
    return "-" if value is None else format(value, spec)


def _diff_rows(old: dict, new: dict) -> list[tuple]:
    """(slug, factor, old, new, delta, grade-transition) rows for the summary
    table — one row per changed subscore/field/provenance entry, so the
    reviewer sees *which factor* moved a score, not just that it moved."""
    rows = []
    for slug in sorted(set(old) | set(new)):
        o, n = old.get(slug), new.get(slug)
        if o is None or n is None:
            rows.append((slug, "(entire address)",
                         "-" if o is None else f"{o['composite']:.2f}",
                         "-" if n is None else f"{n['composite']:.2f}",
                         "", ""))
            continue
        grade = (f"{o['grade']} -> {n['grade']}"
                 if o["grade"] != n["grade"] else o["grade"])
        for factor in sorted(set(o["subscores"]) | set(n["subscores"])):
            ov = o["subscores"].get(factor)
            nv = n["subscores"].get(factor)
            if ov != nv:
                delta = (f"{nv - ov:+.4f}"
                         if ov is not None and nv is not None else "")
                rows.append((slug, factor, _num(ov, ".4f"), _num(nv, ".4f"),
                             delta, grade))
        for section in ("provenance", "fields", "geocode"):
            os_, ns_ = o.get(section) or {}, n.get(section) or {}
            for key in sorted(set(os_) | set(ns_)):
                if os_.get(key) != ns_.get(key):
                    rows.append((slug, f"{section}:{key}",
                                 str(os_.get(key)), str(ns_.get(key)),
                                 "", grade))
        if o.get("data_completeness") != n.get("data_completeness"):
            rows.append((slug, "data_completeness",
                         _num(o.get("data_completeness"), ".4f"),
                         _num(n.get("data_completeness"), ".4f"), "", grade))
        if o["composite"] != n["composite"]:
            rows.append((slug, "composite", f"{o['composite']:.2f}",
                         f"{n['composite']:.2f}",
                         f"{n['composite'] - o['composite']:+.2f}", grade))
    return rows


def _print_table(rows: list[tuple], changed: bool) -> None:
    if not rows:
        if changed:
            print("Goldens changed outside the tabled fields — inspect the "
                  "git diff of expected/scores.json directly.")
        else:
            print("No changes — expected/scores.json already matches the "
                  "fixtures.")
        return
    headers = ("slug", "factor", "old", "new", "delta", "grade")
    widths = [max(len(str(r[i])) for r in rows + [headers])
              for i in range(len(headers))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*(str(c) for c in row)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true",
                        help="actually write expected/scores.json")
    args = parser.parse_args()

    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        print("refusing to regenerate goldens in CI — goldens change only in "
              "reviewed commits", file=sys.stderr)
        return 2

    old = {}
    if harness.EXPECTED_SCORES.exists():
        old = json.loads(harness.EXPECTED_SCORES.read_text())

    new = harness.build_all()

    _print_table(_diff_rows(old, new), changed=old != new)

    if not args.confirm:
        if old != new:
            print("\nDry run — nothing written. Re-run with --confirm to "
                  "update expected/scores.json.")
            return 1
        return 0

    harness.EXPECTED_SCORES.parent.mkdir(parents=True, exist_ok=True)
    harness.EXPECTED_SCORES.write_text(canonical_json(new))
    print(f"\nWrote {harness.EXPECTED_SCORES} "
          f"({len(new)} addresses). Review the diff before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
