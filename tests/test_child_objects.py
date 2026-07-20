"""Tests for the Phase-5 associated objects (policies / orders / appointments):
route contracts (account scoping, status validation, activity logging, event
hooks) plus the engine's object-event matching and the new date-trigger
sources. Fake-conn style — no live DB."""
import json
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from api import workflow_engine as we
from api.models import (
    PolicyCreate, PolicyUpdate, OrderCreate, AppointmentCreate,
    POLICY_STATUSES, ORDER_STATUSES, APPOINTMENT_STATUSES,
)
from api.routes import policies as policies_route
from api.routes import orders as orders_route
from api.routes import appointments as appointments_route


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
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.commits = 0

    def cursor(self):
        return _ScriptedCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


USER = {"id": 9, "account_id": 3, "role": "rep"}


def _policy_row(**over):
    row = {
        "id": 5, "account_id": 3, "property_id": 42, "policy_number": "POL-1",
        "carrier": "Allstate", "policy_type": "auto", "premium": 1200.0,
        "billing_frequency": "annual", "effective_date": date(2026, 1, 1),
        "expiration_date": date(2027, 1, 1), "status": "quoted",
        "commission_rate": 12.0, "notes": None, "created_by": 9,
        "created_at": datetime(2026, 7, 1), "updated_at": datetime(2026, 7, 1),
    }
    row.update(over)
    return row


class TestPolicies:
    def test_create_scopes_account_and_logs_history(self, monkeypatch):
        fired = {}
        monkeypatch.setattr(policies_route, "_fire_policy_event",
                            lambda db, policy, event, user_id: fired.update(event=event))
        conn = _ScriptedConn([[_policy_row()], []])       # INSERT RETURNING, history INSERT
        body = PolicyCreate(property_id=42, carrier="Allstate", policy_type="auto",
                            premium=1200, expiration_date=date(2027, 1, 1))
        result = policies_route.create_policy(body, current_user=USER, db=conn)
        insert_sql, insert_params = conn.executed[0]
        assert "INSERT INTO policies" in insert_sql
        assert insert_params[-2:] == [9, 3]               # created_by, account_id
        history_sql, history_params = conn.executed[1]
        assert "contact_history" in history_sql
        assert history_params[0] == 42
        assert "Allstate auto" in history_params[1]
        assert fired["event"] == "created"
        assert result.status == "quoted"

    def test_create_rejects_bad_status(self):
        with pytest.raises(HTTPException) as exc:
            policies_route.create_policy(PolicyCreate(status="expired"), current_user=USER, db=_ScriptedConn([]))
        assert exc.value.status_code == 400

    def test_create_without_property_skips_history(self, monkeypatch):
        monkeypatch.setattr(policies_route, "_fire_policy_event", lambda *a, **k: None)
        conn = _ScriptedConn([[_policy_row(property_id=None)]])
        policies_route.create_policy(PolicyCreate(), current_user=USER, db=conn)
        assert len(conn.executed) == 1                    # no history insert

    def test_status_change_fires_event(self, monkeypatch):
        fired = {}
        monkeypatch.setattr(policies_route, "_fire_policy_event",
                            lambda db, policy, event, user_id: fired.update(event=event))
        conn = _ScriptedConn([
            [_policy_row(status="quoted")],               # _get_policy_or_404
            [_policy_row(status="active")],               # UPDATE RETURNING
            [],                                           # history INSERT
        ])
        policies_route.update_policy(5, PolicyUpdate(status="active"), user=USER, db=conn)
        update_sql, update_params = conn.executed[1]
        assert "UPDATE policies" in update_sql
        assert update_params[-2:] == [5, 3]               # id + account scope
        assert fired["event"] == "active"

    def test_update_same_status_fires_nothing(self, monkeypatch):
        fired = {}
        monkeypatch.setattr(policies_route, "_fire_policy_event",
                            lambda db, policy, event, user_id: fired.update(event=event))
        conn = _ScriptedConn([
            [_policy_row(status="active")],
            [_policy_row(status="active", premium=1500.0)],
        ])
        policies_route.update_policy(5, PolicyUpdate(status="active", premium=1500), user=USER, db=conn)
        assert fired == {}

    def test_list_rollups_and_scope(self):
        conn = _ScriptedConn([
            [(2,)],                                       # COUNT
            [(2400.0, 2, date(2026, 9, 1))],              # roll-ups
            [_policy_row()],                              # page rows
        ])
        result = policies_route.list_policies(
            status=None, property_id=42, page=1, page_size=25, user=USER, db=conn)
        assert result["premium_in_force"] == 2400.0
        assert result["active_count"] == 2
        assert result["next_expiration"] == "2026-09-01"
        count_sql, count_params = conn.executed[0]
        assert "account_id = %s" in count_sql
        assert count_params[0] == 3


class TestOrders:
    def test_create_parses_items_and_logs(self, monkeypatch):
        monkeypatch.setattr(orders_route, "_fire_order_event", lambda *a, **k: None)
        row = {
            "id": 7, "account_id": 3, "property_id": 42, "order_number": "SQ-100",
            "order_date": date(2026, 7, 2), "total": 55.0, "item_count": 2,
            "items": json.dumps([{"description": "Widget", "quantity": 2}]),
            "channel": "in_store", "status": "completed", "notes": None,
            "created_by": 9, "created_at": datetime(2026, 7, 2), "updated_at": datetime(2026, 7, 2),
        }
        conn = _ScriptedConn([[row], []])
        result = orders_route.create_order(
            OrderCreate(property_id=42, order_number="SQ-100", total=55,
                        items=[{"description": "Widget", "quantity": 2}]),
            current_user=USER, db=conn)
        assert result.items == [{"description": "Widget", "quantity": 2}]  # JSON string parsed
        history_sql, history_params = conn.executed[1]
        assert "contact_history" in history_sql
        assert "SQ-100" in history_params[1]

    def test_create_rejects_bad_status(self):
        with pytest.raises(HTTPException):
            orders_route.create_order(OrderCreate(status="shipped"), current_user=USER, db=_ScriptedConn([]))

    def test_status_constants(self):
        assert set(ORDER_STATUSES) == {"pending", "completed", "refunded", "cancelled"}
        assert set(POLICY_STATUSES) == {"quoted", "active", "lapsed", "cancelled"}
        assert set(APPOINTMENT_STATUSES) == {"scheduled", "completed", "cancelled", "no_show"}


