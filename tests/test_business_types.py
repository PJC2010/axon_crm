"""Invariants for the business-type preset packs (Phase 6): every preset's
terminology, modules, stages, fields, workflows, and KPI ids must be internally
consistent — a broken pack would provision a broken account."""
import pytest

from api.business_types import (
    BASE_TERMINOLOGY, BUSINESS_TYPES, DEFAULT_BUSINESS_TYPE, DEFAULT_KPIS,
    business_type_catalog, business_type_profile, get_business_type, resolve_terminology,
)
from api.entitlements import MODULE_KEYS
from api.routes.record_fields import FIELD_TYPES
from api.routes.workflows import _validate_rule

# Every KPI id any preset may reference; HomeDashboard's KPI config and
# /api/objects/kpis must cover these.
KNOWN_KPIS = {
    "revenue_mtd", "outstanding_ar", "win_rate", "forecast",
    "premium_in_force", "active_policies", "renewals_30d",
    "orders_30d", "repeat_rate",
}

ALL_PRESETS = list(BUSINESS_TYPES)


class TestPresetInvariants:
    def test_expected_presets_exist(self):
        assert {"home_services", "general_sales", "professional_services",
                "insurance_agency", "retail"} <= set(BUSINESS_TYPES)
        assert DEFAULT_BUSINESS_TYPE in BUSINESS_TYPES

    @pytest.mark.parametrize("key", ALL_PRESETS)
    def test_terminology_overrides_are_known_keys(self, key):
        bt = BUSINESS_TYPES[key]
        assert set(bt.terminology_overrides) <= set(BASE_TERMINOLOGY), (
            f"{key} overrides a key missing from BASE_TERMINOLOGY (frontend "
            f"terminology.ts must stay in sync)"
        )

    @pytest.mark.parametrize("key", ALL_PRESETS)
    def test_default_modules_cover_module_keys(self, key):
        assert set(BUSINESS_TYPES[key].default_modules) == set(MODULE_KEYS)

    @pytest.mark.parametrize("key", ALL_PRESETS)
    def test_objects_are_modules_and_enabled(self, key):
        bt = BUSINESS_TYPES[key]
        for obj in bt.objects:
            assert obj in MODULE_KEYS, f"{key}: unknown object module {obj}"
            assert bt.default_modules.get(obj) is True, (
                f"{key}: declares object {obj} but doesn't enable its module"
            )

    @pytest.mark.parametrize("key", ALL_PRESETS)
    def test_kpis_are_known(self, key):
        assert set(BUSINESS_TYPES[key].kpis) <= KNOWN_KPIS

    @pytest.mark.parametrize("key", ALL_PRESETS)
    def test_stages_shape(self, key):
        bt = BUSINESS_TYPES[key]
        if bt.default_stages is None:
            return
        keys = [s[0] for s in bt.default_stages]
        assert len(keys) == len(set(keys)), f"{key}: duplicate stage keys"
        assert sum(1 for s in bt.default_stages if s[5]) == 1, (
            f"{key}: exactly one stage must be is_default"
        )
        assert any(s[4] for s in bt.default_stages), f"{key}: needs a terminal stage"
        for stage in bt.default_stages:
            assert len(stage) == 6

    @pytest.mark.parametrize("key", ALL_PRESETS)
    def test_fields_shape(self, key):
        bt = BUSINESS_TYPES[key]
        keys = [f["key"] for f in bt.default_fields]
        assert len(keys) == len(set(keys)), f"{key}: duplicate field keys"
        for f in bt.default_fields:
            assert f.get("label")
            assert f.get("field_type", "text") in FIELD_TYPES
            if f.get("field_type") == "select":
                assert f.get("options"), f"{key}.{f['key']}: select needs options"

    @pytest.mark.parametrize("key", ALL_PRESETS)
    def test_default_workflows_pass_route_validation(self, key):
        """Every seeded rule must be one the workflows API would accept — a
        pack must never provision a rule the engine silently skips."""
        for rule in BUSINESS_TYPES[key].default_workflows:
            _validate_rule(
                rule.get("trigger_type", "status_change"),
                rule.get("trigger_config", {}),
                rule.get("action_type", "create_task"),
                rule.get("action_config", {}),
            )
            assert rule.get("name")


class TestInsurancePack:
    def test_renewal_ladder(self):
        bt = BUSINESS_TYPES["insurance_agency"]
        offsets = sorted(
            r["trigger_config"]["offset_days"]
            for r in bt.default_workflows if r["trigger_type"] == "date_offset"
        )
        assert offsets == [-90, -30, -7]
        for r in bt.default_workflows:
            if r["trigger_type"] == "date_offset":
                assert r["trigger_config"]["source"] == "policies"
                assert r["trigger_config"]["date_field"] == "expiration_date"

    def test_modules(self):
        bt = BUSINESS_TYPES["insurance_agency"]
        assert bt.default_modules["policies"] is True
        assert bt.default_modules["orders"] is False
        assert bt.default_modules["prospecting"] is False
        assert not bt.property_based


class TestRetailPack:
    def test_winback_rule(self):
        bt = BUSINESS_TYPES["retail"]
        assert any(r["trigger_type"] == "inactivity" for r in bt.default_workflows)

    def test_modules(self):
        bt = BUSINESS_TYPES["retail"]
        assert bt.default_modules["orders"] is True
        assert bt.default_modules["policies"] is False


class TestProfilePayload:
    def test_profile_includes_kpis_and_objects(self):
        profile = business_type_profile("insurance_agency")
        assert profile["kpis"] == ["premium_in_force", "active_policies", "renewals_30d", "win_rate"]
        assert profile["objects"] == ["policies", "appointments"]

    def test_default_profile_keeps_classic_kpis(self):
        assert business_type_profile("home_services")["kpis"] == list(DEFAULT_KPIS)

    def test_catalog_shape(self):
        catalog = business_type_catalog()
        assert {c["key"] for c in catalog} == set(BUSINESS_TYPES)
        for c in catalog:
            assert set(c) == {"key", "label", "property_based"}

    def test_unknown_key_falls_back(self):
        assert get_business_type("nonsense").key == DEFAULT_BUSINESS_TYPE
        assert resolve_terminology("insurance_agency")["lead"] == "Client"
        assert resolve_terminology("insurance_agency")["quote"] == "Quote"  # base fallback
