"""Tests for contact-level messaging (Phase 7): the pure merge-field renderer,
the per-record send route, and the send_template workflow action. Fake-conn
style — no live DB, network monkeypatched."""
import pytest
from fastapi import HTTPException

from api import messaging
from api import workflow_engine as we
from api.models import SendMessageRequest
from api.routes import messaging as messaging_route


# ── Pure renderer ─────────────────────────────────────────────────────────────

class TestRenderer:
    def test_builds_context_with_first_name(self):
        ctx = messaging.build_context(
            {"contact_name": "Jane Doe", "address": "1 Main St", "owner_name": "Jane Doe"},
            "Acme Insurance",
        )
        assert ctx["first_name"] == "Jane"
        assert ctx["contact_name"] == "Jane Doe"
        assert ctx["business_name"] == "Acme Insurance"

    def test_missing_values_render_empty(self):
        ctx = messaging.build_context({}, None)
        assert ctx == {"contact_name": "", "first_name": "", "address": "",
                       "owner_name": "", "business_name": ""}

    def test_known_placeholders_substituted(self):
        ctx = messaging.build_context({"contact_name": "Sam Lee"}, "Acme")
        out = messaging.render_template("Hi {{first_name}}, thanks from {{business_name}}!", ctx)
        assert out == "Hi Sam, thanks from Acme!"

    def test_unknown_placeholder_left_intact(self):
        out = messaging.render_template("Order {{order_id}} ready", messaging.build_context({}, "Acme"))
        assert out == "Order {{order_id}} ready"

    def test_whitespace_in_braces_ok(self):
        out = messaging.render_template("Hi {{ first_name }}", messaging.build_context({"contact_name": "Sam Lee"}, None))
        assert out == "Hi Sam"

    def test_recipient_for_channel(self):
        rec = {"contact_email": "a@b.com", "contact_phone": "+15551234567"}
        assert messaging.recipient_for_channel(rec, "email") == "a@b.com"
        assert messaging.recipient_for_channel(rec, "sms") == "+15551234567"
        assert messaging.recipient_for_channel({}, "email") is None


# ── fake DB ─────────────────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    @property
    def description(self):
        rows = self._current
        return [(k,) for k in rows[0].keys()] if rows and isinstance(rows[0], dict) else []

    def fetchall(self):
        rows = self._current
        return [tuple(r.values()) for r in rows] if rows and isinstance(rows[0], dict) else list(rows)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _Conn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.commits = 0
    def cursor(self): return _Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): pass


USER = {"id": 9, "account_id": 3, "role": "owner"}


# ── Send route ────────────────────────────────────────────────────────────────

