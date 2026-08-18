"""Layer B — live vendor contract tests. Nightly cron only, never on PRs.

For each corpus address whose fixtures were recorded from the real vendors
(fixtures/recorded.json, maintained by scripts/refresh_fixtures.py), this
module re-fetches the payloads live, sanitizes them exactly as recording
does, replays them through the SAME harness the goldens were built with —
frozen clock included, so time decay can't masquerade as vendor drift — and
asserts:

* **Shape**: every field the scorer reads is present where expected and of
  the expected type.
* **Plausible range**: home_age 0-150, zip_median_income $15k-$350k,
  estimated_equity >= 0, garage_spaces 0-MAX_GARAGE_SPACES, coordinates
  inside greater Harris County.
* **Drift vs fixture**: composite moved more than 2.0 points, any grade
  flip, or any provenance change -> fail.

Addresses still carrying synthetic (hand-authored) fixtures are SKIPPED with
an explicit reason — a synthetic baseline cannot measure vendor drift. Record
real baselines first:  python scripts/refresh_fixtures.py --confirm

A markdown drift table is written to $GITHUB_STEP_SUMMARY (and to
$CONTRACT_REPORT_PATH if set) at session end; the nightly workflow posts it
into the "Vendor drift detected" issue.
"""
import json
import numbers
import os
from pathlib import Path

import pytest

import config

from tests.golden import harness, recording, sanitize
from tests.golden.clock import AS_OF

pytestmark = pytest.mark.live

ENTRIES = harness.corpus_entries()
BY_SLUG = {e["slug"]: e for e in ENTRIES}
SLUGS = [e["slug"] for e in ENTRIES]

HARRIS_LAT = (29.3, 30.3)
HARRIS_LNG = (-96.1, -94.7)


def _recorded_state() -> dict:
    if harness.RECORDED_STATE.exists():
        return json.loads(harness.RECORDED_STATE.read_text())
    return {}


@pytest.fixture(scope="session")
def recorded():
    return _recorded_state()


