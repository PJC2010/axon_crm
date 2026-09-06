"""Tests for the org-detail controls in api/routes/admin.py: edit org, limit
overrides, schedule deactivation, session revocation, the audit vocabulary
endpoint and the audit feed's denormalized admin name. Fake-conn style."""
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

import api.scheduler as sched  # noqa: E402
import api.territory as territory  # noqa: E402
from api.admin_logic import AUDIT_ACTIONS  # noqa: E402
from api.business_types import BUSINESS_TYPES  # noqa: E402
from api.routes.admin import (  # noqa: E402
    AdminAccountUpdate, AdminLimits, admin_audit_actions, admin_audit_log,
    admin_deactivate_schedule, admin_revoke_sessions, admin_set_limits,
    admin_update_account,
)
from tests.fakeconn import Conn, first_index, sql_matching  # noqa: E402

ADMIN = {"id": 7, "username": "pete", "account_id": 1}
ACCOUNT_COLS = ["id", "name", "business_type", "created_at", "review_link"]
PLAN_COLS = ["plan_name", "scoring_monthly_limit", "territory_limit"]
USER_COLS = ["id", "username", "email", "role", "is_active", "email_verified",
             "is_platform_admin", "account_id", "created_at", "last_login_at"]
SCHEDULE_COLS = ["zip", "is_active"]
OTHER_TYPE = next(k for k in BUSINESS_TYPES if k != "home_services")


def _account(review_link=None):
    return ("FROM accounts WHERE id",
            (ACCOUNT_COLS, [(9, "Blue Sky Roofing", "home_services", "2026-01-01", review_link)]))


def _audit(conn):
    rows = sql_matching(conn, "INSERT INTO admin_audit_log")
    assert len(rows) == 1
    params = rows[0][1]
    return params[2], params[5].adapted


def _usage_script(plan=("growth", None, None), reveals=18, zips=("77001", "77002")):
    """Everything _usage_block reads, most-specific patterns first."""
    return [
        _account(),
        ("SELECT plan_name, scoring_monthly_limit, territory_limit FROM account_plans",
         (PLAN_COLS, [plan])),
        ("SELECT plan_name, scoring_monthly_limit FROM account_plans",
         (["plan_name", "scoring_monthly_limit"], [(plan[0], plan[1])])),
        ("SELECT plan_name, territory_limit FROM account_plans",
         (["plan_name", "territory_limit"], [(plan[0], plan[2])])),
        ("FROM scoring_reveals", (["n"], [(reveals,)])),
        ("SELECT zip FROM pipeline_schedules", (["zip"], [(z,) for z in zips])),
    ]


class TestUpdateAccount:
    def test_writes_only_the_changed_columns(self):
        conn = Conn([_account()])
        admin_update_account(
            account_id=9,
            body=AdminAccountUpdate(name="Blue Sky Roofing", business_type=OTHER_TYPE,
                                    review_link=" https://g.page/blue-sky "),
            admin=ADMIN, db=conn)
        (sql, params), = sql_matching(conn, "UPDATE accounts SET")
        assert "business_type = %s" in sql and "review_link = %s" in sql
        assert "name = %s" not in sql            # unchanged → not written
        assert params == (OTHER_TYPE, "https://g.page/blue-sky", 9)

    def test_audit_row_carries_the_diff_and_precedes_the_commit(self):
        conn = Conn([_account()])
        admin_update_account(account_id=9, body=AdminAccountUpdate(business_type=OTHER_TYPE),
                             admin=ADMIN, db=conn)
        action, detail = _audit(conn)
        assert action == "account.update"
        assert detail == {"business_type": {"old": "home_services", "new": OTHER_TYPE}}
        assert (first_index(conn, "UPDATE accounts")
                < first_index(conn, "INSERT INTO admin_audit_log")
                < first_index(conn, "COMMIT"))
        assert conn.commits == 1

    def test_no_change_writes_nothing(self):
        conn = Conn([_account()])
        admin_update_account(account_id=9, body=AdminAccountUpdate(name="Blue Sky Roofing"),
                             admin=ADMIN, db=conn)
        assert not sql_matching(conn, "UPDATE accounts")
        assert not sql_matching(conn, "admin_audit_log")
        assert conn.commits == 0

    def test_empty_review_link_clears_it(self):
        conn = Conn([_account(review_link="https://old.example")])
        admin_update_account(account_id=9, body=AdminAccountUpdate(review_link=""),
                             admin=ADMIN, db=conn)
        (sql, params), = sql_matching(conn, "UPDATE accounts SET")
        assert sql.endswith("SET review_link = %s WHERE id = %s")
        assert params == (None, 9)

    @pytest.mark.parametrize("body", [
        AdminAccountUpdate(),
        AdminAccountUpdate(business_type="spaceship"),
        AdminAccountUpdate(name="   "),
        AdminAccountUpdate(review_link="not a url"),
    ])
    def test_invalid_bodies_are_400(self, body):
        conn = Conn([_account()])
        with pytest.raises(HTTPException) as exc:
            admin_update_account(account_id=9, body=body, admin=ADMIN, db=conn)
        assert exc.value.status_code == 400
        assert not sql_matching(conn, "UPDATE accounts")

    def test_unknown_account_is_404(self):
        conn = Conn([("FROM accounts WHERE id", (ACCOUNT_COLS, []))])
        with pytest.raises(HTTPException) as exc:
            admin_update_account(account_id=9, body=AdminAccountUpdate(name="X"),
                                 admin=ADMIN, db=conn)
        assert exc.value.status_code == 404


