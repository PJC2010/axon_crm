"""Golden-file harness — replay recorded vendor payloads through the REAL
production enrichment cascade and score the result.

The point of this module is that it re-implements *nothing*. Every
transformation between a vendor payload and a grade runs the same production
code the pipeline runs, with only the process boundaries (HTTP, Postgres,
DuckDB) replaced by recorded fixtures — the same `unittest.mock.patch`-at-the-
module-boundary convention tests/test_property_enrich.py and tests/test_census.py
already use:

    stage      production entry point                 replayed boundary
    ─────────  ─────────────────────────────────────  ─────────────────────────
    hcad       pipeline.hcad_enrichment.enrich_hcad   hcad_store.query_* + DB
    rentcast   pipeline.property.enrich_property      pipeline.http + DB
    acs        pipeline.census.fetch_income           pipeline.http
    permits    pipeline.permits.enrich_permits        hcad_store.query_permits + DB
    geocode    geocode_provider.CensusGeocoder        pipeline.http
    score      pipeline.scorer.score_zip              DB + snapshots/ML

so a golden mismatch always means *our* logic changed (Layer A) or the
*vendor's* data changed (Layer B) — never that this harness drifted from
production on its own.

Provenance: after each stage the harness diffs the row and records which stage
first filled each scored field. `estimated_equity` is special-cased — it is
always derived (pipeline/equity.py), so its provenance is
``imputed:{basis}@{stage}`` where basis is estimate_equity's own source label
(``balance`` | ``amortized`` | ``fallback``) and stage is who triggered the
derivation (hcad, rentcast, or the scorer's backfill).

Everything here runs under tests.golden.clock.frozen_clock — see that module.
"""
import copy
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import yaml

import config
import pipeline.census as census
import pipeline.equity as equity_mod
import pipeline.geocode_provider as geocode_provider
import pipeline.hcad_enrichment as hcad_enrichment
import pipeline.permits as permits_mod
import pipeline.property as prop
import pipeline.scorer as scorer
import pipeline.scoring as scoring
from pipeline import addr, regional
from pipeline.db import clamp_garage_spaces
from pipeline.profiles import resolve_profile

from tests.golden.clock import frozen_clock

GOLDEN_DIR = Path(__file__).parent
FIXTURES_DIR = GOLDEN_DIR / "fixtures"
VENDOR_DIR = FIXTURES_DIR / "vendor_responses"
ADDRESSES_YAML = FIXTURES_DIR / "addresses.yaml"
EXPECTED_SCORES = GOLDEN_DIR / "expected" / "scores.json"
RECORDED_STATE = FIXTURES_DIR / "recorded.json"

ACCOUNT_ID = 1
VENDOR_KINDS = ("rentcast", "acs", "geocode", "hcad")

# factor key -> row field, for the default profile only (goldens score with
# vertical=None). Derived from config so a renamed field breaks loudly here.
FACTOR_FIELDS = {key: config.FACTOR_META[key]["field"]
                 for key in config.DEFAULT_WEIGHTS}

# Fields whose provenance the goldens pin: the default profile's inputs plus
# estimated_value, which is not scored directly but is the basis every equity
# estimate is derived from — a silent value-source shift moves equity too.
PROVENANCE_FIELDS = tuple(sorted(set(FACTOR_FIELDS.values()) | {"estimated_value"}))


def _scored_profile(zip_code: str, row: dict):
    """The profile score_zip will actually use for this address.

    Every corpus address is in Harris County, so all of them score on the
    Houston calibration (pipeline/regional.py) rather than the national matrix.
    Reading the profile back here is what keeps the pinned subscores reconciled
    with the pinned composite: the market overrides both the weights AND the
    signal thresholds, so scoring a Texas row against the national signal
    functions would report an equity subscore of 1.0 next to a composite that
    was computed from 0.76.
    """
    region = regional.resolve_region(zip_code, row.get("state"))
    return resolve_profile(None, region)


# ── Fixture IO ────────────────────────────────────────────────────────────────

def load_corpus() -> dict:
    with ADDRESSES_YAML.open() as f:
        return yaml.safe_load(f)


def corpus_entries() -> list[dict]:
    return load_corpus()["addresses"]


def vendor_path(kind: str, slug: str) -> Path:
    return VENDOR_DIR / kind / f"{slug}.json"


def load_vendor(kind: str, slug: str):
    """A missing fixture file means "this source has nothing for this address"
    — e.g. the condo with no parcel-level HCAD match simply has no hcad file."""
    path = vendor_path(kind, slug)
    if not path.exists():
        return None
    import json
    with path.open() as f:
        return json.load(f)