@pytest.fixture(scope="session")
def drift_report():
    """Collects one row per checked address; written out at session end."""
    rows: list[dict] = []
    yield rows
    if not rows:
        return
    lines = [
        f"### Vendor contract run — {len(rows)} address(es), as_of {AS_OF}",
        "",
        "| slug | composite (golden -> live) | delta | grade | provenance changes | notes |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: -abs(r["delta"])):
        lines.append(
            f"| {r['slug']} | {r['golden_composite']:.2f} -> "
            f"{r['live_composite']:.2f} | {r['delta']:+.2f} | {r['grade']} | "
            f"{r['provenance_changes'] or '—'} | {r['notes'] or '—'} |")
    text = "\n".join(lines) + "\n"
    for env in ("CONTRACT_REPORT_PATH", "GITHUB_STEP_SUMMARY"):
        path = os.environ.get(env)
        if path:
            with Path(path).open("a") as f:
                f.write(text)


@pytest.fixture(scope="session")
def live(recorded):
    """Lazy per-slug live fetch + harness replay, shared across tests so each
    address is fetched from the vendors exactly once per run."""
    cache: dict = {}

    def get(slug: str):
        if slug in cache:
            return cache[slug]
        entry = BY_SLUG[slug]
        # A baseline counts only when its RentCast half was recorded live —
        # the nightly re-fetches RentCast, and drift measured against a
        # synthetic RentCast fixture would be fiction (refresh_fixtures.py
        # enforces the same rule when writing recorded.json).
        if "rentcast" not in (recorded.get(slug) or {}).get("sources", []):
            pytest.skip(
                f"{slug}: fixtures are synthetic — no live-recorded baseline "
                f"to measure drift against. Run scripts/refresh_fixtures.py "
                f"--confirm with vendor keys set, review, and commit.")
        raw, skips = recording.fetch_all(entry)
        payloads = {
            "rentcast": (sanitize.sanitize_rentcast(raw["rentcast"])
                         if "rentcast" in raw else None),
            "acs": raw.get("acs"),
            "geocode": raw.get("geocode"),
            # Without the county database live, the committed HCAD fixture is
            # the replay input — HCAD drift is only measured where the store
            # is reachable, and the report row says so.
            "hcad": (sanitize.sanitize_hcad(raw["hcad"]) if "hcad" in raw
                     else harness.load_vendor("hcad", slug)),
        }
        if "rentcast" not in raw:
            pytest.skip(f"{slug}: {skips.get('rentcast')}")
        result = harness.build_result(entry, payloads)
        cache[slug] = (result, payloads, skips)
        return cache[slug]

    return get


def _require_number(value, what, lo=None, hi=None, allow_none=False):
    if value is None:
        assert allow_none, f"{what} is missing"
        return
    assert isinstance(value, numbers.Real) and not isinstance(value, bool), \
        f"{what} is {type(value).__name__}, expected a number"
    if lo is not None:
        assert value >= lo, f"{what}={value} below plausible floor {lo}"
    if hi is not None:
        assert value <= hi, f"{what}={value} above plausible ceiling {hi}"


@pytest.mark.parametrize("slug", SLUGS)
def test_shape_and_plausible_ranges(slug, live):
    result, payloads, _ = live(slug)

    row_fields = result["subscores"]
    assert set(row_fields) == set(config.DEFAULT_WEIGHTS), \
        "scorer no longer reads the default factor set"
    for factor, signal in row_fields.items():
        _require_number(signal, f"subscore[{factor}]", lo=0.0, hi=1.0)

    records = payloads.get("rentcast") or []
    for record in records:
        yb = record.get("yearBuilt")
        if yb is not None:
            age = AS_OF.year - yb
            assert 0 <= age <= 150, f"home_age {age} outside 0-150"
        _require_number(record.get("squareFootage"), "squareFootage",
                        lo=100, hi=100_000, allow_none=True)
        features = record.get("features") or {}
        _require_number(features.get("garageSpaces"), "garageSpaces",
                        lo=0, hi=config.MAX_GARAGE_SPACES, allow_none=True)
        _require_number(record.get("latitude"), "latitude",
                        lo=HARRIS_LAT[0], hi=HARRIS_LAT[1], allow_none=True)
        _require_number(record.get("longitude"), "longitude",
                        lo=HARRIS_LNG[0], hi=HARRIS_LNG[1], allow_none=True)

    acs = payloads.get("acs")
    if acs is not None:
        from pipeline.census import parse_income
        income = parse_income(acs)
        _require_number(income, "zip_median_income",
                        lo=15_000, hi=350_000, allow_none=True)

    # The scorer-read fields themselves, from the replayed row (brief §6):
    # present-where-expected, typed, and inside plausible ranges.
    fields = result["fields"]
    yb = fields.get("year_built")
    if yb is not None:
        _require_number(yb, "year_built",
                        lo=AS_OF.year - 150, hi=AS_OF.year + 1)
    _require_number(fields.get("estimated_equity"), "estimated_equity",
                    lo=0, allow_none=True)
    _require_number(fields.get("estimated_value"), "estimated_value",
                    lo=10_000, hi=50_000_000, allow_none=True)
    _require_number(fields.get("garage_spaces"), "garage_spaces",
                    lo=0, hi=config.MAX_GARAGE_SPACES, allow_none=True)
    _require_number(fields.get("zip_median_income"), "zip_median_income",
                    lo=15_000, hi=350_000, allow_none=True)
    _require_number(fields.get("permit_count_24mo"), "permit_count_24mo",
                    lo=0, hi=200, allow_none=True)

    _require_number(result["composite"], "composite", lo=0, hi=100)
    assert result["grade"] in "ABCD"
    for field, source in result["provenance"].items():
        assert isinstance(source, str) and source, f"provenance[{field}] empty"


@pytest.mark.parametrize("slug", SLUGS)
def test_drift_vs_golden(slug, live, golden_scores, drift_report):
    result, payloads, skips = live(slug)
    golden = golden_scores[slug]

    delta = result["composite"] - golden["composite"]
    prov_changes = ", ".join(
        f"{field}: {golden['provenance'].get(field)} -> {source}"
        for field, source in sorted(result["provenance"].items())
        if source != golden["provenance"].get(field))
    notes = "; ".join(f"{k}: {v}" for k, v in sorted(skips.items()))
    drift_report.append({
        "slug": slug,
        "golden_composite": golden["composite"],
        "live_composite": result["composite"],
        "delta": delta,
        "grade": (golden["grade"] if result["grade"] == golden["grade"]
                  else f"{golden['grade']} -> {result['grade']} FLIPPED"),
        "provenance_changes": prov_changes,
        "notes": notes,
    })

    assert abs(delta) <= 2.0, (
        f"{slug}: composite drifted {delta:+.2f} (>{2.0}) vs the recorded "
        f"baseline — vendor data changed underneath us")
    assert result["grade"] == golden["grade"], (
        f"{slug}: grade flipped {golden['grade']} -> {result['grade']}")
    assert not prov_changes, (
        f"{slug}: provenance shifted ({prov_changes}) — same score can hide "
        f"a cascade falling through to a different source")
