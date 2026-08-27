"""Tests for the platform-admin org-creation surface (api/routes/admin.py):
POST /admin/accounts and POST /admin/users' new_account mode, which share
_provision_org_with_owner. Fake-conn style — no live DB; the conn answers
whitespace-normalized SQL by first matching substring, so the tests survive
preset changes (extra templates/workflows) without re-scripting a sequence."""
import os

import psycopg2.errors
import pytest
from fastapi import HTTPException

# Importing the routes imports api.security, which refuses to load without a
# signing secret. Nothing here signs a token — this only calls the endpoint
# functions with a fake conn.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

from api.routes.admin import (  # noqa: E402
    AdminAccountCreate, AdminAccountOwner, AdminNewAccount, AdminUserCreate,
    admin_create_account, admin_create_user,
)


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _respond(self, flat_sql):
        for pattern, response in self._conn.script:
            if pattern in flat_sql:
                if isinstance(response, Exception):
                    raise response
                cols, rows = response
                self.description = [(c,) for c in cols] if cols else None
                self._rows = list(rows)
                return
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self._conn.executed.append((flat, params))
        self._respond(flat)

    def executemany(self, sql, seq):
        self._conn.executed.append((" ".join(sql.split()), list(seq)))
        self._rows = []

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = list(self._rows), []
        return rows


class _Conn:
    """COMMIT/ROLLBACK land in the same `executed` stream as the writes, so
    ordering (audit row before commit) can be asserted."""

    def __init__(self, script):
        self.script = list(script)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1
        self.executed.append(("COMMIT", None))

    def rollback(self):
        self.rollbacks += 1
        self.executed.append(("ROLLBACK", None))


ADMIN = {"id": 7, "username": "pete", "account_id": 1}

_USER_COLS = ["id", "username", "email", "role", "is_active", "email_verified",
              "is_platform_admin", "account_id", "created_at", "last_login_at"]


def _happy_script():
    return [
        ("INSERT INTO accounts", (None, [(101,)])),
        ("INSERT INTO account_plans", (None, [])),
        ("INSERT INTO record_field_defs", (None, [(1,)])),
        ("SELECT 1 FROM users WHERE username", (None, [])),   # base name is free
        ("INSERT INTO users", (None, [(55,)])),
        ("INSERT INTO account_billing", (None, [])),
        ("INSERT INTO message_templates", (None, [(201,)])),
        ("SELECT id FROM message_templates", (None, [(201,)])),
        ("SELECT 1 FROM workflow_rules", (None, [])),
        ("INSERT INTO workflow_rules", (None, [])),
        ("INSERT INTO admin_audit_log", (None, [])),
        # Response assembly after the commit:
        ("FROM accounts WHERE id",
         (["id", "name", "business_type", "created_at", "review_link"],
          [(101, "Blue Sky Roofing", "home_services", "2026-08-26", None)])),
        ("LEFT JOIN account_plans",
         (["plan_name", "billing_status", "trial_ends_at"],
          [("pro", "trialing", "2026-09-09")])),
        ("FROM users WHERE id",
         (_USER_COLS,
          [(55, "owner", "owner@blue.sky", "owner", True, True, False, 101,
            "2026-08-26", None)])),
    ]


def _account_body(**over):
    owner = over.pop("owner", {})
    return AdminAccountCreate(
        name=over.pop("name", "Blue Sky Roofing"),
        business_type=over.pop("business_type", "home_services"),
        owner=AdminAccountOwner(
            **{"email": "Owner@Blue.Sky", "password": "longenough1", **owner}),
    )


