"""Tests for the pure platform-admin logic (api/admin_logic.py) and the shared
plan-change resolver (api/entitlements.py::resolve_plan_modules). No DB."""
import pytest

from api.admin_logic import (
    build_reset_url, clamp_page, classify_login_failure, evaluate_config_checks,
    parse_forwarded_for, validate_admin_user_update,
)
from api.entitlements import MODULE_KEYS, PLAN_CATALOG, resolve_plan_modules


class TestResolvePlanModules:
    def test_each_plan_gets_its_catalog_defaults(self):
        for plan, granted in PLAN_CATALOG.items():
            modules = resolve_plan_modules(plan)
            assert set(modules) == set(MODULE_KEYS)
            assert {k for k, v in modules.items() if v} == granted

    def test_enable_beyond_plan(self):
        modules = resolve_plan_modules("starter", enable=["map"])
        assert modules["map"] is True
        assert modules["prospecting"] is True
        assert modules["invoicing"] is False

    def test_disable_within_plan(self):
        modules = resolve_plan_modules("pro", disable=["calls"])
        assert modules["calls"] is False

    def test_disable_wins_over_enable(self):
        # Applied in order: enables first, then disables — an explicit off wins.
        modules = resolve_plan_modules("starter", enable=["map"], disable=["map"])
        assert modules["map"] is False

    def test_unknown_plan_raises(self):
        with pytest.raises(ValueError, match="Unknown plan"):
            resolve_plan_modules("enterprise")

    def test_unknown_module_raises(self):
        with pytest.raises(ValueError, match="Unknown module"):
            resolve_plan_modules("pro", enable=["time_travel"])


class TestClassifyLoginFailure:
    def test_unknown_user(self):
        assert classify_login_failure(None, False) == "unknown_user"

    def test_bad_password(self):
        assert classify_login_failure({"id": 1, "is_active": True}, False) == "bad_password"

    def test_inactive(self):
        assert classify_login_failure({"id": 1, "is_active": False}, True) == "inactive"


class TestParseForwardedFor:
    def test_absent_header_falls_back(self):
        assert parse_forwarded_for(None, "1.2.3.4") == "1.2.3.4"
        assert parse_forwarded_for("", "1.2.3.4") == "1.2.3.4"

    def test_single_ip(self):
        assert parse_forwarded_for("9.9.9.9", "fallback") == "9.9.9.9"

    def test_multi_hop_takes_last(self):
        # Only the last entry was appended by our own proxy; earlier ones are
        # client-suppliable.
        assert parse_forwarded_for("6.6.6.6, 7.7.7.7, 8.8.8.8", "x") == "8.8.8.8"

    def test_whitespace_and_empty_entries(self):
        assert parse_forwarded_for("  6.6.6.6 ,  , 8.8.8.8  ", "x") == "8.8.8.8"
        assert parse_forwarded_for(" , ,", "fallback") == "fallback"


class TestBuildResetUrl:
    def test_shape_matches_frontend_page(self):
        assert build_reset_url("https://axonhtx.com", "tok123") == \
            "https://axonhtx.com/reset-password?token=tok123"

    def test_trailing_slash_stripped(self):
        assert build_reset_url("https://axonhtx.com/", "t") == \
            "https://axonhtx.com/reset-password?token=t"


class TestClampPage:
    def test_defaults_pass_through(self):
        assert clamp_page(3, 50) == (3, 50)

    def test_bounds(self):
        assert clamp_page(0, 0) == (1, 1)
        assert clamp_page(-5, 10_000) == (1, 100)
        assert clamp_page(None, None) == (1, 1)


class TestValidateAdminUserUpdate:
    def test_empty_body(self):
        assert validate_admin_user_update({}, is_self=False) == ["No fields to update."]

    def test_bad_role(self):
        problems = validate_admin_user_update({"role": "superuser"}, is_self=False)
        assert any("Role must be" in p for p in problems)

    def test_valid_role_change(self):
        assert validate_admin_user_update({"role": "sales_rep"}, is_self=False) == []

    def test_self_deactivate_blocked(self):
        problems = validate_admin_user_update({"is_active": False}, is_self=True)
        assert any("deactivate your own" in p for p in problems)

    def test_other_deactivate_allowed(self):
        assert validate_admin_user_update({"is_active": False}, is_self=False) == []

    def test_self_revoke_blocked(self):
        problems = validate_admin_user_update({"is_platform_admin": False}, is_self=True)
        assert any("platform-admin" in p for p in problems)

    def test_self_grantlike_changes_allowed(self):
        # Setting truthy values on yourself is harmless.
        assert validate_admin_user_update(
            {"is_active": True, "is_platform_admin": True}, is_self=True) == []


class TestEvaluateConfigChecks:
    BASE = {
        "jwt_secret_set": True,
        "allow_insecure_dev_jwt": False,
        "app_base_url": "https://axonhtx.com",
        "resend_api_key_set": True,
        "resend_from_email_set": True,
        "billing_configured": True,
        "stripe_billing_webhook_secret_set": True,
        "admin_notification_email_set": True,
        "self_serve_signup": True,
        "twilio_configured": True,
    }

    def _by_key(self, checks):
        return {c["key"]: c for c in checks}

    def test_all_configured_has_no_errors_or_warnings(self):
        checks = self._by_key(evaluate_config_checks(self.BASE))
        assert not [c for c in checks.values() if c["status"] in ("error", "warn")]

    def test_missing_jwt_secret_is_error(self):
        checks = self._by_key(evaluate_config_checks({**self.BASE, "jwt_secret_set": False}))
        assert checks["jwt_secret_set"]["status"] == "error"

    def test_insecure_dev_jwt_is_error(self):
        checks = self._by_key(evaluate_config_checks({**self.BASE, "allow_insecure_dev_jwt": True}))
        assert checks["insecure_dev_jwt"]["status"] == "error"

    def test_localhost_base_url_warns(self):
        checks = self._by_key(evaluate_config_checks(
            {**self.BASE, "app_base_url": "http://localhost:3000"}))
        assert checks["app_base_url"]["status"] == "warn"

    def test_api_origin_base_url_warns(self):
        checks = self._by_key(evaluate_config_checks(
            {**self.BASE, "app_base_url": "https://axon-crm-api.onrender.com"}))
        assert checks["app_base_url"]["status"] == "warn"

    def test_missing_email_warns(self):
        checks = self._by_key(evaluate_config_checks({**self.BASE, "resend_api_key_set": False}))
        assert checks["email_configured"]["status"] == "warn"

    def test_every_check_is_well_formed(self):
        for check in evaluate_config_checks(self.BASE):
            assert set(check) == {"key", "label", "status", "detail"}
            assert check["status"] in ("ok", "warn", "error", "info")
