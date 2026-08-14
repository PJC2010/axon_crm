"""
Tests for pipeline/county_build.py — the county-wide parcels cache build.

The spec's two hard guarantees — a bulk build can never spend geocoding money,
and can never materialize tenant rows — are structural (they hold because of
what the build modules import and write), so these tests assert them from the
SOURCE, plus the per-ZIP orchestration order and the loud match-rate gate.
No database, no network.
"""
import inspect
import re

import pytest

from pipeline import county_build, parcel_centroids, parcels
from pipeline.addr import sql_has_situs


class _FakeCursor:
    def __init__(self, rows=None, rowcount=0):
        self.statements: list[tuple] = []
        self._rows = rows or []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    @property
    def sql(self):
        return self.statements[0][0] if self.statements else None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        self.commits += 1


_REPORT_OK = {
    "parcels_total": 100, "with_apn": 96, "apn_matched": 95,
    "with_coords": 98, "geocode_sources": [("hcad_centroid", 95)],
    "hcad_properties": 100, "hcad_parcel_centroids": 95,
    "unmatched_sample": [],
}


# ── Orchestration ─────────────────────────────────────────────────────────────

def _patched_build(monkeypatch, calls):
    monkeypatch.setattr(parcels, "ensure_from_hcad",
                        lambda c, z: calls.append(("ensure", z)) or 1)
    monkeypatch.setattr(parcels, "fill_coords_from_centroids",
                        lambda c, z: calls.append(("fill", z)) or 1)
    monkeypatch.setattr(parcels, "coverage",
                        lambda c, z: {"parcels": 1, "geocoded": 1})
    monkeypatch.setattr(county_build, "census_fill_parcels",
                        lambda c, z: calls.append(("census", z)) or 0)
    monkeypatch.setattr(county_build, "report", lambda c: dict(_REPORT_OK))


def test_build_runs_ensure_then_fill_then_census_per_zip(monkeypatch):
    calls = []
    _patched_build(monkeypatch, calls)
    rep = county_build.build(object(), zips=["77001", "77002"], analyze_every=0)
    assert calls == [("ensure", "77001"), ("fill", "77001"), ("census", "77001"),
                     ("ensure", "77002"), ("fill", "77002"), ("census", "77002")]
    assert rep["match_rate"] == pytest.approx(95 / 96)


def test_build_can_skip_the_census_fallback(monkeypatch):
    calls = []
    _patched_build(monkeypatch, calls)
    county_build.build(object(), zips=["77001"], census_fallback=False,
                       analyze_every=0)
    assert ("census", "77001") not in calls
    assert ("fill", "77001") in calls


def test_build_start_after_and_limit_slice_the_zip_list(monkeypatch):
    calls = []
    _patched_build(monkeypatch, calls)
    monkeypatch.setattr(county_build, "county_zips",
                        lambda c: [("77001", 5), ("77002", 5), ("77003", 5),
                                   ("77004", 5)])
    county_build.build(object(), start_after="77001", limit_zips=2,
                       analyze_every=0)
    assert [z for tag, z in calls if tag == "ensure"] == ["77002", "77003"]


def test_build_fails_loud_below_the_match_rate_gate(monkeypatch):
    """A silently low-matching APN join is the design's top failure mode — the
    build must raise, not report success, and must surface the sample."""
    calls = []
    _patched_build(monkeypatch, calls)
    bad = dict(_REPORT_OK, apn_matched=50,
               unmatched_sample=[("77001", "123 MAIN ST", "0000123400056")])
    monkeypatch.setattr(county_build, "report", lambda c: bad)
    with pytest.raises(RuntimeError) as exc:
        county_build.build(object(), zips=["77001"], analyze_every=0)
    assert "52.1%" in str(exc.value)


def test_assert_match_rate_passes_at_the_threshold():
    rate = county_build.assert_match_rate(
        {"with_apn": 100, "apn_matched": 90, "unmatched_sample": []}, 0.90)
    assert rate == pytest.approx(0.90)


