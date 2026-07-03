"""Tests for the scheduled workflow triggers (api/workflow_engine.py Phase 4):
date_offset and inactivity rules, the firings-ledger dedup, the whitelist on
date sources, and the send_notification action.

No live DB (repo convention): route/engine functions run against a scripted
fake connection that replays canned responses per execute() and records the
SQL + params for assertions.
"""
import json
from datetime import date, datetime

import pytest

from api import workflow_engine as we


# ── scripted fake DB ────────────────────────────────────────────────────────────

class _ScriptedCursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    @property
    def description(self):
        rows = self._current
        if rows and isinstance(rows[0], dict):
            return [(k,) for k in rows[0].keys()]
        return []

    def fetchall(self):
        rows = self._current
        if rows and isinstance(rows[0], dict):
            return [tuple(r.values()) for r in rows]
        return list(rows)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _ScriptedConn:
    """Each execute() consumes the next canned response (list of dicts for
    dict_fetchall-shaped queries, list of tuples otherwise, [] for writes)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _ScriptedCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _rule(**over):
    base = {
        "id": 1, "name": "Renewal outreach", "trigger_type": "date_offset",
        "trigger_config": {"source": "properties", "date_field": "last_sale_date", "offset_days": -30},
        "action_type": "create_task",
        "action_config": {"title": "Call about renewal", "due_days_offset": 1, "priority": "high"},
        "is_active": True, "vertical": None, "created_by": 9, "account_id": 3,
    }
    base.update(over)
    return base


# ── date_offset rules ───────────────────────────────────────────────────────────

class TestDateOffsetRules:
    def test_fires_action_when_claim_succeeds(self):
        anchor = date(2026, 8, 1)
        conn = _ScriptedConn([
            [_rule()],                                  # load rules
            [(42, 42, anchor)],                         # candidates (target, lead, anchor)
            [(100,)],                                   # claim INSERT returns a row
            [(5, "Call about renewal", date(2026, 7, 3), "high")],  # task INSERT
        ])
        results = we.execute_date_offset_rules(conn, 3)
        assert [r["action"] for r in results] == ["task_created"]

        candidate_sql, candidate_params = conn.executed[1]
        assert "last_sale_date" in candidate_sql
        assert "account_id = %s" in candidate_sql
        assert "archived_at IS NULL" in candidate_sql
        assert candidate_params == [3, -30]

        claim_sql, claim_params = conn.executed[2]
        assert "ON CONFLICT DO NOTHING" in claim_sql
        assert claim_params == [1, 3, "property", 42, anchor.isoformat()]

    def test_skips_when_already_fired(self):
        conn = _ScriptedConn([
            [_rule()],
            [(42, 42, date(2026, 8, 1))],
            [],                                          # claim conflict → no row
        ])
        assert we.execute_date_offset_rules(conn, 3) == []
        assert len(conn.executed) == 3                   # no action query ran

    def test_rejects_non_whitelisted_field(self):
        bad = _rule(trigger_config={"source": "properties",
                                    "date_field": "id; DROP TABLE properties", "offset_days": 0})
        conn = _ScriptedConn([[bad]])
        assert we.execute_date_offset_rules(conn, 3) == []
        assert len(conn.executed) == 1                   # only the rule load ran

    def test_rejects_unknown_source(self):
        bad = _rule(trigger_config={"source": "users", "date_field": "created_at", "offset_days": 0})
        conn = _ScriptedConn([[bad]])
        assert we.execute_date_offset_rules(conn, 3) == []
        assert len(conn.executed) == 1

    def test_trigger_config_as_json_string(self):
        rule = _rule(trigger_config=json.dumps(
            {"source": "properties", "date_field": "created_at", "offset_days": 7}))
        conn = _ScriptedConn([
            [rule],
            [(8, 8, date(2026, 6, 25))],
            [(101,)],
            [(6, "Call about renewal", date(2026, 7, 3), "high")],
        ])
        results = we.execute_date_offset_rules(conn, 3)
        assert results and results[0]["action"] == "task_created"

    def test_vertical_scoped_rule_skips_other_verticals(self):
        rule = _rule(vertical="solar")
        conn = _ScriptedConn([
            [rule],
            [(42, 42, date(2026, 8, 1))],
            [("roofing",)],                              # _get_lead_vertical
        ])
        assert we.execute_date_offset_rules(conn, 3) == []

    def test_action_failure_rolls_back_and_reports(self, monkeypatch):
        conn = _ScriptedConn([
            [_rule()],
            [(42, 42, date(2026, 8, 1))],
            [(100,)],                                    # claim ok
        ])
        monkeypatch.setattr(we, "_execute_action",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        results = we.execute_date_offset_rules(conn, 3)
        assert results[0]["action"] == "rule_failed"
        assert conn.rollbacks == 1                       # unclaims the firing for retry

    def test_policy_source_threads_context_to_send_template(self, monkeypatch):
        """A policies-source firing with a send_template action fetches the
        policy row and hands it to the action as merge-field context."""
        rule = _rule(
            trigger_config={"source": "policies", "date_field": "expiration_date", "offset_days": -30},
            action_type="send_template",
            action_config={"templates": {"sms": 5, "email": 7}, "delivery": "sms_first"},
        )
        policy_row = {"id": 77, "account_id": 3, "property_id": 42, "carrier": "Progressive",
                      "policy_type": "auto", "expiration_date": date(2026, 8, 1)}
        captured = {}

        def fake_execute_action(conn, r, lead_id, user_id, account_id, extra=None):
            captured.update(lead_id=lead_id, extra=extra)
            return {"action": "template_sent"}

        monkeypatch.setattr(we, "_execute_action", fake_execute_action)
        conn = _ScriptedConn([
            [rule],
            [(77, 42, date(2026, 8, 1))],                # candidate: policy 77 → lead 42
            [(100,)],                                    # claim ok
            [policy_row],                                # policy fetch for context
        ])
        results = we.execute_date_offset_rules(conn, 3)
        assert results == [{"action": "template_sent"}]
        assert captured["lead_id"] == 42
        assert captured["extra"] == {"policy": policy_row}
        fetch_sql, fetch_params = conn.executed[3]
        assert "FROM policies" in fetch_sql
        assert fetch_params == [77, 3]

    def test_policy_source_task_action_skips_context_fetch(self):
        """create_task doesn't render merge fields — no extra query for it."""
        rule = _rule(trigger_config={"source": "policies", "date_field": "expiration_date",
                                     "offset_days": -30})
        conn = _ScriptedConn([
            [rule],
            [(77, 42, date(2026, 8, 1))],
            [(100,)],                                    # claim ok
            [(6, "Call about renewal", date(2026, 7, 3), "high")],   # task insert directly
        ])
        results = we.execute_date_offset_rules(conn, 3)
        assert results and results[0]["action"] == "task_created"


