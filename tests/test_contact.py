"""Tests for pipeline/contact.py — owner-name cleaning and Versium parsing.

Pure unit tests: the network call (get_json) is monkeypatched, so no provider
key or DB is required.
"""
import pytest

from pipeline.contact import (
    PHONE_APPEND_PROVIDERS, PROVIDERS, _is_business, _owner_name_candidates,
    _clean_person_tokens, _full_name, _first_value, _versium_lookup,
    _batchdata_lookup, batchdata_phone_append, batchdata_phone_append_batch,
    phone_append, phone_append_batch, versium_phone_append,
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
        # Assessor placeholders parse as a plausible person; without the junk
        # guard each one billed two skip-trace lookups that can never match.
        "CURRENT OWNER", "Current Property Owner", "UNKNOWN",
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


# ── versium_phone_append (reverse lookup: caller phone → address) ─────────────

class TestVersiumPhoneAppend:
    def _configured(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "versium")
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_API_KEY", "test-key")

    def test_requests_address_and_email_outputs(self, monkeypatch):
        self._configured(monkeypatch)
        captured = {}
        def fake(url, *, headers=None, params=None, timeout=None, retries=None):
            captured.update(headers=headers, params=params,
                            timeout=timeout, retries=retries)
            return {"versium": {"results": []}}
        monkeypatch.setattr("pipeline.contact.get_json", fake)
        versium_phone_append("7135550142")
        assert captured["params"]["output[]"] == ["address", "email"]
        assert captured["params"]["phone"] == "7135550142"
        assert captured["headers"]["x-versium-api-key"] == "test-key"
        assert captured["retries"] == 0  # runs inside Twilio's webhook window

    def test_maps_full_address(self, monkeypatch):
        self._configured(monkeypatch)
        monkeypatch.setattr(
            "pipeline.contact.get_json",
            lambda *a, **k: _versium_payload(
                "Greta", "Fisher",
                **{"Address": "123 Main St", "City": "Humble", "State": "TX",
                   "Zip": "77396", "Email Address": "g@example.com"}),
        )
        assert versium_phone_append("7135550142") == {
            "contact_name": "Greta Fisher",
            "contact_email": "g@example.com",
            "address": "123 Main St",
            "city": "Humble",
            "state": "TX",
            "zip": "77396",
        }

    def test_merges_partial_records(self, monkeypatch):
        self._configured(monkeypatch)
        monkeypatch.setattr(
            "pipeline.contact.get_json",
            lambda *a, **k: {"versium": {"results": [
                {"Address": "123 Main St"},
                {"City": "Humble", "State": "TX", "Zip": "77396"},
            ]}},
        )
        assert versium_phone_append("7135550142") == {
            "address": "123 Main St", "city": "Humble",
            "state": "TX", "zip": "77396",
        }

    def test_no_match_returns_none(self, monkeypatch):
        self._configured(monkeypatch)
        monkeypatch.setattr("pipeline.contact.get_json",
                            lambda *a, **k: {"versium": {"results": []}})
        assert versium_phone_append("7135550142") is None

    def test_unconfigured_or_bad_number_skips_call(self, monkeypatch):
        called = {"n": 0}
        def boom(*a, **k):
            called["n"] += 1
            return None
        monkeypatch.setattr("pipeline.contact.get_json", boom)
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "")
        assert versium_phone_append("7135550142") is None
        self._configured(monkeypatch)
        assert versium_phone_append("5550142") is None  # not a 10-digit number
        assert called["n"] == 0  # no API call wasted

    def test_independent_of_skiptrace_provider(self, monkeypatch):
        # The batch skip-trace can stay on BatchData while the inbound-call
        # append runs on Versium — the two directions configure separately.
        monkeypatch.setattr("pipeline.contact.CONTACT_PROVIDER", "batchdata")
        self._configured(monkeypatch)
        monkeypatch.setattr("pipeline.contact.get_json",
                            lambda *a, **k: _versium_payload(
                                "Greta", "Fisher", **{"Address": "123 Main St"}))
        assert versium_phone_append("7135550142") == {
            "contact_name": "Greta Fisher", "address": "123 Main St",
        }


# ── batchdata_phone_append (Reverse Skip Trace: caller phone → property) ─────

def _reverse_payload(*records):
    """A Reverse Skip Trace envelope wrapping already-built data[] records."""
    return {"status": {"code": 200, "text": "OK"},
            "result": {"data": list(records), "meta": {}}}