def load_payloads(slug: str) -> dict:
    return {kind: load_vendor(kind, slug) for kind in VENDOR_KINDS}


# ── Boundary stubs ────────────────────────────────────────────────────────────

class _StubConn:
    def close(self):
        pass

    def commit(self):
        pass


def _capturing_upsert(store: list):
    def fake_upsert(conn, rows, account_id, fill_only=False):
        store.extend(rows)
        return len(rows)
    return fake_upsert


def _recording_equity(sources: list):
    """estimate_equity pass-through that records which basis fired. The real
    function does all the math — this only observes the `source` label."""
    def rec(value, last_sale_price=None, last_sale_date=None,
            mortgage_balance=None, return_source=False):
        eq, src = equity_mod.estimate_equity(
            value, last_sale_price, last_sale_date, mortgage_balance,
            return_source=True)
        sources.append(src)
        return (eq, src) if return_source else eq
    return rec


def apply_update(row: dict, update: dict) -> None:
    """Mirror pipeline.db.upsert_properties write semantics onto an in-memory
    row: None is never written, garage_spaces is clamped at write time, and
    enrichment_flags merge (`||`) instead of replacing."""
    for key, value in update.items():
        if value is None:
            continue
        if key == "enrichment_flags":
            merged = dict(row.get("enrichment_flags") or {})
            merged.update(value)
            row["enrichment_flags"] = merged
        elif key == "garage_spaces":
            row[key] = clamp_garage_spaces(value)
        else:
            row[key] = value


def _note_provenance(provenance: dict, before: dict, row: dict, stage: str,
                     equity_sources: list) -> None:
    for field in PROVENANCE_FIELDS:
        if provenance.get(field) is not None:
            continue
        if before.get(field) is None and row.get(field) is not None:
            if field == "estimated_equity":
                basis = equity_sources[-1] if equity_sources else "unknown"
                provenance[field] = f"imputed:{basis}@{stage}"
            else:
                provenance[field] = stage


# ── Stage drivers (each runs the real production entry point) ─────────────────

def _run_hcad(row: dict, fixture, zip_code: str, equity_sources: list) -> None:
    if not fixture:
        return
    summary = fixture.get("property_summary")
    extra = fixture.get("extra_features")
    if not summary and not extra:
        return
    key = addr.normalize(row["address"])
    hcad_map = {key: _typed_hcad_summary(summary)} if summary else {}
    ef_map = {key: dict(extra)} if extra else {}

    captured: list[dict] = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(
            hcad_enrichment.hcad_store, "query_properties", lambda z: hcad_map))
        stack.enter_context(patch.object(
            hcad_enrichment.hcad_store, "query_extra_features", lambda z: ef_map))
        stack.enter_context(patch.object(
            hcad_enrichment, "get_conn", lambda: _StubConn()))
        stack.enter_context(patch.object(
            hcad_enrichment, "fetch_by_zip", lambda c, z, a: [row]))
        stack.enter_context(patch.object(
            hcad_enrichment, "upsert_properties", _capturing_upsert(captured)))
        stack.enter_context(patch.object(
            hcad_enrichment, "record_findings", lambda *a, **k: None))
        stack.enter_context(patch.object(
            hcad_enrichment, "estimate_equity", _recording_equity(equity_sources)))
        hcad_enrichment.enrich_hcad(zip_code, ACCOUNT_ID)
    for update in captured:
        apply_update(row, update)


def _typed_hcad_summary(summary: dict) -> dict:
    """query_properties returns last_sale_date as a datetime.date (DuckDB DATE
    column); the JSON fixture stores ISO text. Convert through the *currently
    bound* date class so under frozen_clock the value is a FrozenDate instance
    and enrich_hcad's `isinstance(sale_date, date)` branch behaves exactly as
    in production."""
    out = dict(summary)
    # PII columns are stripped from fixtures (sanitize.py); production would
    # supply them, but fill-only _backfill treats None as "nothing to write".
    out.setdefault("owner_name", None)
    out.setdefault("mailing_address", None)
    sale = out.get("last_sale_date")
    if isinstance(sale, str):
        out["last_sale_date"] = hcad_enrichment.date.fromisoformat(sale[:10])
    return out