# ── inactivity rules ────────────────────────────────────────────────────────────

class TestInactivityRules:
    def _rule(self, **over):
        return _rule(trigger_type="inactivity",
                     trigger_config={"days": 60}, **over)

    def test_fires_with_last_touch_fire_key(self):
        last_touch = datetime(2026, 4, 1, 12, 30)
        conn = _ScriptedConn([
            [self._rule()],
            [(42, last_touch)],                          # candidates
            [(100,)],                                    # claim
            [(5, "Call about renewal", date(2026, 7, 3), "high")],
        ])
        results = we.execute_inactivity_rules(conn, 3)
        assert results[0]["action"] == "task_created"
        _, claim_params = conn.executed[2]
        assert claim_params[-1] == "2026-04-01"

        sql, params = conn.executed[1]
        assert "contact_history" in sql
        assert "make_interval" in sql
        assert "is_terminal" in sql                      # default excludes closed stages
        assert params == [3, 3, 60]

    def test_never_touched_uses_never_key(self):
        conn = _ScriptedConn([
            [self._rule()],
            [(42, None)],
            [(100,)],
            [(5, "t", date(2026, 7, 3), "normal")],
        ])
        we.execute_inactivity_rules(conn, 3)
        _, claim_params = conn.executed[2]
        assert claim_params[-1] == "never"

    def test_explicit_statuses_replace_terminal_exclusion(self):
        rule = self._rule()
        rule["trigger_config"] = {"days": 30, "statuses": ["contacted", "qualified"]}
        conn = _ScriptedConn([[rule], []])
        we.execute_inactivity_rules(conn, 3)
        sql, params = conn.executed[1]
        assert "p.status = ANY(%s)" in sql
        assert "is_terminal" not in sql
        assert params == [3, ["contacted", "qualified"], 30]

    def test_invalid_days_skipped(self):
        rule = self._rule()
        rule["trigger_config"] = {"days": 0}
        conn = _ScriptedConn([[rule]])
        assert we.execute_inactivity_rules(conn, 3) == []
        assert len(conn.executed) == 1


