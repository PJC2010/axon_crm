"""Tests for the admin-audit and auth-event write helpers. Fake-conn style —
no live DB (see tests/test_provisioning.py for the pattern)."""
from api.admin_audit import record_admin_action
from api.auth_events import record_auth_event


class _Cursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self._conn.raise_on_execute:
            raise RuntimeError("boom")
        self._conn.executed.append((sql, list(params) if params is not None else None))


class _Conn:
    def __init__(self, raise_on_execute=False):
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.raise_on_execute = raise_on_execute

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


ADMIN = {"id": 7, "username": "pete"}


class TestRecordAdminAction:
    def test_single_insert_no_commit(self):
        # No commit: the caller runs it in the mutation's transaction and
        # commits both together, so the trail can't drift from the data.
        conn = _Conn()
        record_admin_action(conn, ADMIN, "user.update", "user", 42,
                            {"role": {"old": "owner", "new": "sales_rep"}})
        assert len(conn.executed) == 1
        sql, params = conn.executed[0]
        assert "INSERT INTO admin_audit_log" in sql
        assert params[0] == 7 and params[1] == "pete"
        assert params[2] == "user.update"
        assert params[3] == "user" and params[4] == "42"
        assert params[5].adapted == {"role": {"old": "owner", "new": "sales_rep"}}
        assert conn.commits == 0

    def test_actor_username_is_denormalized(self):
        # migration 0074: admin_user_id goes NULL when the admin is deleted, so
        # the row only keeps saying who did it because of this copy.
        conn = _Conn()
        record_admin_action(conn, ADMIN, "account.delete", "account", 3)
        _, params = conn.executed[0]
        assert params[1] == "pete"

    def test_defaults(self):
        conn = _Conn()
        record_admin_action(conn, {"id": 1, "username": "a"}, "user.set_password")
        _, params = conn.executed[0]
        assert params[3] is None and params[4] is None
        assert params[5].adapted == {}


class TestRecordAuthEvent:
    def test_success_inserts_stamps_last_login_and_commits(self):
        conn = _Conn()
        record_auth_event(conn, success=True, user_id=5, account_id=2,
                          identifier="pete", ip="1.2.3.4", user_agent="ua")
        assert len(conn.executed) == 2
        assert "INSERT INTO auth_events" in conn.executed[0][0]
        assert "last_login_at" in conn.executed[1][0]
        assert conn.executed[1][1] == [5]
        assert conn.commits == 1

    def test_failure_event_skips_last_login(self):
        conn = _Conn()
        record_auth_event(conn, success=False, identifier="ghost",
                          failure_reason="unknown_user", ip="1.2.3.4")
        assert len(conn.executed) == 1
        params = conn.executed[0][1]
        assert params[0] is None            # user_id
        assert params[2] == "ghost"         # attempted_identifier
        assert params[5] == "unknown_user"  # failure_reason
        assert conn.commits == 1

    def test_success_without_user_id_skips_last_login(self):
        conn = _Conn()
        record_auth_event(conn, success=True)
        assert len(conn.executed) == 1

    def test_user_agent_truncated(self):
        conn = _Conn()
        record_auth_event(conn, success=False, user_agent="x" * 2000)
        assert len(conn.executed[0][1][7]) == 512

    def test_insert_failure_rolls_back_and_never_raises(self):
        # A broken auth_events table must never break login.
        conn = _Conn(raise_on_execute=True)
        record_auth_event(conn, success=True, user_id=1)
        assert conn.rollbacks == 1
        assert conn.commits == 0
