"""Layer A — frozen-fixture golden tests for the scoring cascade.

Every corpus address is replayed from disk through the REAL production
cascade (see tests/golden/harness.py) and compared field-by-field against
tests/golden/expected/scores.json. Hermetic: no network (enforced by
conftest's socket guard), no database, and the clock frozen at
tests.golden.clock.AS_OF.

What is asserted per address — deliberately more than the final grade:

* every normalized subscore of the default profile (age, sale, equity,
  garage, income, neighborhood, permit) — composite-only assertions hide
  offsetting errors;
* the composite, pinned exactly as production stores it: ``round(score, 2)``
  (Python round-half-even), applied by pipeline/scorer.py — the goldens hold
  the byte-identical float;
* the grade letter;
* per-field provenance (which source actually supplied each scored input:
  hcad | rentcast | acs | computed | imputed:{basis}@{stage} | missing) — a
  cascade that silently shifts to a fallback can leave the score identical
  while cost and reliability changed;
* data_completeness, the codebase's own thin-file measure.

Null-handling policy pinned here (current behavior, per config
SCORE_MISSING_MODE="zero"): a missing factor input scores 0 — grades blend
lead quality with data richness — and data_completeness reports the gap
separately. Notably, ``garage_spaces = 0`` and ``garage_spaces = NULL``
produce the SAME composite under this mode; they differ in data_completeness
and provenance, and diverge in composite only under the opt-in
"renormalize" mode. Both facts are pinned below rather than "fixed" —
this suite observes behavior, it does not change it.
"""
import copy
import json

import pytest

import config
from pipeline import scoring
from pipeline.scoring import _compute_score

from tests.golden import harness, sanitize

ENTRIES = harness.corpus_entries()
SLUGS = [e["slug"] for e in ENTRIES]
BY_SLUG = {e["slug"]: e for e in ENTRIES}

# One cascade replay per address per module run — the per-aspect tests below
# then stay cheap and fail independently (a provenance break doesn't hide a
# composite break).
_RESULTS: dict = {}


def result_for(slug: str) -> dict:
    if slug not in _RESULTS:
        _RESULTS[slug] = harness.build_result(BY_SLUG[slug])
    return _RESULTS[slug]


@pytest.mark.parametrize("slug", SLUGS)
def test_composite_and_grade(slug, golden_scores):
    got = result_for(slug)
    want = golden_scores[slug]
    assert got["composite"] == want["composite"], (
        f"{slug}: composite {got['composite']} != golden {want['composite']} "
        f"(subscores now: {got['subscores']})")
    assert got["grade"] == want["grade"]


@pytest.mark.parametrize("slug", SLUGS)
def test_subscores(slug, golden_scores):
    got = result_for(slug)["subscores"]
    want = golden_scores[slug]["subscores"]
    assert got == want, (
        f"{slug}: per-factor signals drifted: "
        f"{ {k: (want.get(k), got.get(k)) for k in set(got) | set(want) if got.get(k) != want.get(k)} }")


@pytest.mark.parametrize("slug", SLUGS)
def test_provenance(slug, golden_scores):
    got = result_for(slug)["provenance"]
    want = golden_scores[slug]["provenance"]
    assert got == want, (
        f"{slug}: a factor's supplying source changed — the score may be "
        f"identical while cost/reliability shifted: "
        f"{ {k: (want.get(k), got.get(k)) for k in set(got) | set(want) if got.get(k) != want.get(k)} }")


@pytest.mark.parametrize("slug", SLUGS)
def test_data_completeness_and_geocode(slug, golden_scores):
    got = result_for(slug)
    want = golden_scores[slug]
    assert got["data_completeness"] == want["data_completeness"]
    assert got["geocode"] == want["geocode"]


@pytest.mark.parametrize("slug", SLUGS)
def test_scored_field_values(slug, golden_scores):
    """The raw inputs, not just their signals: a vendor value drifting inside
    a saturated signal (equity far past $100k, permits past 2) leaves every
    subscore untouched — this is the assertion that still catches it."""
    got = result_for(slug)["fields"]
    want = golden_scores[slug]["fields"]
    assert got == want, (
        f"{slug}: scored input values drifted: "
        f"{ {k: (want.get(k), got.get(k)) for k in set(got) | set(want) if got.get(k) != want.get(k)} }")


@pytest.mark.parametrize("slug", SLUGS)
def test_grade_matches_declared_band(slug, golden_scores):
    """addresses.yaml declares the band each non-edge row was chosen for."""
    band = BY_SLUG[slug].get("band")
    if band in ("A", "B", "C", "D"):
        assert golden_scores[slug]["grade"] == band


def test_corpus_and_goldens_cover_same_slugs(golden_scores):
    assert sorted(golden_scores) == sorted(SLUGS)


# ── Null-handling policy (pinned current behavior) ────────────────────────────

GARAGE_ZERO = "16706-clan-macintosh-dr-77084"
GARAGE_NULL = "16710-clan-macintosh-dr-77084"