class TestSendLeadMessage:
    def _record(self, **over):
        r = {"id": 42, "contact_name": "Jane Doe", "contact_email": "jane@x.com",
             "contact_phone": "+15551112222", "address": "1 Main St", "owner_name": "Jane Doe"}
        r.update(over)
        return r

    def _template(self, **over):
        t = {"id": 5, "account_id": 3, "name": "Renewal notice", "channel": "email",
             "subject": "Hi {{first_name}}", "body": "Your renewal is due, {{first_name}}.",
             "created_by": 9}
        t.update(over)
        return t

    def test_sends_template_email_and_logs(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(messaging_route.notifications, "email_configured", lambda: True)
        monkeypatch.setattr(messaging_route.notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(to=to_email, subject=subject, html=html))
        conn = _Conn([
            [self._record()],             # record lookup
            [self._template()],           # template lookup
            [("Acme Insurance",)],        # account name
            [(77,)],                      # history insert
        ])
        result = messaging_route.send_lead_message(42, SendMessageRequest(template_id=5), user=USER, db=conn)
        assert result == {"sent": True, "channel": "email", "to": "jane@x.com"}
        assert sent["subject"] == "Hi Jane"
        assert "Your renewal is due, Jane." in sent["html"]
        assert any("contact_history" in sql for sql, _ in conn.executed)

    def test_missing_contact_address_400(self, monkeypatch):
        monkeypatch.setattr(messaging_route.notifications, "email_configured", lambda: True)
        conn = _Conn([[self._record(contact_email=None)], [self._template()]])
        with pytest.raises(HTTPException) as exc:
            messaging_route.send_lead_message(42, SendMessageRequest(template_id=5), user=USER, db=conn)
        assert exc.value.status_code == 400

    def test_unconfigured_channel_503(self, monkeypatch):
        monkeypatch.setattr(messaging_route.notifications, "email_configured", lambda: False)
        conn = _Conn([[self._record()], [self._template()], [("Acme",)]])
        with pytest.raises(HTTPException) as exc:
            messaging_route.send_lead_message(42, SendMessageRequest(template_id=5), user=USER, db=conn)
        assert exc.value.status_code == 503

    def test_lead_not_found_404(self):
        conn = _Conn([[]])
        with pytest.raises(HTTPException) as exc:
            messaging_route.send_lead_message(42, SendMessageRequest(body="hi"), user=USER, db=conn)
        assert exc.value.status_code == 404

    def test_adhoc_body_without_template(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(messaging_route.notifications, "email_configured", lambda: True)
        monkeypatch.setattr(messaging_route.notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(to=to_email))
        conn = _Conn([[self._record()], [("Acme",)], [(77,)]])
        result = messaging_route.send_lead_message(
            42, SendMessageRequest(channel="email", subject="Hi", body="Hello {{first_name}}"),
            user=USER, db=conn)
        assert result["sent"] is True


# ── send_template workflow action ───────────────────────────────────────────────

class TestSendTemplateAction:
    def _rule(self, **over):
        r = {"id": 1, "name": "Welcome kit", "action_type": "send_template",
             "action_config": {"template_id": 5}, "created_by": 9, "account_id": 3}
        r.update(over)
        return r

    def test_sends_to_record_contact(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(we, "dict_fetchone", we.dict_fetchone)  # keep real
        from api import notifications
        monkeypatch.setattr(notifications, "email_configured", lambda: True)
        monkeypatch.setattr(notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(to=to_email, subject=subject))
        conn = _Conn([
            [{"id": 5, "account_id": 3, "name": "Welcome", "channel": "email",
              "subject": "Welcome {{first_name}}", "body": "Hi {{first_name}}"}],   # template
            [{"id": 42, "contact_name": "Jane Doe", "contact_email": "jane@x.com",
              "contact_phone": None, "address": "1 Main", "owner_name": "Jane Doe"}],  # record
            [("Acme",)],                 # account name
            [(88,)],                     # history
        ])
        result = we._send_template(conn, {"template_id": 5}, 42, self._rule(), 3)
        assert result["action"] == "template_sent"
        assert sent == {"to": "jane@x.com", "subject": "Welcome Jane"}

    def test_missing_template_skips(self):
        conn = _Conn([[]])               # template lookup empty
        result = we._send_template(conn, {"template_id": 5}, 42, self._rule(), 3)
        assert result["reason"] == "template_not_found"

    def test_unconfigured_channel_skips(self, monkeypatch):
        from api import notifications
        monkeypatch.setattr(notifications, "email_configured", lambda: False)
        conn = _Conn([[{"id": 5, "account_id": 3, "name": "W", "channel": "email",
                        "subject": "s", "body": "b"}]])
        result = we._send_template(conn, {"template_id": 5}, 42, self._rule(), 3)
        assert result["reason"] == "email_not_configured"

    def test_no_contact_address_skips(self, monkeypatch):
        from api import notifications
        monkeypatch.setattr(notifications, "email_configured", lambda: True)
        conn = _Conn([
            [{"id": 5, "account_id": 3, "name": "W", "channel": "email", "subject": "s", "body": "b"}],
            [{"id": 42, "contact_name": "X", "contact_email": None, "contact_phone": None,
              "address": "1 Main", "owner_name": "X"}],
        ])
        result = we._send_template(conn, {"template_id": 5}, 42, self._rule(), 3)
        assert result["reason"] == "no_email_address"

    def test_dispatched_from_execute_action(self, monkeypatch):
        called = {}

        def fake_send_template(conn, cfg, lead_id, rule, account_id):
            called["hit"] = lead_id
            return {"action": "template_sent"}

        monkeypatch.setattr(we, "_send_template", fake_send_template)
        result = we._execute_action(_Conn([]), self._rule(), 42, 9, 3)
        assert result == {"action": "template_sent"}
        assert called["hit"] == 42


class TestValidation:
    def test_send_template_requires_template_id(self):
        from api.routes.workflows import _validate_rule
        with pytest.raises(HTTPException) as exc:
            _validate_rule("status_change", {"to_status": "won"}, "send_template", {})
        assert exc.value.status_code == 400

    def test_send_template_valid(self):
        from api.routes.workflows import _validate_rule
        _validate_rule("status_change", {"to_status": "won"}, "send_template", {"template_id": 5})