class TestSetLimits:
    def test_refused_without_a_plan_row(self):
        conn = Conn([_account(), ("FROM account_plans WHERE account_id", (PLAN_COLS, []))])
        with pytest.raises(HTTPException) as exc:
            admin_set_limits(account_id=9, body=AdminLimits(scoring_monthly_limit=50),
                             admin=ADMIN, db=conn)
        assert exc.value.status_code == 409
        assert not sql_matching(conn, "UPDATE account_plans")

    def test_scoring_override_leaves_territory_alone_and_skips_the_trim(self, monkeypatch):
        monkeypatch.setattr(territory, "trim_schedules_to_limit",
                            lambda db, aid: pytest.fail("trim ran without a territory change"))
        conn = Conn(_usage_script(plan=("growth", None, 2)))
        result = admin_set_limits(account_id=9, body=AdminLimits(scoring_monthly_limit=250),
                                  admin=ADMIN, db=conn)
        (sql, params), = sql_matching(conn, "UPDATE account_plans SET")
        assert params == (250, 2, 9)             # territory_limit preserved
        action, detail = _audit(conn)
        assert action == "account.limits_set"
        assert detail == {"scoring_monthly_limit": {"old": None, "new": 250},
                          "trimmed_schedule_ids": []}
        assert first_index(conn, "INSERT INTO admin_audit_log") < first_index(conn, "COMMIT")
        assert set(result) == {"scoring", "territories"}
        assert result["scoring"]["used"] == 18
        assert result["territories"]["used"] == 2 and result["territories"]["zips"] == ["77001", "77002"]

    def test_territory_change_trims_schedules_inside_the_transaction(self, monkeypatch):
        seen = {}

        def fake_trim(db, aid):
            seen["commits_at_call"] = db.commits
            return [5, 6]

        monkeypatch.setattr(territory, "trim_schedules_to_limit", fake_trim)
        conn = Conn(_usage_script())
        admin_set_limits(account_id=9, body=AdminLimits(territory_limit=1), admin=ADMIN, db=conn)
        assert seen["commits_at_call"] == 0     # rode the same transaction
        (sql, params), = sql_matching(conn, "UPDATE account_plans SET")
        assert params == (None, 1, 9)
        _, detail = _audit(conn)
        assert detail == {"territory_limit": {"old": None, "new": 1},
                          "trimmed_schedule_ids": [5, 6]}

    def test_explicit_null_returns_to_the_plan_default(self, monkeypatch):
        monkeypatch.setattr(territory, "trim_schedules_to_limit", lambda db, aid: [])
        conn = Conn(_usage_script(plan=("growth", 500, 9)))
        admin_set_limits(account_id=9,
                         body=AdminLimits(scoring_monthly_limit=None, territory_limit=None),
                         admin=ADMIN, db=conn)
        (sql, params), = sql_matching(conn, "UPDATE account_plans SET")
        assert params == (None, None, 9)
        _, detail = _audit(conn)
        assert detail["scoring_monthly_limit"] == {"old": 500, "new": None}

    @pytest.mark.parametrize("body", [AdminLimits(), AdminLimits(scoring_monthly_limit=-1)])
    def test_invalid_bodies_are_400(self, body):
        conn = Conn(_usage_script())
        with pytest.raises(HTTPException) as exc:
            admin_set_limits(account_id=9, body=body, admin=ADMIN, db=conn)
        assert exc.value.status_code == 400
        assert not sql_matching(conn, "UPDATE account_plans")