class TestGarageZeroVsNull:
    """The brief's sharpest edge: 0 and NULL are different facts (a confirmed
    no-garage home vs no data), and the suite pins exactly how much of that
    difference today's scoring surfaces."""

    def test_current_mode_is_zero(self):
        assert (config.SCORE_MISSING_MODE or "zero").lower() == "zero"

    def test_composites_equal_under_zero_mode(self, golden_scores):
        # OBSERVED (not endorsed): under SCORE_MISSING_MODE="zero" the twins
        # score identically — the composite alone cannot distinguish them.
        assert (golden_scores[GARAGE_ZERO]["composite"]
                == golden_scores[GARAGE_NULL]["composite"])

    def test_completeness_and_provenance_differ(self, golden_scores):
        # ... which is why the suite pins the fields that DO distinguish them.
        zero, null = golden_scores[GARAGE_ZERO], golden_scores[GARAGE_NULL]
        assert zero["provenance"]["garage_spaces"] == "rentcast"
        assert null["provenance"]["garage_spaces"] == "missing"
        # A present 0 counts as measured, an absent value does not, so the twins
        # differ by exactly garage's share of the profile. Read that share from
        # the profile the ZIP actually scores on rather than hardcoding the
        # national 0.15 — the Houston calibration rescales every weight.
        garage_weight = harness._scored_profile(
            "77084", {"state": "TX"}).weights["garage"]
        assert (zero["data_completeness"] - null["data_completeness"]
                == pytest.approx(garage_weight, abs=1e-4))

    def test_composites_diverge_under_renormalize(self, frozen, monkeypatch):
        """Under the opt-in renormalize mode the twins DO separate: the null
        row is rescaled over its available weight while the confirmed 0 keeps
        dragging its full weight. Pins that the distinction is one config
        switch away, not a schema change."""
        rows = {}
        for slug in (GARAGE_ZERO, GARAGE_NULL):
            r = result_for(slug)  # ensure fixture replay happened
            assert r is not None
            row = {
                "year_built": 2000, "last_sale_date": None,
                "estimated_equity": 144000, "zip_median_income": 66000,
                "permit_count_24mo": None, "neighborhood_value_ratio": None,
                "garage_spaces": 0 if slug == GARAGE_ZERO else None,
            }
            rows[slug] = row
        monkeypatch.setattr(config, "SCORE_MISSING_MODE", "renormalize")
        scores = {slug: _compute_score(row, config.DEFAULT_WEIGHTS)
                  for slug, row in rows.items()}
        assert scores[GARAGE_NULL] > scores[GARAGE_ZERO]


class TestEquityFallbackPolicy:
    """estimated_equity is always derived; who derives it decides its weight.

    OBSERVED asymmetry, pinned deliberately: when an enrichment stage (HCAD or
    RentCast) writes the flat-fallback equity into the row, the scorer sees a
    populated field and applies FULL equity weight. The
    EQUITY_FALLBACK_SIGNAL_SCALE haircut only fires when the *scorer itself*
    backfills at scoring time. Same basis, different weight, depending on
    which stage got there first. If that ever looks wrong enough to fix, the
    fix changes these goldens — which is the point of having them.
    """

    def test_hcad_fallback_equity_gets_full_weight(self, golden_scores):
        g = golden_scores["4614-pin-oak-forest-dr-77070"]
        assert g["provenance"]["estimated_equity"] == "imputed:fallback@hcad"
        assert g["subscores"]["equity"] == 1.0   # not scaled by 0.5

    def test_scorer_backfill_fallback_is_halved(self, frozen):
        entry = BY_SLUG["4614-pin-oak-forest-dr-77070"]
        payloads = harness.load_payloads(entry["slug"])
        # Strip every path that lets an enrichment stage derive equity, so the
        # scorer's own backfill is the first to touch it.
        payloads = copy.deepcopy(payloads)
        payloads["hcad"]["property_summary"]["estimated_value"] = None
        for record in payloads["rentcast"]:
            record["taxAssessments"] = {}
        result = harness.build_result(entry, payloads)
        # No value anywhere -> no equity at all -> nothing to scale.
        assert result["provenance"]["estimated_equity"] == "missing"
        assert result["subscores"]["equity"] == 0.0

        # Now give the scorer a value but keep enrichment's equity out of the
        # row: value arrives via RentCast, whose own equity derivation is
        # dropped by simulating a pre-populated estimated_value... simplest
        # honest form: hand the scorer stage a row directly.
        row = {"estimated_value": 385000, "year_built": 2003,
               "last_sale_date": None, "estimated_equity": None,
               "garage_spaces": 2, "zip_median_income": 92000,
               "permit_count_24mo": 3, "neighborhood_value_ratio": None}
        update = harness._run_score(dict(row, address=entry["address"],
                                         id=1, zip=entry["zip"]),
                                    str(entry["zip"]), [])
        # Fallback equity written by the scorer: flagged in-memory, halved in
        # the composite. 385000*0.6 = 231000. Compared against the profile the
        # ZIP scores on, so the assertion measures the HAIRCUT and not the
        # market's weights: equity's contribution drops by exactly
        # weight x signal x 100 x (1 - EQUITY_FALLBACK_SIGNAL_SCALE).
        profile = harness._scored_profile(str(entry["zip"]), {"state": "TX"})
        full = dict(row, estimated_equity=231000)
        full_weight_score = scoring.compute_score(full, profile)
        haircut = (profile.weights["equity"]
                   * profile.signal_fns["equity"](231000) * 100
                   * (1 - config.EQUITY_FALLBACK_SIGNAL_SCALE))
        assert update["lead_score"] == pytest.approx(
            round(full_weight_score - haircut, 2), abs=0.01)


