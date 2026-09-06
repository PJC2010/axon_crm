"""Tests for the pure platform-admin logic (api/admin_logic.py) and the shared
plan-change resolver (api/entitlements.py::resolve_plan_modules). No DB."""
import pytest

from api.admin_logic import (
    build_leftover_probe_sql, build_reset_url, clamp_page, classify_login_failure,
    evaluate_config_checks, parse_forwarded_for, validate_account_delete,
    validate_admin_user_update, validate_user_delete,
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


class TestValidateUserDelete:
    REP = {"id": 5, "role": "sales_rep", "is_platform_admin": False}
    OWNER = {"id": 5, "role": "owner", "is_platform_admin": False}

    def test_plain_rep_with_colleagues(self):
        assert validate_user_delete(self.REP, admin_id=1, siblings=3, other_owners=1) == []

    def test_self_delete_blocked(self):
        problems = validate_user_delete(
            {**self.REP, "id": 1}, admin_id=1, siblings=3, other_owners=1)
        assert any("your own account" in p for p in problems)

    def test_platform_admin_blocked(self):
        problems = validate_user_delete(
            {**self.REP, "is_platform_admin": True}, admin_id=1, siblings=3, other_owners=1)
        assert any("platform-admin" in p for p in problems)

    def test_last_user_in_org_blocked(self):
        problems = validate_user_delete(self.OWNER, admin_id=1, siblings=0, other_owners=0)
        assert any("delete the organization instead" in p for p in problems)

    def test_only_owner_blocked(self):
        problems = validate_user_delete(self.OWNER, admin_id=1, siblings=2, other_owners=0)
        assert any("only owner" in p for p in problems)

    def test_owner_with_a_co_owner_allowed(self):
        assert validate_user_delete(self.OWNER, admin_id=1, siblings=2, other_owners=1) == []

    def test_last_user_message_wins_over_only_owner(self):
        # Both are true of a solo owner; reporting only the actionable one keeps
        # the error from suggesting you promote a colleague who doesn't exist.
        problems = validate_user_delete(self.OWNER, admin_id=1, siblings=0, other_owners=0)
        assert len(problems) == 1


class TestValidateAccountDelete:
    ACCOUNT = {"id": 9, "name": "Blue Sky Roofing"}
    OK = {"admin_account_id": 1, "confirm_name": "Blue Sky Roofing",
          "has_subscription": False, "platform_admins": []}

    def test_valid(self):
        assert validate_account_delete(self.ACCOUNT, **self.OK) == []

    def test_own_org_blocked(self):
        problems = validate_account_delete(self.ACCOUNT, **{**self.OK, "admin_account_id": 9})
        assert any("organization you belong to" in p for p in problems)

    def test_live_subscription_blocked(self):
        problems = validate_account_delete(self.ACCOUNT, **{**self.OK, "has_subscription": True})
        assert any("Stripe" in p for p in problems)

    def test_platform_admin_inside_org_blocked(self):
        problems = validate_account_delete(
            self.ACCOUNT, **{**self.OK, "platform_admins": ["pete", "dana"]})
        assert any("pete, dana" in p for p in problems)

    def test_name_must_match_exactly(self):
        for typed in ("blue sky roofing", "Blue Sky", "", "Blue  Sky Roofing"):
            problems = validate_account_delete(self.ACCOUNT, **{**self.OK, "confirm_name": typed})
            assert any("exactly" in p for p in problems), typed

    def test_surrounding_whitespace_forgiven(self):
        # A pasted name picks up spaces; the characters that matter still match.
        assert validate_account_delete(
            self.ACCOUNT, **{**self.OK, "confirm_name": "  Blue Sky Roofing "}) == []

    def test_admin_without_an_org_is_not_blocked_by_the_self_guard(self):
        assert validate_account_delete(self.ACCOUNT, **{**self.OK, "admin_account_id": None}) == []


class TestBuildLeftoverProbeSql:
    def test_probes_every_table(self):
        sql = build_leftover_probe_sql(["properties", "tasks"])
        assert sql.count("UNION ALL") == 1
        assert "FROM properties WHERE account_id = %(id)s" in sql
        assert "FROM tasks WHERE account_id = %(id)s" in sql

    def test_binds_the_id_by_name_only(self):
        # Named param throughout: psycopg2 binds positional %s in text order,
        # and this statement repeats one value once per table.
        sql = build_leftover_probe_sql(["properties", "tasks", "invoices"])
        assert "%s" not in sql.replace("%(id)s", "")
        assert sql.count("%(id)s") == 3

    def test_empty_list_yields_a_query_with_no_rows(self):
        assert "WHERE FALSE" in build_leftover_probe_sql([])

    def test_rejects_anything_that_is_not_a_bare_identifier(self):
        for bad in ["users; DROP TABLE accounts", "public.users", 'u"x', "Users", ""]:
            with pytest.raises(ValueError, match="Refusing to interpolate"):
                build_leftover_probe_sql(["properties", bad])


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


# ── Additions for the org controls / usage / data-health surfaces ─────────────

import inspect  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from api.admin_logic import (  # noqa: E402
    AUDIT_ACTIONS, data_health_alerts, effective_scoring_limit, match_rate, merge_usage,
    normalize_account_update, overlay_account_state, overlay_zip_rule_state, paginate_rows,
    pct, rule_state, rule_summary, sort_usage, validate_account_limits,
    validate_account_update,
)


class TestAuditActionsRegistry:
    def test_every_recorded_action_is_registered(self):
        os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")
        from api.routes import admin, admin_data, admin_usage
        pattern = re.compile(r'record_admin_action\(\s*db,\s*admin,\s*"([a-z_.]+)"')
        found: set[str] = set()
        for module in (admin, admin_data, admin_usage):
            found |= set(pattern.findall(inspect.getsource(module)))
        assert found, "the probe found no audit calls — did the call shape change?"
        assert found <= set(AUDIT_ACTIONS), found - set(AUDIT_ACTIONS)

    def test_registry_is_sorted_and_unique(self):
        assert list(AUDIT_ACTIONS) == sorted(set(AUDIT_ACTIONS))


class TestNormalizeAccountUpdate:
    def test_trims_and_drops_unknown_keys(self):
        assert normalize_account_update({"name": "  Blue Sky ", "hashed_pw": "x"}) == {"name": "Blue Sky"}

    def test_empty_review_link_means_clear(self):
        assert normalize_account_update({"review_link": ""}) == {"review_link": None}
        assert normalize_account_update({"review_link": None}) == {"review_link": None}

    def test_absent_fields_stay_absent(self):
        assert normalize_account_update({}) == {}


class TestValidateAccountUpdate:
    TYPES = {"home_services", "retail"}

    def test_empty_is_a_problem(self):
        assert validate_account_update({}, self.TYPES) == ["No fields to update."]

    def test_name_uses_the_shared_company_rule(self):
        assert any("required" in p for p in validate_account_update({"name": ""}, self.TYPES))
        assert any("80" in p for p in validate_account_update({"name": "x" * 81}, self.TYPES))
        assert validate_account_update({"name": "Blue Sky Roofing"}, self.TYPES) == []

    def test_business_type_must_be_known(self):
        assert validate_account_update({"business_type": "retail"}, self.TYPES) == []
        assert any("Unknown business type" in p
                   for p in validate_account_update({"business_type": "spaceship"}, self.TYPES))

    def test_review_link_is_an_http_url_or_null(self):
        assert validate_account_update({"review_link": None}, self.TYPES) == []
        assert validate_account_update({"review_link": "https://g.page/x"}, self.TYPES) == []
        for bad in ("g.page/x", "ftp://x", "https://has space", "https://" + "a" * 500):
            assert validate_account_update({"review_link": bad}, self.TYPES), bad


class TestValidateAccountLimits:
    def test_empty_is_a_problem(self):
        assert validate_account_limits({}) == ["No limits to update."]

    def test_null_and_non_negative_ints_are_fine(self):
        assert validate_account_limits({"scoring_monthly_limit": None, "territory_limit": 0}) == []
        assert validate_account_limits({"territory_limit": 3}) == []

    def test_rejects_negatives_bools_and_unknown_keys(self):
        assert validate_account_limits({"scoring_monthly_limit": -1})
        assert validate_account_limits({"territory_limit": True})
        assert validate_account_limits({"modules": {}})


class TestUsageHelpers:
    LIMITS = {"starter": 25, "growth": 100, "pro": None}
    COLS = {"rentcast": ("rentcast_requests",), "calls": ("calls", "call_minutes")}
    ACCOUNTS = [{"id": 1, "name": "Zed", "plan_name": "pro", "scoring_monthly_limit": None},
                {"id": 2, "name": "acme", "plan_name": "starter", "scoring_monthly_limit": 40},
                {"id": 3, "name": "Nolan", "plan_name": None, "scoring_monthly_limit": None}]

    def test_effective_scoring_limit(self):
        assert effective_scoring_limit("starter", None, self.LIMITS) == 25
        assert effective_scoring_limit("starter", 40, self.LIMITS) == 40
        assert effective_scoring_limit("pro", None, self.LIMITS) is None
        assert effective_scoring_limit(None, None, self.LIMITS) is None   # no plan row = unlimited

    def test_merge_fills_zero_and_degrades_to_none(self):
        rows = merge_usage(self.ACCOUNTS,
                           {"rentcast": [{"account_id": 1, "rentcast_requests": 9}], "calls": None},
                           self.COLS, self.LIMITS)
        by = {r["account_id"]: r for r in rows}
        assert by[1]["rentcast_requests"] == 9 and by[2]["rentcast_requests"] == 0
        assert by[1]["calls"] is None and by[3]["call_minutes"] is None
        assert by[2]["scoring_limit"] == 40 and by[3]["scoring_limit"] is None

    def test_sort_name_is_case_insensitive_and_metrics_put_unknown_last(self):
        rows = merge_usage(self.ACCOUNTS,
                           {"rentcast": [{"account_id": 2, "rentcast_requests": 5},
                                         {"account_id": 3, "rentcast_requests": 7}], "calls": None},
                           self.COLS, self.LIMITS)
        assert [r["name"] for r in sort_usage(rows, "name", ("rentcast_requests",))] == ["acme", "Nolan", "Zed"]
        assert [r["account_id"] for r in sort_usage(rows, "rentcast_requests", ("rentcast_requests",))] == [3, 2, 1]
        rows[0]["rentcast_requests"] = None
        assert sort_usage(rows, "rentcast_requests", ("rentcast_requests",))[-1]["rentcast_requests"] is None

    def test_sort_whitelist(self):
        with pytest.raises(ValueError):
            sort_usage([], "hashed_pw", ("calls",))

    def test_paginate(self):
        assert paginate_rows(list(range(7)), 2, 3) == [3, 4, 5]
        assert paginate_rows(list(range(7)), 4, 3) == []


class TestDataHealthOverlay:
    def test_pct_and_match_rate_handle_unknowns(self):
        assert pct(1, 4) == 25.0 and pct(0, 4) == 0.0
        assert pct(None, 4) is None and pct(3, 0) is None and pct(3, None) is None
        assert match_rate(1000, 950) == 0.95
        assert match_rate(0, 0) is None and match_rate(None, 5) is None

    def test_rule_state(self):
        assert rule_state(None, "h") == "unstamped"
        assert rule_state("h", "h") == "current"
        assert rule_state("old", "h") == "stale"

    def test_zip_overlay_marks_each_zip_against_the_parcel_hash(self):
        zips = [{"zip": "77001", "parcels": 5}, {"zip": "77002", "parcels": 1}]
        stamps = [{"zip": "77001", "rule_hash": "pc", "classified_at": "t1"}]
        out = overlay_zip_rule_state(zips, stamps, "pc")
        assert out[0]["rule_state"] == "current" and out[0]["classified_at"] == "t1"
        assert out[1]["rule_state"] == "unstamped" and out[1]["classified_at"] is None

    def test_account_overlay_joins_live_state_and_survives_org_churn(self):
        rows = [{"account_id": 1, "properties": 900, "with_coords": 1, "unclassified": 0, "excludable": 0},
                {"account_id": 99, "properties": 5, "with_coords": 1, "unclassified": 0, "excludable": 0}]
        names = {1: "Acme", 2: "New"}
        stamps = [{"account_id": 1, "rule_hash": "old", "classified_at": "t"}]
        out = overlay_account_state(rows, names, stamps, {2: 4}, "hp")
        assert [r["account_id"] for r in out] == [1, 2]      # 99 gone, 2 appended
        assert out[0]["rule_state"] == "stale" and out[0]["unclassified_live"] == 0
        assert out[1]["properties"] is None and out[1]["unclassified_live"] == 4
        # A cut-off live read is None on every row, never 0.
        assert all(r["unclassified_live"] is None
                   for r in overlay_account_state(rows, names, stamps, None, "hp"))
        assert rule_summary([{"rule_state": "stale"}], out) == {
            "accounts_stale": 1, "accounts_unstamped": 1, "zips_stale": 1, "zips_unstamped": 0}


class TestDataHealthAlerts:
    NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)

    def _snapshot(self, hours_old=3, **report):
        base = {"apn_match": {"with_apn": 100, "matched": 99}, "parcels": {"unclassified": 0},
                "city_sanity": {}, "blocks_failed": []}
        return {"started_at": self.NOW - timedelta(hours=hours_old), "status": "ok",
                "report": {**base, **report}}

    def _keys(self, snapshot, live=None, rule=None):
        return [a["key"] for a in data_health_alerts(snapshot, live, rule, now=self.NOW)]

    def test_clean_snapshot_raises_nothing(self):
        assert self._keys(self._snapshot()) == []

    def test_no_snapshot(self):
        assert self._keys(None) == ["no_snapshot"]

    def test_each_condition_has_its_alert(self):
        assert "snapshot_stale" in self._keys(self._snapshot(hours_old=72))
        assert "blocks_failed" in self._keys(self._snapshot(blocks_failed=["hcad"]))
        assert "apn_match_rate" in self._keys(self._snapshot(apn_match={"with_apn": 100, "matched": 80}))
        assert "parcels_unclassified" in self._keys(self._snapshot(parcels={"unclassified": 5}))
        assert "mail_city_leak" in self._keys(self._snapshot(city_sanity={"parcels_mail_city_leak": 1}))
        assert "accounts_stale" in self._keys(self._snapshot(), rule={"accounts_stale": 2})
        assert "geocode_failed" in self._keys(self._snapshot(), live={"geocode_queue": {"failed": 3}})
        assert "hcad_source" in self._keys(self._snapshot(), live={"hcad_source": "none"})

    def test_every_alert_is_well_formed(self):
        for alert in data_health_alerts(self._snapshot(hours_old=72, blocks_failed=["x"]),
                                        {"hcad_source": "none", "geocode_queue": {"failed": 1}},
                                        {"zips_unstamped": 1}, now=self.NOW):
            assert set(alert) == {"key", "severity", "label", "detail"}
            assert alert["severity"] in ("error", "warn", "info")
