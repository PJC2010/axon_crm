"""Tests for the pure call-tracking *setup* logic (api/call_setup_logic.py):
which area codes activation shops, and the default missed-call auto-text.
No DB, no network — the runtime half is covered by tests/test_call_logic.py."""
import pytest

from api import call_setup_logic as csl


# ── Area codes ────────────────────────────────────────────────────────────────

class TestAreaCodeOf:
    @pytest.mark.parametrize("phone", [
        "7135550142", "+17135550142", "17135550142",
        "(713) 555-0142", " 713.555.0142 ",
    ])
    def test_reads_every_written_form(self, phone):
        assert csl.area_code_of(phone) == "713"

    @pytest.mark.parametrize("phone", [None, "", "555-0142", "12345", "abc"])
    def test_too_short_or_missing_is_blank(self, phone):
        assert csl.area_code_of(phone) == ""


class TestSearchAreaCodes:
    def test_defaults_to_the_business_lines_own_area_code(self):
        # A tracking number reads as local when it matches the line it forwards
        # to, so that's the first thing tried.
        assert csl.search_area_codes("(713) 555-0142") == ["713", None]

    def test_explicit_request_outranks_the_business_line(self):
        assert csl.search_area_codes("7135550142", "832") == ["832", "713", None]

    def test_same_code_twice_is_not_tried_twice(self):
        assert csl.search_area_codes("7135550142", "713") == ["713", None]

    def test_always_ends_with_anywhere(self):
        # None = "any US local number". Activation must not dead-end when one
        # area code is sold out — a number elsewhere still tracks calls.
        for forward_to in (None, "", "junk", "7135550142"):
            assert csl.search_area_codes(forward_to)[-1] is None

    def test_unusable_business_line_falls_straight_through(self):
        assert csl.search_area_codes("nope") == [None]

    @pytest.mark.parametrize("requested", ["71", "7133", "abc", " ", None])
    def test_malformed_request_is_ignored_not_passed_to_twilio(self, requested):
        assert csl.search_area_codes("7135550142", requested) == ["713", None]


# ── The default auto-reply ────────────────────────────────────────────────────

class TestDefaultAutoReplyBody:
    def test_named_account_gets_the_merge_field(self):
        # The merge field, not the literal name — renaming the account should
        # update the text rather than leave the old name in it.
        body = csl.default_auto_reply_body("Kirby Roofing")
        assert "{{business_name}}" in body
        assert "Kirby Roofing" not in body

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_unnamed_account_drops_the_clause_entirely(self, name):
        # An empty merge field would render "This is ." mid-sentence.
        body = csl.default_auto_reply_body(name)
        assert "{{" not in body
        assert body.strip().endswith("right back to you.")

    def test_never_greets_a_placeholder_name(self):
        # Leads auto-created from an unknown caller are named
        # "Caller (713) 555-0142", so {{first_name}} would read "Hi Caller".
        for name in (None, "Kirby Roofing"):
            assert "{{first_name}}" not in csl.default_auto_reply_body(name)

    def test_fits_a_single_sms_segment_budget(self):
        assert len(csl.default_auto_reply_body("Kirby Roofing")) <= csl.AUTO_REPLY_MAX_CHARS


class TestCleanAutoReplyBody:
    def test_none_means_leave_it_alone(self):
        assert csl.clean_auto_reply_body(None) is None

    def test_trims_surrounding_whitespace(self):
        assert csl.clean_auto_reply_body("  on my way  ") == "on my way"

    @pytest.mark.parametrize("raw", ["", "   ", "\n\t"])
    def test_blank_is_rejected(self, raw):
        with pytest.raises(ValueError):
            csl.clean_auto_reply_body(raw)

    def test_overlong_is_rejected_with_the_length_named(self):
        with pytest.raises(ValueError) as exc:
            csl.clean_auto_reply_body("x" * (csl.AUTO_REPLY_MAX_CHARS + 1))
        assert str(csl.AUTO_REPLY_MAX_CHARS) in str(exc.value)

    def test_exactly_at_the_cap_is_allowed(self):
        body = "x" * csl.AUTO_REPLY_MAX_CHARS
        assert csl.clean_auto_reply_body(body) == body


# ── Workflow-rule wiring ──────────────────────────────────────────────────────

class TestRuleConfig:
    def test_fires_on_missed_only(self):
        # 'busy' means the line was engaged — someone was there, no auto-text.
        assert csl.auto_reply_trigger_config() == {"event": "missed"}

    def test_action_sends_the_template_immediately(self):
        cfg = csl.auto_reply_action_config(12)
        assert cfg == {"template_id": 12}
        # No delay_minutes: the caller should get the reply while they still
        # have the phone in their hand.
        assert "delay_minutes" not in cfg

    def test_template_id_is_coerced_to_int(self):
        # psycopg2 hands back plain ints, but a JSON round-trip could not.
        assert csl.auto_reply_action_config("12")["template_id"] == 12

    def test_config_passes_the_routes_own_validator(self):
        # The rule this seeds must survive api/routes/workflows.py's validation,
        # or the owner could not later edit it through the workflows UI.
        from api.routes.workflows import _validate_rule
        _validate_rule("call_event", csl.auto_reply_trigger_config(),
                       "send_template", csl.auto_reply_action_config(12))