def _run_rentcast(row: dict, fixture, zip_code: str, equity_sources: list) -> None:
    if fixture is None:
        return
    captured: list[dict] = []
    source_cfg = {"rentcast": {"key": "golden-replay", "flag": {"property": "rentcast"},
                               "delay": 0, "cap": None}}
    with ExitStack() as stack:
        stack.enter_context(patch.object(prop, "_SOURCE_CONFIG", source_cfg))
        stack.enter_context(patch.object(prop, "PROPERTY_FIELD_SOURCES", ["rentcast"]))
        stack.enter_context(patch.object(
            prop, "get_json_result", lambda *a, **k: (fixture, True)))
        stack.enter_context(patch.object(prop, "get_conn", lambda: _StubConn()))
        stack.enter_context(patch.object(
            prop, "fetch_missing_any", lambda *a, **k: [row]))
        stack.enter_context(patch.object(
            prop, "upsert_properties", _capturing_upsert(captured)))
        stack.enter_context(patch.object(
            prop, "record_findings", lambda *a, **k: None))
        # map_record/consistent_derived call estimate_equity via the reconcile
        # module; record the basis without changing the math.
        import pipeline.reconcile as reconcile
        stack.enter_context(patch.object(
            reconcile, "estimate_equity", _recording_equity(equity_sources)))
        prop.enrich_property(zip_code, ACCOUNT_ID)
    for update in captured:
        apply_update(row, update)


def _run_acs(row: dict, fixture, zip_code: str) -> None:
    if fixture is None:
        return
    with patch.object(census, "get_json", lambda *a, **k: fixture):
        income = census.fetch_income(zip_code)
    if income is not None:
        apply_update(row, {"zip_median_income": income,
                           "enrichment_flags": {"census": "acs5_2022"}})


def _run_permits(row: dict, fixture, zip_code: str) -> None:
    count = (fixture or {}).get("permit_count_24mo")
    if count is None:
        # Production query_permits only emits addresses that HAVE permits
        # (SQL GROUP BY over matching rows), so "no permits" is an absent key,
        # not a zero — the row's permit_count_24mo stays NULL.
        return
    permit_map = {addr.normalize(row["address"]): count}
    captured: list[dict] = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(
            permits_mod.hcad_store, "query_permits", lambda z: permit_map))
        stack.enter_context(patch.object(
            permits_mod, "get_conn", lambda: _StubConn()))
        stack.enter_context(patch.object(
            permits_mod, "fetch_by_zip", lambda c, z, a: [row]))
        stack.enter_context(patch.object(
            permits_mod, "upsert_properties", _capturing_upsert(captured)))
        permits_mod.enrich_permits(zip_code, ACCOUNT_ID)
    for update in captured:
        apply_update(row, update)


def _run_geocode(entry: dict, fixture):
    """Pin the Census geocoder contract: first addressMatches entry wins, with
    confidence 0.9 for an exact match and 0.6 otherwise. Coordinates don't feed
    the six factors, but a resolver change (e.g. ambiguous addresses starting
    to resolve differently) should fail loudly, not silently move map pins.

    The one-line request string is built by the production helper
    (geocode_provider._full_address) so the recorded/replayed request can
    never diverge from what process_queue actually sends."""
    if fixture is None:
        return None
    oneline = geocode_provider._full_address({
        "address": entry["address"], "city": entry.get("city", "HOUSTON"),
        "state": "TX", "zip": str(entry["zip"])})
    with patch.object(geocode_provider, "get_json", lambda *a, **k: fixture):
        result = geocode_provider.CensusGeocoder().geocode(oneline)
    if result is None:
        return {"resolved": False}
    lat, lng, confidence = result
    return {"resolved": True, "latitude": round(lat, 6),
            "longitude": round(lng, 6), "confidence": confidence}


def _run_score(row: dict, zip_code: str, equity_sources: list) -> dict:
    captured: list[dict] = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(scorer, "get_conn", lambda: _StubConn()))
        stack.enter_context(patch.object(
            scorer, "fetch_by_zip", lambda c, z, a: [row]))
        stack.enter_context(patch.object(
            scorer, "upsert_properties", _capturing_upsert(captured)))
        stack.enter_context(patch.object(
            scorer, "write_score_snapshots", lambda *a, **k: None))
        stack.enter_context(patch.object(scorer, "_apply_ml", lambda *a, **k: None))
        stack.enter_context(patch.object(
            scorer, "estimate_equity", _recording_equity(equity_sources)))
        scorer.score_zip(zip_code, ACCOUNT_ID, vertical=None)
    assert len(captured) == 1, "score_zip should write exactly one update"
    return captured[0]


# ── Public entry points ───────────────────────────────────────────────────────

def new_row(entry: dict) -> dict:
    """The row as the seed step would leave it: address identity only."""
    return {
        "id": 1,
        "account_id": ACCOUNT_ID,
        "address": entry["address"],
        "zip": str(entry["zip"]),
        "city": entry.get("city", "HOUSTON"),
        "state": "TX",
        "enrichment_flags": {},
    }


