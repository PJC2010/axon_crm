"""
Tests for pipeline/seed.py seed() — the source-dispatch layer.

Pure/offline: the three concrete seeders are stubbed, so this only locks in
*which* source a given set of arguments routes to. The important guarantee is
that a caller can pick the free local HCAD seed instead of the paid RentCast
address scan (per-run control from the UI via RunCreate.seed_source).
"""
import pytest

import pipeline.seed as seed_mod
from pipeline.seed import seed


@pytest.fixture
def routes(monkeypatch):
    """Stub every seeder; return the list that records which one ran."""
    calls: list[tuple] = []
    monkeypatch.setattr(seed_mod, "seed_from_hcad_zip",
                        lambda z, a, limit=None: calls.append(("hcad_zip", z)) or 0)
    monkeypatch.setattr(seed_mod, "seed_from_rentcast",
                        lambda z, a, limit=None: calls.append(("rentcast", z)) or 0)
    monkeypatch.setattr(seed_mod, "seed_from_hcad",
                        lambda r, z, a, limit=None: calls.append(("hcad_region", r)) or 0)
    monkeypatch.setattr(seed_mod, "seed_from_csv",
                        lambda p, a, z=None: calls.append(("csv", p)) or 0)
    return calls


def test_explicit_hcad_uses_free_local_data(routes):
    seed("77004", 1, seed_source="hcad")
    assert routes == [("hcad_zip", "77004")]


def test_explicit_rentcast_uses_paid_scan(routes):
    seed("77004", 1, seed_source="rentcast")
    assert routes == [("rentcast", "77004")]


def test_seed_source_is_case_and_space_insensitive(routes):
    seed("77004", 1, seed_source="  HCAD  ")
    assert routes == [("hcad_zip", "77004")]


def test_none_falls_back_to_configured_default(routes, monkeypatch):
    monkeypatch.setattr(seed_mod, "SEED_SOURCE", "rentcast")
    seed("77004", 1, seed_source=None)
    assert routes == [("rentcast", "77004")]

    routes.clear()
    monkeypatch.setattr(seed_mod, "SEED_SOURCE", "hcad")
    seed("77004", 1, seed_source=None)
    assert routes == [("hcad_zip", "77004")]


def test_unset_default_falls_back_to_rentcast(routes, monkeypatch):
    monkeypatch.setattr(seed_mod, "SEED_SOURCE", "")
    seed("77004", 1, seed_source=None)
    assert routes == [("rentcast", "77004")]


def test_region_id_wins_over_seed_source(routes):
    """Region runs always seed free from HCAD, whatever seed_source says."""
    seed("77004", 1, region_id="R1", seed_source="rentcast")
    assert routes == [("hcad_region", "R1")]


def test_csv_path_wins_over_seed_source(routes):
    seed("77004", 1, csv_path="/tmp/a.csv", seed_source="hcad")
    assert routes == [("csv", "/tmp/a.csv")]
