"""Invariants for the business-type preset packs (Phase 6): every preset's
terminology, modules, stages, fields, workflows, and KPI ids must be internally
consistent — a broken pack would provision a broken account."""
import pytest

from api.business_types import (
    BASE_TERMINOLOGY, BUSINESS_TYPES, DEFAULT_BUSINESS_TYPE, DEFAULT_KPIS,
    DEFAULT_LIST_COLUMNS,
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

# Every list-table column key a preset may reference; each must have a renderer
# in frontend/components/lead/leadColumns.tsx.
KNOWN_LIST_COLUMNS = {
    "record", "score", "status", "category", "job_value", "x_date",
    "year_built", "equity", "garage", "last_sale",
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
    def test_list_columns_are_known(self, key):
        cols = BUSINESS_TYPES[key].list_columns
        assert cols, f"{key}: needs at least one list column"
        assert len(cols) == len(set(cols)), f"{key}: duplicate list columns"
        assert set(cols) <= KNOWN_LIST_COLUMNS, (
            f"{key}: unknown list column(s) — add a renderer in "
            f"frontend/components/lead/leadColumns.tsx"
        )

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
        pack must never provision a rule the engine silently skips. Rules
        referencing default templates by name are validated as the seeder
        resolves them (template_names → per-channel ids)."""
        template_names = {t["name"] for t in BUSINESS_TYPES[key].default_templates}
        for rule in BUSINESS_TYPES[key].default_workflows:
            action_config = dict(rule.get("action_config", {}))
            names = action_config.pop("template_names", None)
            if names:
                # every referenced template must exist in the pack
                assert set(names.values()) <= template_names, rule["name"]
                action_config["templates"] = {ch: i + 1 for i, ch in enumerate(names)}
            _validate_rule(
                rule.get("trigger_type", "status_change"),
                rule.get("trigger_config", {}),
                rule.get("action_type", "create_task"),
                action_config,
            )
            assert rule.get("name")


class TestInsurancePack:
    def test_renewal_ladder(self):
        bt = BUSINESS_TYPES["insurance_agency"]
        offsets = sorted(
            r["trigger_config"]["offset_days"]
            for r in bt.default_workflows if r["trigger_type"] == "date_offset"
        )
        # -30 twice: the agent's task and the client-facing reminder message.
        assert offsets == [-90, -30, -30, -7]
        for r in bt.default_workflows:
            if r["trigger_type"] == "date_offset":
                assert r["trigger_config"]["source"] == "policies"
                assert r["trigger_config"]["date_field"] == "expiration_date"

    def test_client_reminder_rule_and_templates(self):
        bt = BUSINESS_TYPES["insurance_agency"]
        reminder = next(r for r in bt.default_workflows if r["action_type"] == "send_template")
        assert reminder["action_config"]["delivery"] == "sms_first"
        names = reminder["action_config"]["template_names"]
        by_name = {t["name"]: t for t in bt.default_templates}
        assert by_name[names["sms"]]["channel"] == "sms"
        assert by_name[names["email"]]["channel"] == "email"
        # Reminder templates must name the expiring policy and its date.
        for t in by_name.values():
            assert "{{expiration_date}}" in t["body"] or "{{expiration_date}}" in (t.get("subject") or "")

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

    def test_profile_includes_list_columns(self):
        cols = business_type_profile("insurance_agency")["list_columns"]
        assert cols == ["record", "score", "category", "job_value", "x_date", "status"]
        # Property columns are dropped for non-property verticals.
        assert "year_built" not in cols

    def test_default_profile_keeps_property_columns(self):
        cols = business_type_profile("home_services")["list_columns"]
        assert cols == list(DEFAULT_LIST_COLUMNS)
        assert "year_built" in cols

    def test_catalog_shape(self):
        catalog = business_type_catalog()
        assert {c["key"] for c in catalog} == set(BUSINESS_TYPES)
        for c in catalog:
            assert set(c) == {"key", "label", "property_based"}

    def test_unknown_key_falls_back(self):
        assert get_business_type("nonsense").key == DEFAULT_BUSINESS_TYPE
        assert resolve_terminology("insurance_agency")["lead"] == "Client"
        assert resolve_terminology("insurance_agency")["quote"] == "Quote"  # base fallback