def test_assert_match_rate_treats_an_empty_build_as_failure():
    """Zero APN rows means nothing was built — success would be a lie."""
    with pytest.raises(RuntimeError):
        county_build.assert_match_rate(
            {"with_apn": 0, "apn_matched": 0, "unmatched_sample": []}, 0.90)


# ── census_fill_parcels ───────────────────────────────────────────────────────

def test_census_candidates_are_ungeocoded_parcels_with_a_real_situs():
    cur = _FakeCursor(rows=[])
    assert county_build.census_fill_parcels(_FakeConn(cur), "77001") == 0
    assert "FROM parcels" in cur.sql
    assert "latitude IS NULL" in cur.sql
    # No geocoder can place a "0 ACKLEY DR" no-situs parcel — excluded up
    # front with the shared rule, not a hand-rolled copy.
    assert sql_has_situs("address") in cur.sql


def test_census_fill_survives_a_failed_batch(monkeypatch):
    """A dead endpoint must cost this ZIP's fill, not the run — rerun heals."""
    cur = _FakeCursor(rows=[(1, "123 MAIN ST", "HOUSTON", "TX", "77001")])
    monkeypatch.setattr(county_build, "post_file_text", lambda *a, **k: None)
    assert county_build.census_fill_parcels(_FakeConn(cur), "77001") == 0
    assert len(cur.statements) == 1   # the SELECT; no UPDATE was attempted


def test_census_fill_updates_parcels_and_only_parcels(monkeypatch):
    cur = _FakeCursor(rows=[(1, "123 MAIN ST", "HOUSTON", "TX", "77001")],
                      rowcount=1)
    conn = _FakeConn(cur)
    monkeypatch.setattr(
        county_build, "post_file_text",
        lambda *a, **k: '"1","123 MAIN ST","Match","Exact",'
                        '"123 MAIN ST, HOUSTON, TX, 77001","-95.2,29.9",'
                        '"111","L"\n')
    captured = {}

    def fake_execute_values(cur_, sql, values):
        captured["sql"], captured["values"] = sql, values

    monkeypatch.setattr(county_build, "execute_values", fake_execute_values)
    assert county_build.census_fill_parcels(conn, "77001") == 1

    assert "UPDATE parcels" in captured["sql"]
    assert "'census'" in captured["sql"]
    # Race guard: a promoted/centroid coordinate that landed meanwhile wins.
    assert "p.latitude IS NULL" in captured["sql"]
    # Census answers "lon,lat"; the row must arrive as (id, lat, lng, conf).
    assert captured["values"] == [(1, 29.9, -95.2, 0.9)]
    assert conn.commits == 1


# ── The structural guarantees ─────────────────────────────────────────────────

def _build_sources() -> str:
    return "".join(inspect.getsource(m)
                   for m in (county_build, parcels, parcel_centroids))


def test_build_path_never_imports_a_paid_geocode_module():
    """FREE BY CONSTRUCTION: pipeline.geocode (Google fallback) and
    geocode_provider must be unreachable from the build path. geocode_batch —
    the free Census CSV codec — is the one allowed geocode import. Only real
    import statements are scanned; prose about the rule may name the module."""
    for line in _build_sources().splitlines():
        if not line.strip().startswith(("import ", "from ")):
            continue
        assert not re.search(r"\bgeocode\b(?!_batch)", line), line
        assert "geocode_provider" not in line, line


def test_build_path_never_references_a_paid_key():
    src = _build_sources()
    for key in ("GOOGLE_GEOCODE_KEY", "RENTCAST_API_KEY", "CONTACT_API_KEY",
                "DEMO_API_KEY"):
        assert key not in src, f"{key} must be unreachable from the build path"


def test_build_modules_never_touch_tenant_rows():
    """The multi-tenant-explosion guard: a county build must be incapable of
    materializing properties — per-account seeding stays on-demand."""
    src = (inspect.getsource(county_build)
           + inspect.getsource(parcel_centroids))
    assert "seed_account" not in src
    assert "INSERT INTO properties" not in src
    assert "UPDATE properties" not in src