class TestAppointments:
    def _body(self, **over):
        base = dict(property_id=42, title="Site visit",
                    starts_at=datetime(2026, 7, 10, 9), ends_at=datetime(2026, 7, 10, 10))
        base.update(over)
        return AppointmentCreate(**base)

    def test_create_validates_time_order(self):
        with pytest.raises(HTTPException) as exc:
            appointments_route.create_appointment(
                self._body(ends_at=datetime(2026, 7, 10, 8)), current_user=USER, db=_ScriptedConn([]))
        assert exc.value.status_code == 400

    def test_create_logs_history(self, monkeypatch):
        monkeypatch.setattr(appointments_route, "_fire_appointment_event", lambda *a, **k: None)
        row = {
            "id": 8, "account_id": 3, "property_id": 42, "assigned_to": None,
            "title": "Site visit", "location": None,
            "starts_at": datetime(2026, 7, 10, 9), "ends_at": datetime(2026, 7, 10, 10),
            "status": "scheduled", "notes": None, "created_by": 9,
            "created_at": datetime(2026, 7, 2), "updated_at": datetime(2026, 7, 2),
        }
        conn = _ScriptedConn([[row], []])
        appointments_route.create_appointment(self._body(), current_user=USER, db=conn)
        history_sql, history_params = conn.executed[1]
        assert "contact_history" in history_sql
        assert "Site visit" in history_params[1]


class TestObjectEventRules:
    def _rule(self, **over):
        base = {
            "id": 1, "name": "Renewal won", "trigger_type": "policy_event",
            "trigger_config": {"event": "active"}, "action_type": "create_task",
            "action_config": {"title": "Send welcome kit"}, "is_active": True,
            "vertical": None, "created_by": 9, "account_id": 3,
        }
        base.update(over)
        return base

    def test_matching_event_fires(self):
        conn = _ScriptedConn([
            [self._rule()],                               # rules
            [("auto",)],                                  # _get_lead_vertical
            [(5, "Send welcome kit", date(2026, 7, 5), "normal")],  # task INSERT
        ])
        results = we.execute_object_event_rules(conn, 3, 42, "policy", "active", 9)
        assert results[0]["action"] == "task_created"
        rules_sql, rules_params = conn.executed[0]
        assert rules_params == ["policy_event", 3]

    def test_non_matching_event_skips(self):
        conn = _ScriptedConn([[self._rule()], [("auto",)]])
        assert we.execute_object_event_rules(conn, 3, 42, "policy", "lapsed", 9) == []

    def test_no_lead_skips(self):
        conn = _ScriptedConn([[self._rule()]])
        assert we.execute_object_event_rules(conn, 3, None, "policy", "active", 9) == []

    def test_unknown_object_type_noop(self):
        conn = _ScriptedConn([])
        assert we.execute_object_event_rules(conn, 3, 42, "invoice", "paid", 9) == []
        assert conn.executed == []


class TestChildDateSources:
    def test_policies_source_registered(self):
        src = we.DATE_TRIGGER_SOURCES["policies"]
        assert src["target_type"] == "policy"
        assert "expiration_date" in src["fields"]

    def test_policies_sql_skips_unlinked_rows(self):
        sql = we._date_source_sql("policies", "expiration_date")
        assert "FROM policies" in sql
        assert "property_id IS NOT NULL" in sql
        assert "property_id AS lead_id" in sql

    def test_renewal_rule_fires_from_policy_source(self):
        rule = {
            "id": 1, "name": "Renewal 30d", "trigger_type": "date_offset",
            "trigger_config": {"source": "policies", "date_field": "expiration_date", "offset_days": -30},
            "action_type": "create_task", "action_config": {"title": "Renewal outreach"},
            "is_active": True, "vertical": None, "created_by": 9, "account_id": 3,
        }
        conn = _ScriptedConn([
            [rule],
            [(5, 42, date(2026, 8, 1))],                  # policy 5 on lead 42
            [(100,)],                                     # claim
            [(6, "Renewal outreach", date(2026, 7, 5), "normal")],
        ])
        results = we.execute_date_offset_rules(conn, 3)
        assert results[0]["action"] == "task_created"
        _, claim_params = conn.executed[2]
        assert claim_params == [1, 3, "policy", 5, "2026-08-01"]


class TestModuleCoverage:
    def test_every_business_type_covers_all_module_keys(self):
        from api.business_types import BUSINESS_TYPES
        from api.entitlements import MODULE_KEYS
        for key, bt in BUSINESS_TYPES.items():
            assert set(bt.default_modules) == set(MODULE_KEYS), key

    def test_new_modules_in_plan_catalog(self):
        from api.entitlements import PLAN_CATALOG, MODULE_KEYS
        assert {"policies", "orders", "appointments"} <= set(MODULE_KEYS)
        # pro grants everything except marketing (positioning plan Phase 4).
        assert PLAN_CATALOG["pro"] == set(MODULE_KEYS) - {"marketing"}
        assert "appointments" in PLAN_CATALOG["growth"]