class TestAdminCreateAccount:
    def test_provisions_org_and_owner(self):
        conn = _Conn(_happy_script())
        result = admin_create_account(body=_account_body(), admin=ADMIN, db=conn)
        assert result["id"] == 101
        assert result["name"] == "Blue Sky Roofing"
        assert result["plan_name"] == "pro"
        assert result["billing_status"] == "trialing"
        assert result["owner"]["id"] == 55
        assert conn.commits == 1 and conn.rollbacks == 0

    def test_audit_rows_written_in_the_provisioning_transaction(self):
        conn = _Conn(_happy_script())
        admin_create_account(body=_account_body(), admin=ADMIN, db=conn)
        trail = [sql for sql, _ in conn.executed
                 if "admin_audit_log" in sql or sql == "COMMIT"]
        # account.create + user.create land before the commit, never after.
        assert len(trail) == 3 and trail[-1] == "COMMIT"
        actions = [p[2] for sql, p in conn.executed if "admin_audit_log" in sql]
        assert actions == ["account.create", "user.create"]

    def test_owner_email_normalized_and_starts_verified(self):
        conn = _Conn(_happy_script())
        admin_create_account(body=_account_body(), admin=ADMIN, db=conn)
        params = next(p for sql, p in conn.executed if "INSERT INTO users" in sql)
        assert params[1] == "owner@blue.sky"
        assert params[4] is True   # email_verified — no verification-email gate

    def test_org_name_is_stripped(self):
        conn = _Conn(_happy_script())
        admin_create_account(body=_account_body(name="  Blue Sky Roofing  "),
                             admin=ADMIN, db=conn)
        params = next(p for sql, p in conn.executed if "INSERT INTO accounts" in sql)
        assert params[0] == "Blue Sky Roofing"

    def test_validation_problems_are_a_400_before_any_write(self):
        conn = _Conn([])
        with pytest.raises(HTTPException) as exc:
            admin_create_account(
                body=_account_body(name="  ",
                                   owner={"email": "nope", "password": "short"}),
                admin=ADMIN, db=conn)
        assert exc.value.status_code == 400
        assert "Company or business name is required." in exc.value.detail
        assert "valid email" in exc.value.detail
        assert "at least 8 characters" in exc.value.detail
        assert conn.executed == []

    def test_unknown_business_type_rejected(self):
        conn = _Conn([])
        with pytest.raises(HTTPException) as exc:
            admin_create_account(body=_account_body(business_type="time_travel"),
                                 admin=ADMIN, db=conn)
        assert exc.value.status_code == 400
        assert "Unknown business type" in exc.value.detail
        assert conn.executed == []

    def test_duplicate_email_is_409_and_rolls_back(self):
        script = [(p, r) for p, r in _happy_script() if p != "INSERT INTO users"]
        script.insert(0, ("INSERT INTO users",
                          psycopg2.errors.UniqueViolation("duplicate email")))
        conn = _Conn(script)
        with pytest.raises(HTTPException) as exc:
            admin_create_account(body=_account_body(), admin=ADMIN, db=conn)
        assert exc.value.status_code == 409
        assert "already exists" in exc.value.detail
        assert conn.rollbacks == 1 and conn.commits == 0
        assert not any("admin_audit_log" in sql for sql, _ in conn.executed)

    def test_no_free_username_is_409_and_rolls_back(self):
        # Every candidate is taken → provision_owner gives up → 409, not a 500.
        script = [("SELECT 1 FROM users WHERE username", (None, [(1,)]))] + _happy_script()
        conn = _Conn(script)
        with pytest.raises(HTTPException) as exc:
            admin_create_account(body=_account_body(), admin=ADMIN, db=conn)
        assert exc.value.status_code == 409
        assert "free username" in exc.value.detail
        assert conn.rollbacks == 1 and conn.commits == 0


class TestAdminCreateUserNewOrgMode:
    """POST /admin/users with new_account must keep matching the org endpoint —
    both run _provision_org_with_owner."""

    def _body(self, **over):
        return AdminUserCreate(
            email=over.pop("email", "Owner@Blue.Sky"),
            password=over.pop("password", "longenough1"),
            new_account=AdminNewAccount(
                **over.pop("new_account", {"name": "Blue Sky Roofing"})),
            **over,
        )

    def test_new_org_mode_provisions_and_audits_like_the_account_endpoint(self):
        conn = _Conn(_happy_script())
        result = admin_create_user(body=self._body(), admin=ADMIN, db=conn)
        assert result["id"] == 55
        actions = [p[2] for sql, p in conn.executed if "admin_audit_log" in sql]
        assert actions == ["account.create", "user.create"]
        assert conn.commits == 1

    def test_blank_org_name_rejected(self):
        conn = _Conn([])
        with pytest.raises(HTTPException) as exc:
            admin_create_user(body=self._body(new_account={"name": "   "}),
                              admin=ADMIN, db=conn)
        assert exc.value.status_code == 400
        assert "Company or business name is required." in exc.value.detail
        assert conn.executed == []

    def test_org_name_length_rule_matches_the_account_endpoint(self):
        # Both admin funnels share company_problem — an over-long name must be
        # a 400 from each, exactly as self-serve signup rejects it.
        for call, body in (
            (admin_create_user, self._body(new_account={"name": "x" * 81})),
            (admin_create_account, _account_body(name="x" * 81)),
        ):
            conn = _Conn([])
            with pytest.raises(HTTPException) as exc:
                call(body=body, admin=ADMIN, db=conn)
            assert exc.value.status_code == 400
            assert "80 characters or fewer" in exc.value.detail
            assert conn.executed == []

    def test_over_length_password_rejected(self):
        # password_problem's 72-byte bcrypt cap applies to the admin path too.
        conn = _Conn([])
        with pytest.raises(HTTPException) as exc:
            admin_create_user(body=self._body(password="x" * 73), admin=ADMIN, db=conn)
        assert exc.value.status_code == 400
        assert "72 bytes" in exc.value.detail
