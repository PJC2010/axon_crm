"""Tests for api/phone_append_logic.py — which columns a reverse append may fill.

Pure unit tests: no DB, no network, no provider key. Both the inbound-call
webhook and the backfill sweep route their writes through these two functions,
so the "only fill what's empty" and "flag every completed attempt" rules are
pinned here once rather than in each caller.
"""
from api.phone_append_logic import merge_append, merge_flags


FULL_MATCH = {
    "contact_name": "Greta Fisher",
    "contact_email": "g@example.com",
    "address": "123 Main St",
    "city": "Humble",
    "state": "TX",
    "zip": "77396",
    "phone_type": "Mobile",
    "phone_reachable": True,
    "phone_dnc": False,
}

BLANK_LEAD = {"address": None, "city": None, "state": None, "zip": None,
              "contact_name": None, "contact_email": None}


# ── merge_append ─────────────────────────────────────────────────────────────

class TestMergeAppend:
    def test_fills_every_empty_column(self):
        assert merge_append(FULL_MATCH, BLANK_LEAD) == {
            "contact_name": "Greta Fisher",
            "contact_email": "g@example.com",
            "address": "123 Main St",
            "city": "Humble",
            "state": "TX",
            "zip": "77396",
        }

    def test_never_overwrites_existing_values(self):
        current = {**BLANK_LEAD, "address": "9 Old Rd", "city": "Katy",
                   "contact_email": "kept@example.com"}
        assert merge_append(FULL_MATCH, current) == {
            "contact_name": "Greta Fisher", "state": "TX", "zip": "77396",
        }

    def test_overwrites_the_caller_placeholder_name(self):
        # call_logic.new_lead_row names an unknown caller "Caller (713) 555-0142";
        # a real name from the provider is strictly better.
        current = {**BLANK_LEAD, "contact_name": "Caller (713) 555-0142"}
        assert merge_append(FULL_MATCH, current)["contact_name"] == "Greta Fisher"

    def test_keeps_a_real_name_the_user_already_has(self):
        current = {**BLANK_LEAD, "contact_name": "G. Fisher"}
        assert "contact_name" not in merge_append(FULL_MATCH, current)

    def test_metadata_fields_are_not_columns(self):
        updates = merge_append(FULL_MATCH, BLANK_LEAD)
        assert not {"phone_type", "phone_reachable", "phone_dnc"} & updates.keys()

    def test_no_match_writes_nothing(self):
        assert merge_append(None, BLANK_LEAD) == {}
        assert merge_append({}, BLANK_LEAD) == {}

    def test_missing_keys_count_as_empty(self):
        assert merge_append({"city": "Humble"}, {}) == {"city": "Humble"}

    def test_partial_match_fills_only_what_it_has(self):
        assert merge_append({"address": "123 Main St"}, BLANK_LEAD) == {
            "address": "123 Main St"}


# ── merge_flags ──────────────────────────────────────────────────────────────

class TestMergeFlags:
    def test_stamps_provider_and_metadata(self):
        assert merge_flags(FULL_MATCH, None, "batchdata") == {
            "phone_append": "batchdata",
            "phone_append_meta": {"phone_type": "Mobile", "phone_reachable": True,
                                  "phone_dnc": False},
        }

    def test_no_match_still_stamps_the_provider(self):
        # The provider charged for the query — without the stamp, every later
        # call from this number would re-spend.
        assert merge_flags(None, None, "versium") == {"phone_append": "versium"}

    def test_preserves_unrelated_flags(self):
        flags = merge_flags(None, {"contact": "batchdata", "demo": "versium"},
                            "batchdata")
        assert flags == {"contact": "batchdata", "demo": "versium",
                         "phone_append": "batchdata"}

    def test_does_not_mutate_the_input(self):
        original = {"contact": "batchdata"}
        merge_flags(FULL_MATCH, original, "batchdata")
        assert original == {"contact": "batchdata"}

    def test_false_metadata_survives(self):
        # phone_dnc=False is a real answer, not a missing one — only None drops.
        flags = merge_flags({"phone_dnc": False, "litigator": None}, None, "batchdata")
        assert flags["phone_append_meta"] == {"phone_dnc": False}