def _reverse_person(phone, **person):
    """One matched data[] record for `phone`, defaults filled in."""
    base = {
        "propertyOwner": True,
        "name": {"first": "Greta", "last": "Fisher", "full": "Greta Fisher"},
        "phones": [{"rank": 1, "number": "7135550142", "type": "Mobile",
                    "reachable": True, "dnc": False}],
        "emails": [{"rank": 1, "email": "g@example.com", "tested": True}],
        "property": {"id": "abc", "address": {
            "street": "123 Main St", "city": "Humble", "state": "TX",
            "zip": "77396", "fullAddress": "123 Main St, Humble, TX 77396"}},
    }
    return {"input": {"phone": phone}, "persons": [{**base, **person}],
            "meta": {"matched": True, "error": False}}


class TestBatchdataPhoneAppend:
    def _configured(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "batchdata")
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_API_KEY", "test-key")

    def test_posts_a_bearer_batch_and_maps_the_property(self, monkeypatch):
        self._configured(monkeypatch)
        captured = {}
        def fake(url, *, json=None, headers=None, timeout=None, retries=None):
            captured.update(url=url, json=json, headers=headers,
                            timeout=timeout, retries=retries)
            return _reverse_payload(_reverse_person("7135550142"))
        monkeypatch.setattr("pipeline.contact.post_json", fake)

        assert batchdata_phone_append("7135550142") == {
            "contact_name": "Greta Fisher",
            "contact_email": "g@example.com",
            "address": "123 Main St",
            "city": "Humble",
            "state": "TX",
            "zip": "77396",
            "phone_type": "Mobile",
            "phone_reachable": True,
            "phone_dnc": False,
            "property_owner": True,
        }
        assert captured["url"].endswith("/api/v3/property/reverse-skip-trace")
        assert captured["json"] == {"requests": [{"phone": "7135550142"}]}
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        assert captured["retries"] == 0  # runs inside Twilio's webhook window
        assert captured["timeout"] == 8

    def test_prefers_the_property_owner_person(self, monkeypatch):
        self._configured(monkeypatch)
        record = _reverse_person("7135550142")
        record["persons"].insert(0, {
            "propertyOwner": False,
            "name": {"full": "Roommate Renter"},
            "addresses": [{"rank": 1, "street": "9 Other St", "city": "Katy",
                           "state": "TX", "zip": "77494"}],
        })
        monkeypatch.setattr("pipeline.contact.post_json",
                            lambda *a, **k: _reverse_payload(record))
        assert batchdata_phone_append("7135550142")["contact_name"] == "Greta Fisher"

    def test_falls_back_to_best_ranked_address(self, monkeypatch):
        # No property on the record — addresses[] is a ranked history, and the
        # mailing address for the property wins over an older rank-2 entry.
        self._configured(monkeypatch)
        record = _reverse_person("7135550142", property=None, addresses=[
            {"rank": 2, "street": "9 Old Rd", "city": "Katy", "state": "TX",
             "zip": "77494"},
            {"rank": 1, "street": "123 Main St", "city": "Humble", "state": "TX",
             "zip": "77396", "propertyMailingAddress": True},
        ])
        monkeypatch.setattr("pipeline.contact.post_json",
                            lambda *a, **k: _reverse_payload(record))
        assert batchdata_phone_append("7135550142")["address"] == "123 Main St"

    def test_row_error_inside_a_200_is_not_a_match(self, monkeypatch):
        # The trap: a rejected row rides inside an HTTP 200. It was never run,
        # so the key stays absent and nothing gets flagged as spent.
        self._configured(monkeypatch)
        monkeypatch.setattr("pipeline.contact.post_json", lambda *a, **k: _reverse_payload(
            {"input": {"phone": "7135550142"}, "persons": [],
             "meta": {"matched": False, "error": True,
                      "errorMessage": "Only US phone numbers are supported."}}))
        assert batchdata_phone_append_batch(["7135550142"]) == {}

    def test_no_match_is_present_but_empty(self, monkeypatch):
        # Billed but unmatched — the key must exist so the caller stamps the
        # flag and never re-queries this number.
        self._configured(monkeypatch)
        monkeypatch.setattr("pipeline.contact.post_json", lambda *a, **k: _reverse_payload(
            {"input": {"phone": "7135550142"}, "persons": [],
             "meta": {"matched": False, "error": False}}))
        assert batchdata_phone_append_batch(["7135550142"]) == {"7135550142": None}

    def test_transport_failure_leaves_every_key_absent(self, monkeypatch):
        self._configured(monkeypatch)
        monkeypatch.setattr("pipeline.contact.post_json", lambda *a, **k: None)
        assert batchdata_phone_append_batch(["7135550142", "7135550143"]) == {}

    def test_maps_results_back_by_echoed_number(self, monkeypatch):
        # data[] is parallel to requests[], but the echo is authoritative —
        # pin that a reordered response still lands on the right lead.
        self._configured(monkeypatch)
        monkeypatch.setattr("pipeline.contact.post_json", lambda *a, **k: _reverse_payload(
            _reverse_person("7135550143", name={"full": "Second Caller"}),
            _reverse_person("7135550142", name={"full": "First Caller"})))
        results = batchdata_phone_append_batch(["7135550142", "7135550143"])
        assert results["7135550142"]["contact_name"] == "First Caller"
        assert results["7135550143"]["contact_name"] == "Second Caller"

    def test_dedupes_and_drops_non_us_numbers(self, monkeypatch):
        self._configured(monkeypatch)
        captured = {}
        monkeypatch.setattr("pipeline.contact.post_json",
                            lambda url, *, json=None, **k: captured.update(json=json)
                            or _reverse_payload(_reverse_person("7135550142")))
        batchdata_phone_append_batch(["7135550142", "7135550142", "555014", ""])
        assert captured["json"] == {"requests": [{"phone": "7135550142"}]}

    def test_rejects_an_oversized_batch(self, monkeypatch):
        self._configured(monkeypatch)
        monkeypatch.setattr("pipeline.contact.post_json", lambda *a, **k: None)
        with pytest.raises(ValueError, match="at most 100"):
            batchdata_phone_append_batch([f"71355{i:05d}" for i in range(101)])

    def test_unconfigured_skips_the_call(self, monkeypatch):
        called = {"n": 0}
        def boom(*a, **k):
            called["n"] += 1
        monkeypatch.setattr("pipeline.contact.post_json", boom)
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "versium")
        assert batchdata_phone_append("7135550142") is None
        self._configured(monkeypatch)
        assert batchdata_phone_append("555") is None  # not a 10-digit number
        assert called["n"] == 0