# ── Meta-assertions: the acceptance criteria are themselves tested ────────────

class TestSuiteSensitivity:
    """Prove the suite catches the two regression classes it exists for."""

    def test_single_weight_change_moves_many_composites(self, golden_scores):
        """Move 0.05 of weight from age to permit (still sums to 1.0): at
        least 3 addresses' composites must drift from golden — i.e. a weight
        tweak fails >= 3 tests with a readable diff."""
        tweaked = dict(config.DEFAULT_WEIGHTS)
        tweaked["age"] -= 0.05
        tweaked["permit"] += 0.05
        moved = 0
        from tests.golden.clock import frozen_clock
        with frozen_clock():
            for slug in SLUGS:
                got = result_for(slug)
                # Rescore the already-built row-equivalent via subscores: the
                # composite is sum(weight * subscore * 100) by construction.
                rescored = round(sum(
                    tweaked[k] * got["subscores"][k] for k in tweaked) * 100, 2)
                if abs(rescored - golden_scores[slug]["composite"]) >= 0.01:
                    moved += 1
        assert moved >= 3, f"only {moved} addresses moved — corpus too flat"

    def test_cascade_swap_flips_provenance(self, golden_scores):
        """Simulate the cascade silently shifting a field to its fallback
        source: drop HCAD's year_built so RentCast supplies it instead. The
        VALUE can stay identical — the provenance assertion still fails."""
        slug = "4614-pin-oak-forest-dr-77070"
        payloads = copy.deepcopy(harness.load_payloads(slug))
        assert payloads["rentcast"][0]["yearBuilt"] == \
            payloads["hcad"]["property_summary"]["year_built"]
        payloads["hcad"]["property_summary"]["year_built"] = None
        swapped = harness.build_result(BY_SLUG[slug], payloads)
        golden = golden_scores[slug]
        assert swapped["subscores"]["age"] == golden["subscores"]["age"]
        assert swapped["provenance"]["year_built"] == "rentcast"
        assert golden["provenance"]["year_built"] == "hcad"
        assert swapped["provenance"] != golden["provenance"]


# ── Fixture hygiene: no PII, no credentials, canonical serialization ──────────

class TestFixtureHygiene:
    def test_no_forbidden_content_anywhere(self):
        checked = 0
        for path in sorted(harness.VENDOR_DIR.rglob("*.json")):
            text = path.read_text().lower()
            for needle in sanitize.FORBIDDEN_SUBSTRINGS:
                assert needle not in text, f"{path}: contains {needle!r}"
            checked += 1
        assert checked >= len(SLUGS), "fixture tree looks empty"

    def test_rentcast_fixtures_are_allowlisted(self):
        for path in sorted((harness.VENDOR_DIR / "rentcast").glob("*.json")):
            for record in json.loads(path.read_text()):
                extra = set(record) - sanitize.RENTCAST_ALLOWED_KEYS
                assert not extra, f"{path}: non-allowlisted keys {extra}"
                extra_f = (set(record.get("features") or {})
                           - sanitize.RENTCAST_ALLOWED_FEATURES)
                assert not extra_f, f"{path}: non-allowlisted features {extra_f}"

    def test_hcad_fixtures_are_allowlisted(self):
        for path in sorted((harness.VENDOR_DIR / "hcad").glob("*.json")):
            payload = json.loads(path.read_text())
            top = set(payload) - {"property_summary", "extra_features",
                                  "permit_count_24mo"}
            assert not top, f"{path}: unexpected top-level keys {top}"
            summary = payload.get("property_summary") or {}
            extra = set(summary) - sanitize.HCAD_ALLOWED_SUMMARY_KEYS
            assert not extra, f"{path}: non-allowlisted summary keys {extra}"
            features = payload.get("extra_features") or {}
            extra_f = set(features) - sanitize.HCAD_ALLOWED_EXTRA_KEYS
            assert not extra_f, f"{path}: non-allowlisted extra_features keys {extra_f}"

    def test_fixtures_are_canonically_serialized(self):
        """Re-serializing must be a no-op, so re-recording diffs stay clean."""
        for path in sorted(harness.VENDOR_DIR.rglob("*.json")):
            obj = json.loads(path.read_text())
            assert path.read_text() == sanitize.canonical_json(obj), (
                f"{path} is not in canonical form — rewrite it with "
                f"tests.golden.sanitize.write_fixture")

    def test_goldens_are_canonically_serialized(self):
        obj = json.loads(harness.EXPECTED_SCORES.read_text())
        assert harness.EXPECTED_SCORES.read_text() == sanitize.canonical_json(obj)
