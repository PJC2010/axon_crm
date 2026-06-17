"""Feature extraction: stable order, missing-awareness, and graceful degradation
when life-event (Versium) data is entirely absent."""
from datetime import date

from pipeline.ml import features


def test_feature_names_are_stable_and_have_missing_indicators():
    names = features.feature_names()
    assert names == features.feature_names()          # deterministic
    assert "home_age" in names
    assert "home_age__missing" in names
    # One-hot buckets + an explicit "other" catch-all.
    assert "vertical__other" in names
    assert "lead_source__other" in names


def test_vector_length_matches_names():
    row = {"year_built": 2000, "vertical": "roofing"}
    vec = features.feature_vector(row)
    assert len(vec) == len(features.feature_names())


def test_missing_field_sets_indicator_and_zero_value():
    d = features.feature_dict({})            # nothing known
    assert d["home_age"] == 0.0
    assert d["home_age__missing"] == 1.0
    assert d["est_household_income"] == 0.0
    assert d["est_household_income__missing"] == 1.0


def test_present_field_clears_indicator():
    d = features.feature_dict({"year_built": date.today().year - 20})
    assert d["home_age"] == 20.0
    assert d["home_age__missing"] == 0.0


def test_absentee_inverts_owner_occupied():
    assert features.feature_dict({"owner_occupied": False})["absentee"] == 1.0
    assert features.feature_dict({"owner_occupied": True})["absentee"] == 0.0
    # Unknown occupancy => not absentee, but flagged missing.
    d = features.feature_dict({})
    assert d["absentee"] == 0.0 and d["absentee__missing"] == 1.0


def test_works_without_any_life_event_data():
    """A property-only lead (no Versium block) must still vectorize cleanly, with
    every life-event slot marked missing rather than silently treated as a real 0."""
    property_only = {
        "year_built": 1995, "estimated_equity": 120000, "garage_spaces": 2,
        "last_sale_date": "2024-01-15", "vertical": "roofing", "lead_source": "pipeline",
    }
    d = features.feature_dict(property_only)
    assert d["credit_rating__missing"] == 1.0
    assert d["has_children__missing"] == 1.0
    assert d["months_since_refi__missing"] == 1.0
    # Property signals are populated.
    assert d["log_equity"] > 0
    assert d["vertical__roofing"] == 1.0
    assert d["lead_source__pipeline"] == 1.0


def test_credit_and_life_stage_ordinal_mapping():
    assert features.feature_dict({"credit_rating": "A"})["credit_rating"] == 1.0
    assert features.feature_dict({"credit_rating": "d"})["credit_rating"] == 0.10
    assert features.feature_dict({"life_stage": "new_mover"})["life_stage"] == 1.0


def test_unknown_vertical_falls_into_other_bucket():
    d = features.feature_dict({"vertical": "underwater_basket_weaving"})
    assert d["vertical__other"] == 1.0


def test_snapshot_payload_is_json_serializable():
    import json
    payload = features.snapshot_payload({"last_sale_date": date(2024, 1, 1), "year_built": 2001})
    json.dumps(payload)                      # must not raise
    assert payload["last_sale_date"] == "2024-01-01"