# ── phone_append / phone_append_batch (provider dispatch) ────────────────────

class TestPhoneAppendDispatch:
    def test_registry_holds_both_directions(self):
        assert set(PHONE_APPEND_PROVIDERS) == {"batchdata", "versium"}

    def test_dispatches_to_the_configured_provider(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "batchdata")
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_API_KEY", "test-key")
        monkeypatch.setattr("pipeline.contact.post_json",
                            lambda *a, **k: _reverse_payload(_reverse_person("7135550142")))
        assert phone_append("7135550142")["address"] == "123 Main St"

    def test_unknown_provider_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "nope")
        assert phone_append("7135550142") is None
        assert phone_append_batch(["7135550142"]) == {}

    def test_batch_chunks_at_the_provider_limit(self, monkeypatch):
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "batchdata")
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_API_KEY", "test-key")
        sizes = []
        monkeypatch.setattr(
            "pipeline.contact.post_json",
            lambda url, *, json=None, **k: sizes.append(len(json["requests"]))
            or _reverse_payload(*(_reverse_person(r["phone"]) for r in json["requests"])))
        numbers = [f"71355{i:05d}" for i in range(150)]
        assert len(phone_append_batch(numbers)) == 150
        assert sizes == [100, 50]

    def test_versium_degrades_to_one_call_per_number(self, monkeypatch):
        # No batch form upstream; the sweep still works, just serially.
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_PROVIDER", "versium")
        monkeypatch.setattr("pipeline.contact.PHONE_APPEND_API_KEY", "test-key")
        calls = []
        monkeypatch.setattr(
            "pipeline.contact.get_json",
            lambda url, *, params=None, **k: calls.append(params["phone"])
            or _versium_payload("Greta", "Fisher", **{"Address": "123 Main St"}))
        results = phone_append_batch(["7135550142", "7135550143"])
        assert calls == ["7135550142", "7135550143"]
        assert results["7135550142"]["address"] == "123 Main St"
