"""Tests for the pure call-tracking logic (api/call_logic.py): TwiML builders,
DialCallStatus -> outcome mapping, auto-created-lead shape, and the history
action lines. No DB, no network."""
import xml.etree.ElementTree as ET

import pytest

from api import call_logic


# ── TwiML builders ────────────────────────────────────────────────────────────

class TestDialTwiml:
    def test_forwards_to_number_with_action(self):
        xml = call_logic.build_dial_twiml("+17135550142", "https://x.test/api/public/twilio/voice/dial-status")
        root = ET.fromstring(xml)
        dial = root.find("Dial")
        assert dial is not None
        assert dial.get("action") == "https://x.test/api/public/twilio/voice/dial-status"
        assert dial.get("answerOnBridge") == "true"
        assert dial.get("timeout") == "25"
        assert dial.find("Number").text == "+17135550142"

    def test_no_caller_id_override(self):
        # Omitting callerId passes the original caller's number through.
        xml = call_logic.build_dial_twiml("+17135550142", "https://x.test/cb")
        assert "callerId" not in xml

    def test_escapes_xml_specials(self):
        # Junk in forward_to/action must never break the document.
        xml = call_logic.build_dial_twiml('+1713555&<>"', 'https://x.test/cb?a=1&b="2"')
        root = ET.fromstring(xml)  # parses = well-formed
        assert root.find("Dial").get("action") == 'https://x.test/cb?a=1&b="2"'
        assert root.find("Dial/Number").text == '+1713555&<>"'

    def test_custom_timeout_coerced_to_int(self):
        xml = call_logic.build_dial_twiml("+17135550142", "https://x.test/cb", timeout=40)
        assert ET.fromstring(xml).find("Dial").get("timeout") == "40"

    def test_hangup_and_unconfigured_are_well_formed(self):
        assert ET.fromstring(call_logic.build_hangup_twiml()).find("Hangup") is not None
        root = ET.fromstring(call_logic.build_unconfigured_twiml())
        assert root.find("Say") is not None and root.find("Hangup") is not None


# ── Outcome mapping ───────────────────────────────────────────────────────────

class TestDialStatusMapping:
    @pytest.mark.parametrize("status,outcome", [
        ("completed", "answered"),
        ("answered", "answered"),
        ("busy", "busy"),
        ("no-answer", "missed"),
        ("failed", "missed"),
        ("canceled", "missed"),
    ])
    def test_known_statuses(self, status, outcome):
        assert call_logic.map_dial_status(status) == outcome

    def test_unknown_none_and_case(self):
        assert call_logic.map_dial_status("something-new") == "missed"
        assert call_logic.map_dial_status(None) == "missed"
        assert call_logic.map_dial_status(" Completed ") == "answered"


# ── Auto-created lead ─────────────────────────────────────────────────────────

class TestNewLeadRow:
    def test_defaults(self):
        row = call_logic.new_lead_row("+17135550142", "7135550142")
        assert row["contact_name"] == "Caller (713) 555-0142"
        assert row["contact_phone"] == "+17135550142"
        assert row["status"] == "new"
        assert row["lead_source"] == "inbound_call"
        assert row["enrichment_flags"] == {"source": "call_tracking"}

    def test_cnam_name_wins(self):
        row = call_logic.new_lead_row("+17135550142", "7135550142", caller_name="ACME ROOFING")
        assert row["contact_name"] == "ACME ROOFING"

    def test_blank_cnam_falls_back(self):
        row = call_logic.new_lead_row("+17135550142", "7135550142", caller_name="   ")
        assert row["contact_name"] == "Caller (713) 555-0142"

    def test_short_digits_pass_through(self):
        assert call_logic.format_phone_display("555") == "555"


# ── History lines ─────────────────────────────────────────────────────────────

class TestHistoryLines:
    def test_duration_formats(self):
        assert call_logic.format_duration(134) == "2m 14s"
        assert call_logic.format_duration(45) == "45s"
        assert call_logic.format_duration(0) == "0s"
        assert call_logic.format_duration(None) == "0s"
        assert call_logic.format_duration(-5) == "0s"

    def test_answered_includes_duration(self):
        assert call_logic.history_action_for("answered", 134) == "Inbound call — answered (2m 14s)"

    def test_missed_and_busy(self):
        assert call_logic.history_action_for("missed", None) == "Missed call"
        assert call_logic.history_action_for("busy", 0) == "Missed call — line busy"
