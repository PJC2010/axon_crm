"""Tests for pipeline/contact.py — Versium Contact Append parsing and no-key no-op."""
import pytest

import pipeline.contact as contact
from pipeline.contact import (
    _first_name, _last_name, _first_value, _versium_lookup, enrich_contact,
)


# ── Name splitting ─────────────────────────────────────────────────────────────

class TestNameHelpers:
    def test_first_name_two_words(self):
        assert _first_name("John Smith") == "John"

    def test_last_name_two_words(self):
        assert _last_name("John Smith") == "Smith"

    def test_last_name_single_word(self):
        assert _last_name("Smith") == "Smith"

    def test_first_name_single_word(self):
        assert _first_name("Smith") == "Smith"

    def test_empty(self):
        assert _first_name("") == ""
        assert _last_name("") == ""

    def test_none_safe(self):
        assert _first_name(None) == ""
        assert _last_name(None) == ""


# ── _first_value ────────────────────────────────────────────────────────────────

class TestFirstValue:
    def test_scalar(self):
        assert _first_value({"phone": "713-555-0100"}, ("phone",)) == "713-555-0100"

    def test_list_takes_first(self):
        assert _first_value({"phones": ["a", "b"]}, ("phones",)) == "a"

    def test_empty_list_skipped(self):
        assert _first_value({"phones": [], "phone_1": "x"}, ("phones", "phone_1")) == "x"

    def test_dict_unwrapped(self):
        assert _first_value({"phone": {"number": "555"}}, ("phone",)) == "555"

    def test_key_priority(self):
        # First matching key with a value wins.
        assert _first_value({"phone": None, "phone_1": "second"}, ("phone", "phone_1")) == "second"

    def test_none_when_absent(self):
        assert _first_value({}, ("phone",)) is None

    def test_strips_whitespace(self):
        assert _first_value({"email": "  a@b.com "}, ("email",)) == "a@b.com"


# ── _versium_lookup (monkeypatched HTTP) ────────────────────────────────────────

ROW = {"owner_name": "Jane Doe", "address": "123 Main St",
       "city": "Houston", "state": "TX", "zip": "77002"}


class TestVersiumLookup:
    def test_parses_phone_and_email(self, monkeypatch):
        monkeypatch.setattr(contact, "CONTACT_API_KEY", "key")
        monkeypatch.setattr(contact, "get_json", lambda *a, **k: {
            "versium": {"results": [{"Phone": "713-555-0100",
                                     "Email Address": "jane@example.com"}]}
        })
        out = _versium_lookup(ROW)
        assert out == {
            "contact_name": "Jane Doe",
            "contact_phone": "713-555-0100",
            "contact_email": "jane@example.com",
        }

    def test_handles_list_fields(self, monkeypatch):
        monkeypatch.setattr(contact, "CONTACT_API_KEY", "key")
        monkeypatch.setattr(contact, "get_json", lambda *a, **k: {
            "versium": {"results": [{"Phones": ["281-555-0199"],
                                     "Emails": ["a@b.com", "c@d.com"]}]}
        })
        out = _versium_lookup(ROW)
        assert out["contact_phone"] == "281-555-0199"
        assert out["contact_email"] == "a@b.com"

    def test_top_level_results(self, monkeypatch):
        monkeypatch.setattr(contact, "CONTACT_API_KEY", "key")
        monkeypatch.setattr(contact, "get_json", lambda *a, **k: {
            "results": [{"phone_1": "555", "email_address_1": "x@y.com"}]
        })
        out = _versium_lookup(ROW)
        assert out["contact_phone"] == "555"
        assert out["contact_email"] == "x@y.com"

    def test_no_response_returns_none(self, monkeypatch):
        monkeypatch.setattr(contact, "get_json", lambda *a, **k: None)
        assert _versium_lookup(ROW) is None

    def test_empty_results_returns_none(self, monkeypatch):
        monkeypatch.setattr(contact, "get_json", lambda *a, **k: {"versium": {"results": []}})
        assert _versium_lookup(ROW) is None

    def test_no_contact_fields_returns_none(self, monkeypatch):
        # A record with neither phone nor email yields nothing to write.
        monkeypatch.setattr(contact, "get_json", lambda *a, **k: {
            "versium": {"results": [{"Some Other Field": "z"}]}
        })
        assert _versium_lookup(ROW) is None


# ── enrich_contact no-key no-op ─────────────────────────────────────────────────

class TestEnrichContactNoKey:
    def test_no_provider_configured_skips(self, monkeypatch):
        monkeypatch.setattr(contact, "CONTACT_PROVIDER", "")
        monkeypatch.setattr(contact, "CONTACT_API_KEY", "")
        result = enrich_contact("77002", 1)
        assert result["skipped_no_key"] is True
        assert result["updated"] == 0

    def test_unknown_provider_skips(self, monkeypatch):
        monkeypatch.setattr(contact, "CONTACT_PROVIDER", "nope")
        monkeypatch.setattr(contact, "CONTACT_API_KEY", "key")
        result = enrich_contact("77002", 1)
        assert result["skipped_no_key"] is True

    def test_versium_is_registered(self):
        assert "versium" in contact.PROVIDERS