# ── run_daily_rules orchestration ───────────────────────────────────────────────

class TestRunDailyRules:
    def test_per_account_isolation(self, monkeypatch):
        conn = _ScriptedConn([[(1,), (2,)]])             # distinct accounts

        def boom_for_account_1(c, account_id):
            if account_id == 1:
                raise RuntimeError("boom")
            return [{"action": "task_created"}]

        monkeypatch.setattr(we, "execute_date_offset_rules", boom_for_account_1)
        monkeypatch.setattr(we, "execute_inactivity_rules", lambda c, a: [])
        summary = we.run_daily_rules(conn)
        assert summary == {"accounts": 2, "actions": 1, "failures": 1}
        assert conn.rollbacks == 1 and conn.commits == 1


# ── send_notification action ────────────────────────────────────────────────────

class TestSendNotification:
    def _notify_rule(self):
        return _rule(action_type="send_notification",
                     action_config={"subject": "Lead going cold", "message": "Check in."})

    def test_skips_when_email_not_configured(self, monkeypatch):
        from api import notifications
        monkeypatch.setattr(notifications, "email_configured", lambda: False)
        conn = _ScriptedConn([[("owner@example.com",)]])  # users email lookup
        result = we._send_notification(conn, {"subject": "s"}, 42, self._notify_rule(), 3)
        assert result["action"] == "notification_skipped"

    def test_sends_and_logs_history(self, monkeypatch):
        from api import notifications
        sent = {}
        monkeypatch.setattr(notifications, "email_configured", lambda: True)
        monkeypatch.setattr(notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(
                                to=to_email, subject=subject, html=html))
        conn = _ScriptedConn([
            [("owner@example.com",)],                    # users email
            [("123 Main St",)],                          # lead label
            [(77,)],                                     # history INSERT RETURNING id
        ])
        result = we._send_notification(
            conn, {"subject": "Lead going cold", "message": "Check in."},
            42, self._notify_rule(), 3)
        assert result["action"] == "notification_sent"
        assert sent["to"] == "owner@example.com"
        assert "123 Main St" in sent["html"]
        history_sql, history_params = conn.executed[2]
        assert "contact_history" in history_sql
        assert history_params[0] == 42
        assert conn.commits == 1

    def test_non_email_channel_rejected(self):
        conn = _ScriptedConn([])
        assert we._send_notification(conn, {"channel": "sms"}, 42, self._notify_rule(), 3) is None

    def test_dispatched_from_execute_action(self, monkeypatch):
        called = {}
        monkeypatch.setattr(we, "_send_notification",
                            lambda conn, cfg, lead_id, rule, account_id: called.update(lead=lead_id) or {"action": "notification_sent"})
        rule = self._notify_rule()
        result = we._execute_action(_ScriptedConn([]), rule, 42, 9, 3)
        assert result == {"action": "notification_sent"}
        assert called["lead"] == 42


# ── route validation (api/routes/workflows.py) ──────────────────────────────────

class TestValidateRule:
    def _validate(self, *args):
        from api.routes.workflows import _validate_rule
        return _validate_rule(*args)

    def test_valid_date_offset_passes(self):
        self._validate("date_offset",
                       {"source": "properties", "date_field": "last_sale_date", "offset_days": -30},
                       "create_task", {})

    def test_valid_inactivity_passes(self):
        self._validate("inactivity", {"days": 60}, "send_notification", {})

    @pytest.mark.parametrize("trigger_type,trigger_config,action_type,action_config", [
        ("nonsense", {}, "create_task", {}),
        ("status_change", {}, "explode", {}),
        ("date_offset", {"source": "users", "date_field": "created_at"}, "create_task", {}),
        ("date_offset", {"source": "properties", "date_field": "evil"}, "create_task", {}),
        ("date_offset", {"source": "properties", "date_field": "last_sale_date",
                         "offset_days": "soon"}, "create_task", {}),
        ("inactivity", {"days": 0}, "create_task", {}),
        ("inactivity", {"days": "sixty"}, "create_task", {}),
        ("inactivity", {}, "create_task", {}),
        ("status_change", {}, "send_notification", {"channel": "sms"}),
    ])
    def test_invalid_configs_rejected(self, trigger_type, trigger_config, action_type, action_config):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._validate(trigger_type, trigger_config, action_type, action_config)
        assert exc.value.status_code == 400