def build_result(entry: dict, payloads: dict | None = None) -> dict:
    """Replay one corpus address through the full cascade and score it.

    Returns the golden-comparable result::

        {
          "composite":         float,   # lead_score as production stores it
          "grade":             "A".."D",
          "data_completeness": float,
          "subscores":         {factor: signal 0.0-1.0, one per default-profile factor},
          "provenance":        {field: "hcad"|"rentcast"|"acs"|"computed"
                                       |"imputed:{basis}@{stage}"|"missing"},
          "geocode":           {...} | None,
        }

    `payloads` defaults to the on-disk fixtures for entry["slug"]; the live
    contract tests pass freshly fetched payloads instead, so drift is measured
    through the exact same code path the goldens were built with.
    """
    if payloads is None:
        payloads = load_payloads(entry["slug"])
    zip_code = str(entry["zip"])

    with frozen_clock():
        row = new_row(entry)
        provenance: dict = {}
        equity_sources: list = []

        for stage, runner in (("hcad", _run_hcad), ("rentcast", _run_rentcast)):
            before = copy.deepcopy(row)
            runner(row, payloads.get(stage), zip_code, equity_sources)
            _note_provenance(provenance, before, row, stage, equity_sources)

        before = copy.deepcopy(row)
        _run_acs(row, payloads.get("acs"), zip_code)
        _note_provenance(provenance, before, row, "acs", equity_sources)

        before = copy.deepcopy(row)
        _run_permits(row, payloads.get("hcad"), zip_code)
        # County permit DB — same public record as the assessor roll.
        _note_provenance(provenance, before, row, "hcad", equity_sources)

        geocode = _run_geocode(entry, payloads.get("geocode"))

        # neighborhood_value_ratio is computed inside Postgres from geohash
        # cells (pipeline/neighborhood.py) — there is no vendor payload to
        # replay, so the corpus entry injects it directly when present.
        ratio = entry.get("neighborhood_value_ratio")
        if ratio is not None:
            row["neighborhood_value_ratio"] = ratio
            provenance["neighborhood_value_ratio"] = "computed"

        before = copy.deepcopy(row)
        update = _run_score(row, zip_code, equity_sources)
        _note_provenance(provenance, before, row, "scorer", equity_sources)

        for field in PROVENANCE_FIELDS:
            provenance.setdefault(field, "missing")

        profile = _scored_profile(zip_code, row)
        subscores = {
            factor: round(profile.signal_fns[factor](
                row.get(profile.factor_meta[factor]["field"])), 6)
            for factor, weight in profile.weights.items() if weight
        }
        # The equity signal the composite actually used is scaled when the
        # row's equity is the flat fallback — whichever stage wrote it, read
        # through the same provenance rule the engine uses; report that in
        # the subscore so composite == Σ weight×subscore×100 always holds.
        if scoring.equity_is_fallback(row):
            subscores["equity"] = round(
                subscores["equity"] * config.EQUITY_FALLBACK_SIGNAL_SCALE, 6)

        # The raw scored inputs, golden-pinned alongside their signals: a
        # vendor value drifting inside a saturated signal (equity far past
        # $100k, permits past 2) moves nothing else, and the live contract
        # tests range-check these directly (estimated_equity >= 0, etc.).
        fields = {field: _jsonable_value(row.get(field))
                  for field in PROVENANCE_FIELDS}

    return {
        "composite": update["lead_score"],
        "grade": update["score_grade"],
        "data_completeness": update["enrichment_flags"]["data_completeness"],
        "fields": fields,
        "subscores": subscores,
        "provenance": provenance,
        "geocode": geocode,
        # The basis the composite's equity signal was scaled on, as the stored
        # row now carries it (pipeline/equity.py::stored_equity_source) — the
        # stamp is what lets a rescore reproduce the golden composite.
        "equity_source": equity_mod.stored_equity_source(row),
    }


def _jsonable_value(value):
    import datetime
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str):
        return value[:10] if _looks_like_iso_datetime(value) else value
    return value


def _looks_like_iso_datetime(value: str) -> bool:
    # RentCast dates arrive as "2025-11-10T00:00:00.000Z"; pin the day only,
    # matching how every consumer slices [:10].
    return len(value) > 10 and value[4] == "-" and value[7] == "-" and "T" in value


def build_all(entries=None) -> dict:
    """slug -> build_result, for regen and the meta-tests."""
    entries = entries if entries is not None else corpus_entries()
    return {e["slug"]: build_result(e) for e in entries}