class TestDeactivateSchedule:
    def test_unknown_schedule_is_404(self):
        conn = Conn([_account(), ("FROM pipeline_schedules WHERE id", (SCHEDULE_COLS, []))])
        with pytest.raises(HTTPException) as exc:
            admin_deactivate_schedule(account_id=9, schedule_id=3, admin=ADMIN, db=conn)
        assert exc.value.status_code == 404

    def test_already_inactive_is_409(self):
        conn = Conn([_account(),
                     ("FROM pipeline_schedules WHERE id", (SCHEDULE_COLS, [("77001", False)]))])
        with pytest.raises(HTTPException) as exc:
            admin_deactivate_schedule(account_id=9, schedule_id=3, admin=ADMIN, db=conn)
        assert exc.value.status_code == 409
        assert not sql_matching(conn, "UPDATE pipeline_schedules")

    def test_deactivates_audits_commits_then_tells_the_scheduler(self, monkeypatch):
        removed = {}
        conn = Conn([_account(),
                     ("FROM pipeline_schedules WHERE id", (SCHEDULE_COLS, [("77001", True)]))])
        monkeypatch.setattr(sched, "remove_schedule_job",
                            lambda sid: removed.update(sid=sid, commits=conn.commits))
        result = admin_deactivate_schedule(account_id=9, schedule_id=3, admin=ADMIN, db=conn)
        (sql, params), = sql_matching(conn, "UPDATE pipeline_schedules SET is_active = FALSE")
        assert params == (3, 9)
        action, detail = _audit(conn)
        assert action == "schedule.deactivate" and detail == {"account_id": 9, "zip": "77001"}
        assert first_index(conn, "INSERT INTO admin_audit_log") < first_index(conn, "COMMIT")
        assert removed == {"sid": 3, "commits": 1}   # told after the commit, not before
        assert result == {"ok": True, "schedule_id": 3, "is_active": False}


class TestRevokeSessions:
    @staticmethod
    def _user(uid=42):
        return ("FROM users WHERE id",
                (USER_COLS, [(uid, "dana", "dana@x.com", "owner", True, True, False, 9,
                              "2026-01-01", None)]))

    def test_stamps_password_changed_at_and_audits(self):
        conn = Conn([self._user()])
        result = admin_revoke_sessions(user_id=42, admin=ADMIN, db=conn)
        (sql, params), = sql_matching(conn, "UPDATE users SET password_changed_at = NOW()")
        assert params == (42,)
        action, detail = _audit(conn)
        assert action == "user.sessions_revoked"
        assert detail == {"username": "dana", "account_id": 9}
        assert first_index(conn, "INSERT INTO admin_audit_log") < first_index(conn, "COMMIT")
        assert result == {"ok": True, "user_id": 42, "self": False}

    def test_self_is_allowed_and_flagged(self):
        conn = Conn([self._user(uid=7)])
        assert admin_revoke_sessions(user_id=7, admin=ADMIN, db=conn)["self"] is True

    def test_unknown_user_is_404(self):
        conn = Conn([("FROM users WHERE id", (USER_COLS, []))])
        with pytest.raises(HTTPException) as exc:
            admin_revoke_sessions(user_id=1, admin=ADMIN, db=conn)
        assert exc.value.status_code == 404


class TestAuditFeed:
    def test_actions_endpoint_serves_the_registry(self):
        assert admin_audit_actions() == {"actions": list(AUDIT_ACTIONS)}
        assert "account.delete" in AUDIT_ACTIONS and "user.delete" in AUDIT_ACTIONS

    def test_admin_name_survives_the_admin_being_deleted(self):
        cols = ["id", "admin_user_id", "admin_username", "action", "target_type",
                "target_id", "detail", "created_at", "_total"]
        conn = Conn([("FROM admin_audit_log l",
                      (cols, [(1, None, "pete", "user.delete", "user", "3", {}, "2026-01-01", 1)]))])
        page = admin_audit_log(admin_user_id=None, action=None, page=1, page_size=50, db=conn)
        (sql, _), = sql_matching(conn, "FROM admin_audit_log l")
        assert "COALESCE(l.admin_username, u.username) AS admin_username" in sql
        assert page["items"][0]["admin_username"] == "pete" and page["total"] == 1
