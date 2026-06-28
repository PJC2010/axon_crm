"""Tests for pipeline/contact.py — owner-name cleaning and Versium parsing.

Pure unit tests: the network call (get_json) is monkeypatched, so no provider
key or DB is required.
"""
import pytest

from pipeline.contact import (
    PROVIDERS, _is_business, _owner_name_candidates, _clean_person_tokens,
    _full_name, _first_value, _versium_lookup, _batchdata_lookup,
)


# ── Provider registry ───────────────────────────────────────────────────────────

def test_versium_registered():
    # Regression: a missing "versium" entry is what caused the 409 in the UI.
    assert "versium" in PROVIDERS


def test_batchdata_registered():
    assert "batchdata" in PROVIDERS


# ── _batchdata_lookup (parsing the Skip Trace response envelope) ──────────────────

class TestBatchdataLookup:
    def test_parses_persons_envelope(self, monkeypatch):
        captured = {}
        def fake(url, *, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return {"results": {"persons": [{
                "name": {"first": "Greta", "last": "Fisher", "full": "Greta Fisher"},
                "phoneNumbers": [{"number": "8327086648", "type": "Mobile"}],
                "emails": [{"email": "g@example.com"}],
            }]}}
        monkeypatch.setattr("pipeline.contact.post_json", fake)
        out = _batchdata_lookup({"owner_name": "GRETA FISHER", "address": "1 Oak St",
                                 "city": "Humble", "state": "TX", "zip": "77396"})
        assert out == {
            "contact_name": "Greta Fisher",
            "contact_phone": "8327086648",
            "contact_email": "g@example.com",
        }
        # Default endpoint + structured request payload.
        assert captured["url"].endswith("/property/skip-trace")
        req = captured["json"]["requests"][0]
        assert req["propertyAddress"]["zip"] == "77396"
        assert req["name"] == {"first": "Greta", "last": "Fisher"}

    def test_no_persons_returns_none(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.post_json",
                            lambda *a, **k: {"results": {"persons": []}})
        assert _batchdata_lookup({"owner_name": "Timothy Boone"}) is None

    def test_api_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.post_json", lambda *a, **k: None)
        assert _batchdata_lookup({"owner_name": "Greta Fisher"}) is None


# ── Business-entity detection ────────────────────────────────────────────────────

class TestIsBusiness:
    @pytest.mark.parametrize("name", [
        "RASPBERRY REALTY I LLC", "ACME HOLDINGS INC", "SMITH FAMILY TRUST",
        "HOUSTON CITY OF", "FIRST BANK", "OAK PROPERTIES LP",
    ])
    def test_business(self, name):
        assert _is_business(name) is True

    @pytest.mark.parametrize("name", [
        "GRETA FISHER", "James M Alford", "Portela Raul E",
    ])
    def test_person(self, name):
        assert _is_business(name) is False


# ── Owner-name → (first, last) candidates ────────────────────────────────────────

class TestOwnerNameCandidates:
    def test_simple_first_last_tries_both_orders(self):
        assert _owner_name_candidates("GRETA FISHER") == [("Greta", "Fisher"), ("Fisher", "Greta")]

    def test_drops_middle_initial(self):
        assert _owner_name_candidates("James M Alford") == [("James", "Alford"), ("Alford", "James")]

    def test_multi_owner_keeps_first(self):
        got = _owner_name_candidates("Portela Raul E & Connie E & Portela Stephanie R")
        assert got == [("Portela", "Raul"), ("Raul", "Portela")]

    def test_comma_form_is_unambiguous(self):
        assert _owner_name_candidates("FISHER, GRETA") == [("Greta", "Fisher")]

    def test_strips_suffix(self):
        assert _owner_name_candidates("SMITH JOHN JR") == [("Smith", "John"), ("John", "Smith")]

    def test_strips_title_and_suffix(self):
        assert _owner_name_candidates("Dr Robert A Jones III") == [("Robert", "Jones"), ("Jones", "Robert")]

    @pytest.mark.parametrize("name", [
        "RASPBERRY REALTY I LLC", "HOUSTON CITY OF", "MARIA", "", "   ",
    ])
    def test_no_usable_person_returns_empty(self, name):
        assert _owner_name_candidates(name) == []


# ── _clean_person_tokens ─────────────────────────────────────────────────────────

class TestCleanPersonTokens:
    def test_titlecases_allcaps(self):
        assert _clean_person_tokens("GRETA FISHER") == ["Greta", "Fisher"]

    def test_preserves_mixed_case_hyphenated(self):
        assert _clean_person_tokens("O'Brien-Smith") == ["O'Brien-Smith"]


# ── _full_name ───────────────────────────────────────────────────────────────────

def test_full_name_joins():
    assert _full_name("Greta", "Fisher") == "Greta Fisher"

def test_full_name_ignores_blanks():
    assert _full_name(None, "Fisher") == "Fisher"
    assert _full_name(None, None) is None


# ── _first_value (response field extraction) ─────────────────────────────────────

class TestFirstValue:
    def test_scalar(self):
        assert _first_value({"phone": "281555"}, ("phone",)) == "281555"

    def test_list(self):
        assert _first_value({"phones": ["281", "832"]}, ("phones",)) == "281"

    def test_dict_number(self):
        assert _first_value({"phone": {"number": "281555"}}, ("phone",)) == "281555"

    def test_first_present_key_wins(self):
        assert _first_value({"mobile_phone": "832", "phone": "281"},
                            ("mobile_phone", "phone")) == "832"

    def test_none_when_absent(self):
        assert _first_value({}, ("phone",)) is None


# ── _versium_lookup (parsing the real response envelope) ─────────────────────────

def _versium_payload(first, last, **fields):
    return {"versium": {"results": [{"First Name": first, "Last Name": last, **fields}]}}


class TestVersiumLookup:
    def test_parses_and_stores_normalized_name(self, monkeypatch):
        # Real envelope: "Mobile Phone" + "Email Address" Title-Case keys.
        monkeypatch.setattr(
            "pipeline.contact.get_json",
            lambda *a, **k: _versium_payload(
                "Greta", "Fisher",
                **{"Mobile Phone": "8327086648", "Email Address": "g@example.com"}),
        )
        out = _versium_lookup({"owner_name": "GRETA FISHER", "city": "Humble",
                               "state": "TX", "zip": "77396"})
        assert out == {
            "contact_name": "Greta Fisher",
            "contact_phone": "8327086648",
            "contact_email": "g@example.com",
        }

    def test_business_entity_skips_without_calling(self, monkeypatch):
        called = {"n": 0}
        def boom(*a, **k):
            called["n"] += 1
            return None
        monkeypatch.setattr("pipeline.contact.get_json", boom)
        assert _versium_lookup({"owner_name": "RASPBERRY REALTY I LLC"}) is None
        assert called["n"] == 0  # no API call wasted on a business

    def test_swaps_order_on_first_miss(self, monkeypatch):
        # First ordering (Portela, Raul) misses; swapped (Raul, Portela) hits.
        def fake(url, *, headers=None, params=None, timeout=None):
            if params["first"] == "Raul" and params["last"] == "Portela":
                return _versium_payload("Raul", "Portela",
                                        **{"Mobile Phone": "8326715727"})
            return {"versium": {"results": []}}
        monkeypatch.setattr("pipeline.contact.get_json", fake)
        out = _versium_lookup({"owner_name": "Portela Raul E & Connie E"})
        assert out["contact_name"] == "Raul Portela"
        assert out["contact_phone"] == "8326715727"

    def test_no_match_returns_none(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.get_json",
                            lambda *a, **k: {"versium": {"results": []}})
        assert _versium_lookup({"owner_name": "Timothy Boone"}) is None
