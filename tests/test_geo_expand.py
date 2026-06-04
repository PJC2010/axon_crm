"""
Tests for pipeline/geo_expand.py.

The uszipcode library is optional, so these tests focus on the graceful-
degradation contract and the capping logic via a fake engine.
"""
import pipeline.geo_expand as ge


def test_degrades_gracefully_when_unavailable(monkeypatch):
    monkeypatch.setattr(ge, "_AVAILABLE", False)
    assert ge.nearby_zips("77002") == []
    assert ge.city_zips("77002") == []


class _FakeZip:
    def __init__(self, zipcode, lat=29.0, lng=-95.0, city="Houston", state="TX"):
        self.zipcode = zipcode
        self.lat = lat
        self.lng = lng
        self.major_city = city
        self.state = state


class _FakeEngine:
    def by_zipcode(self, z):
        return _FakeZip(z)

    def by_coordinates(self, lat, lng, radius, returns):
        return [_FakeZip(str(77000 + i)) for i in range(returns)]

    def by_city_and_state(self, city, state, returns):
        return [_FakeZip(str(77000 + i)) for i in range(returns)]


def test_nearby_excludes_self_and_caps(monkeypatch):
    monkeypatch.setattr(ge, "_AVAILABLE", True)
    monkeypatch.setattr(ge, "_engine", lambda: _FakeEngine())
    out = ge.nearby_zips("77000", radius_miles=5, max_zips=3)
    assert "77000" not in out
    assert len(out) == 3


def test_city_zips_excludes_self_and_caps(monkeypatch):
    monkeypatch.setattr(ge, "_AVAILABLE", True)
    monkeypatch.setattr(ge, "_engine", lambda: _FakeEngine())
    out = ge.city_zips("77000", max_zips=2)
    assert "77000" not in out
    assert len(out) == 2
