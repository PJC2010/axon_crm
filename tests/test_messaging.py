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
        assert all(v == "" for v in ctx.values())
        assert set(messaging.MERGE_FIELDS) <= set(ctx)
        assert set(messaging.POLICY_MERGE_FIELDS) <= set(ctx)

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

    def test_review_link_merge_field(self):
        ctx = messaging.build_context({}, "Acme", review_link="https://g.page/r/acme")
        out = messaging.render_template("Review us: {{review_link}}", ctx)
        assert out == "Review us: https://g.page/r/acme"
        # Absent link renders empty (the send path skips such messages first).
        ctx = messaging.build_context({}, "Acme")
        assert messaging.render_template("{{review_link}}", ctx) == ""

    def test_references_field(self):
        assert messaging.references_field("Review: {{review_link}}", "review_link") is True
        assert messaging.references_field("Review: {{ review_link }}", "review_link") is True
        assert messaging.references_field("Hi {{first_name}}", "review_link") is False
        assert messaging.references_field(None, "review_link") is False
        assert messaging.references_field("no placeholders", "review_link") is False


class TestPolicyContext:
    _POLICY = {"id": 7, "policy_number": "PN-123", "carrier": "Progressive",
               "policy_type": "auto", "premium": 1250.5,
               "effective_date": "2025-07-15", "expiration_date": "2026-07-15"}

    def test_policy_fields_formatted(self):
        ctx = messaging.build_context({"contact_name": "Sam Lee"}, "Acme", policy=self._POLICY)
        assert ctx["carrier"] == "Progressive"
        assert ctx["policy_type"] == "auto"
        assert ctx["policy_number"] == "PN-123"
        assert ctx["premium"] == "$1,250.50"
        assert ctx["expiration_date"] == "July 15, 2026"
        assert ctx["effective_date"] == "July 15, 2025"

    def test_date_objects_also_format(self):
        from datetime import date
        ctx = messaging.build_context({}, None, policy={"expiration_date": date(2026, 1, 3)})
        assert ctx["expiration_date"] == "January 3, 2026"

    def test_policy_placeholders_render(self):
        ctx = messaging.build_context({"contact_name": "Sam Lee"}, "Acme", policy=self._POLICY)
        out = messaging.render_template(
            "Hi {{first_name}}, your {{carrier}} {{policy_type}} policy expires {{expiration_date}}.", ctx)
        assert out == "Hi Sam, your Progressive auto policy expires July 15, 2026."

    def test_without_policy_placeholders_render_empty(self):
        ctx = messaging.build_context({}, "Acme")
        out = messaging.render_template("Policy {{policy_number}} from {{carrier}}", ctx)
        assert out == "Policy  from "


class TestChannelOrder:
    def test_modes(self):
        assert messaging.channel_order("sms_first") == (["sms", "email"], False)
        assert messaging.channel_order("email_first") == (["email", "sms"], False)
        assert messaging.channel_order("both") == (["sms", "email"], True)


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
            [("Acme Insurance", None)],        # account name
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
        conn = _Conn([[self._record()], [self._template()], [("Acme", None)]])
        with pytest.raises(HTTPException) as exc:
            messaging_route.send_lead_message(42, SendMessageRequest(template_id=5), user=USER, db=conn)
        assert exc.value.status_code == 503

    def test_sms_sends_from_the_accounts_own_tracking_number(self, monkeypatch):
        """The account's number wins over the global TWILIO_FROM_NUMBER, so the
        text comes from the number the contact already sees on caller ID and
        replies thread back to this tenant."""
        sent = {}
        monkeypatch.setattr(messaging_route.notifications, "sms_configured",
                            lambda from_number=None: True)
        monkeypatch.setattr(messaging_route.notifications, "send_sms",
                            lambda **kw: sent.update(kw))
        conn = _Conn([
            [self._record()],                    # record
            [self._template(channel="sms", body="Hi {{first_name}}")],
            [("Acme", None)],                    # account name
            [("+18325550100",)],                 # account tracking number
            [(77,)],                             # history
        ])
        result = messaging_route.send_lead_message(
            42, SendMessageRequest(template_id=5), user=USER, db=conn)
        assert result == {"sent": True, "channel": "sms", "to": "+15551112222"}
        assert sent["from_number"] == "+18325550100"
        # The tracking-number lookup is account-scoped.
        sql, params = next((s, p) for s, p in conn.executed if "tracking_numbers" in s)
        assert params == [3]

    def test_sms_falls_back_to_the_global_number(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(messaging_route.notifications, "sms_configured",
                            lambda from_number=None: True)
        monkeypatch.setattr(messaging_route.notifications, "send_sms",
                            lambda **kw: sent.update(kw))
        conn = _Conn([
            [self._record()],
            [self._template(channel="sms", body="Hi")],
            [("Acme", None)],
            [],                                  # account has no tracking number
            [(77,)],
        ])
        messaging_route.send_lead_message(42, SendMessageRequest(template_id=5),
                                          user=USER, db=conn)
        assert sent["from_number"] is None      # resolved to TWILIO_FROM_NUMBER downstream

    def test_sms_diagnostics_hides_other_tenants_numbers(self, monkeypatch):
        monkeypatch.setattr(messaging_route.notifications, "verify_sms_sender",
                            lambda from_number=None: {
                                "sender": "+13466016971", "owned": False, "error": "nope",
                                "available_senders": [{"phone_number": "+18325550100"},
                                                      {"phone_number": "+17135550101"}],
                            })
        monkeypatch.setattr(messaging_route.notifications, "sms_configured",
                            lambda from_number=None: True)
        conn = _Conn([[]])                       # no tracking number for this account
        report = messaging_route.sms_diagnostics(current_user=USER, db=conn)
        assert report["owned"] is False
        assert report["owned_number_count"] == 2
        assert "available_senders" not in report

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
        conn = _Conn([[self._record()], [("Acme", None)], [(77,)]])
        result = messaging_route.send_lead_message(
            42, SendMessageRequest(channel="email", subject="Hi", body="Hello {{first_name}}"),
            user=USER, db=conn)
        assert result["sent"] is True

    def test_policy_id_merges_policy_fields(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(messaging_route.notifications, "email_configured", lambda: True)
        monkeypatch.setattr(messaging_route.notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(subject=subject, html=html))
        template = self._template(subject="{{carrier}} renewal {{expiration_date}}",
                                  body="Hi {{first_name}}, your {{policy_type}} policy expires {{expiration_date}}.")
        policy = {"id": 7, "account_id": 3, "property_id": 42, "policy_number": "PN-1",
                  "carrier": "Progressive", "policy_type": "auto", "premium": 900,
                  "effective_date": "2025-08-01", "expiration_date": "2026-08-01"}
        conn = _Conn([
            [self._record()],       # record
            [template],             # template
            [policy],               # policy (org- and lead-scoped)
            [("Acme", None)],            # account name
            [(77,)],                # history
        ])
        result = messaging_route.send_lead_message(
            42, SendMessageRequest(template_id=5, policy_id=7), user=USER, db=conn)
        assert result["sent"] is True
        assert sent["subject"] == "Progressive renewal August 1, 2026"
        assert "your auto policy expires August 1, 2026" in sent["html"]
        # The policy lookup is scoped to this account AND this lead.
        policy_sql, policy_params = conn.executed[2]
        assert "policies" in policy_sql
        assert policy_params == [7, 3, 42]
        # Timeline label names the policy.
        history_params = next(p for sql, p in conn.executed if "contact_history" in sql)
        assert "(Progressive auto)" in history_params[1]

    def test_policy_on_other_record_404(self, monkeypatch):
        monkeypatch.setattr(messaging_route.notifications, "email_configured", lambda: True)
        conn = _Conn([
            [self._record()],
            [self._template()],
            [],                     # policy lookup empty (wrong lead/org)
        ])
        with pytest.raises(HTTPException) as exc:
            messaging_route.send_lead_message(
                42, SendMessageRequest(template_id=5, policy_id=7), user=USER, db=conn)
        assert exc.value.status_code == 404


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
            [("Acme", None)],                 # account name
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

        def fake_send_template(conn, cfg, lead_id, rule, account_id, extra=None):
            called["hit"] = lead_id
            called["extra"] = extra
            return {"action": "template_sent"}

        monkeypatch.setattr(we, "_send_template", fake_send_template)
        result = we._execute_action(_Conn([]), self._rule(), 42, 9, 3, extra={"policy": {"id": 7}})
        assert result == {"action": "template_sent"}
        assert called["hit"] == 42
        assert called["extra"] == {"policy": {"id": 7}}


class TestSendTemplateMultiChannel:
    """The {"templates": {...}, "delivery": mode} shape: channel fallback and
    both-channel sends."""

    def _rule(self, **over):
        r = {"id": 1, "name": "Renewal reminder", "action_type": "send_template",
             "action_config": {}, "created_by": 9, "account_id": 3}
        r.update(over)
        return r

    def _sms_template(self):
        return {"id": 5, "account_id": 3, "name": "Reminder SMS", "channel": "sms",
                "subject": None, "body": "Hi {{first_name}}, {{carrier}} expires {{expiration_date}}."}

    def _email_template(self):
        return {"id": 7, "account_id": 3, "name": "Reminder Email", "channel": "email",
                "subject": "Renewal {{expiration_date}}", "body": "Hi {{first_name}}"}

    def _record(self, **over):
        r = {"id": 42, "contact_name": "Jane Doe", "contact_email": "jane@x.com",
             "contact_phone": "+15551112222", "address": "1 Main", "owner_name": "Jane Doe"}
        r.update(over)
        return r

    _CFG = {"templates": {"sms": 5, "email": 7}, "delivery": "sms_first"}

    def _configure(self, monkeypatch, email=True, sms=True):
        from api import notifications
        monkeypatch.setattr(notifications, "email_configured", lambda: email)
        monkeypatch.setattr(notifications, "sms_configured", lambda from_number=None: sms)

    def test_sms_first_sends_sms_only(self, monkeypatch):
        self._configure(monkeypatch)
        sent = {}
        from api import notifications
        monkeypatch.setattr(notifications, "send_sms", lambda *, to_phone, body, from_number=None: sent.update(sms=(to_phone, body)))
        monkeypatch.setattr(notifications, "send_email", lambda **kw: sent.update(email=kw))
        conn = _Conn([
            [self._sms_template()], [self._email_template()],   # template loads
            [],                                                  # no tracking number
            [self._record()],                                    # record
            [("Acme", None)],                                         # account name
            [(88,)],                                             # history (sms)
        ])
        result = we._send_template(conn, self._CFG, 42, self._rule(), 3)
        assert result["action"] == "template_sent"
        assert [s["channel"] for s in result["sent"]] == ["sms"]
        assert "email" not in sent
        assert sent["sms"][0] == "+15551112222"

    def test_sms_first_falls_back_to_email_without_phone(self, monkeypatch):
        self._configure(monkeypatch)
        sent = {}
        from api import notifications
        monkeypatch.setattr(notifications, "send_sms", lambda **kw: sent.update(sms=kw))
        monkeypatch.setattr(notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(email=(to_email, subject)))
        conn = _Conn([
            [self._sms_template()], [self._email_template()],
            [],                                                  # no tracking number
            [self._record(contact_phone=None)],
            [("Acme", None)],
            [(88,)],
        ])
        result = we._send_template(conn, self._CFG, 42, self._rule(), 3)
        assert [s["channel"] for s in result["sent"]] == ["email"]
        assert result["skipped"]["sms"] == "no_address"
        assert sent["email"][0] == "jane@x.com"

    def test_sms_first_falls_back_when_sms_unconfigured(self, monkeypatch):
        self._configure(monkeypatch, sms=False)
        sent = {}
        from api import notifications
        monkeypatch.setattr(notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(email=to_email))
        conn = _Conn([
            [self._sms_template()], [self._email_template()],
            [],                                                  # no tracking number
            [self._record()],
            [("Acme", None)],
            [(88,)],
        ])
        result = we._send_template(conn, self._CFG, 42, self._rule(), 3)
        assert [s["channel"] for s in result["sent"]] == ["email"]
        assert result["skipped"]["sms"] == "not_configured"

    def test_both_sends_on_every_channel(self, monkeypatch):
        self._configure(monkeypatch)
        sent = {}
        from api import notifications
        monkeypatch.setattr(notifications, "send_sms", lambda *, to_phone, body, from_number=None: sent.update(sms=to_phone))
        monkeypatch.setattr(notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(email=to_email))
        cfg = {"templates": {"sms": 5, "email": 7}, "delivery": "both"}
        conn = _Conn([
            [self._sms_template()], [self._email_template()],
            [],                                                  # no tracking number
            [self._record()],
            [("Acme", None)],
            [(88,)], [(89,)],                                    # two history inserts
        ])
        result = we._send_template(conn, cfg, 42, self._rule(), 3)
        assert sorted(s["channel"] for s in result["sent"]) == ["email", "sms"]
        assert sent == {"sms": "+15551112222", "email": "jane@x.com"}
        history = [p for sql, p in conn.executed if "contact_history" in sql]
        assert len(history) == 2

    def test_neither_channel_reachable_skips(self, monkeypatch):
        self._configure(monkeypatch)
        conn = _Conn([
            [self._sms_template()], [self._email_template()],
            [],                                                  # no tracking number
            [self._record(contact_phone=None, contact_email=None)],
        ])
        result = we._send_template(conn, self._CFG, 42, self._rule(), 3)
        assert result["action"] == "template_skipped"
        assert result["skipped"] == {"sms": "no_address", "email": "no_address"}

    def test_provider_error_falls_through_to_next_channel(self, monkeypatch):
        self._configure(monkeypatch)
        sent = {}
        from api import notifications

        def boom(**kw):
            raise RuntimeError("twilio down")

        monkeypatch.setattr(notifications, "send_sms", boom)
        monkeypatch.setattr(notifications, "send_email",
                            lambda *, to_email, subject, html: sent.update(email=to_email))
        conn = _Conn([
            [self._sms_template()], [self._email_template()],
            [],                                                  # no tracking number
            [self._record()],
            [("Acme", None)],
            [(88,)],
        ])
        result = we._send_template(conn, self._CFG, 42, self._rule(), 3)
        assert [s["channel"] for s in result["sent"]] == ["email"]
        assert "send_failed" in result["skipped"]["sms"]

    def test_all_channels_error_reraises(self, monkeypatch):
        self._configure(monkeypatch)
        from api import notifications

        def boom(**kw):
            raise RuntimeError("provider down")

        monkeypatch.setattr(notifications, "send_sms", boom)
        monkeypatch.setattr(notifications, "send_email", boom)
        conn = _Conn([
            [self._sms_template()], [self._email_template()],
            [],                                                  # no tracking number
            [self._record()],
            [("Acme", None)],
        ])
        with pytest.raises(RuntimeError):
            we._send_template(conn, self._CFG, 42, self._rule(), 3)

    def test_policy_context_renders_into_body(self, monkeypatch):
        self._configure(monkeypatch)
        sent = {}
        from api import notifications
        monkeypatch.setattr(notifications, "send_sms", lambda *, to_phone, body, from_number=None: sent.update(body=body))
        conn = _Conn([
            [self._sms_template()], [self._email_template()],
            [],                                                  # no tracking number
            [self._record()],
            [("Acme", None)],
            [(88,)],
        ])
        policy = {"id": 7, "carrier": "Progressive", "policy_type": "auto",
                  "policy_number": "PN-1", "premium": 900,
                  "effective_date": "2025-08-01", "expiration_date": "2026-08-01"}
        result = we._send_template(conn, self._CFG, 42, self._rule(), 3,
                                   extra={"policy": policy})
        assert result["action"] == "template_sent"
        assert sent["body"] == "Hi Jane, Progressive expires August 1, 2026."
        history_params = next(p for sql, p in conn.executed if "contact_history" in sql)
        assert "Progressive expires August 1, 2026" in history_params[5]


class TestValidation:
    def test_send_template_requires_template_id(self):
        from api.routes.workflows import _validate_rule
        with pytest.raises(HTTPException) as exc:
            _validate_rule("status_change", {"to_status": "won"}, "send_template", {})
        assert exc.value.status_code == 400

    def test_send_template_valid(self):
        from api.routes.workflows import _validate_rule
        _validate_rule("status_change", {"to_status": "won"}, "send_template", {"template_id": 5})

    def test_send_template_multi_channel_valid(self):
        from api.routes.workflows import _validate_rule
        _validate_rule("status_change", {"to_status": "won"}, "send_template",
                       {"templates": {"sms": 5, "email": 7}, "delivery": "sms_first"})
        _validate_rule("status_change", {"to_status": "won"}, "send_template",
                       {"templates": {"sms": 5}, "delivery": "both"})

    def test_send_template_bad_delivery_rejected(self):
        from api.routes.workflows import _validate_rule
        with pytest.raises(HTTPException) as exc:
            _validate_rule("status_change", {"to_status": "won"}, "send_template",
                           {"templates": {"sms": 5, "email": 7}, "delivery": "carrier_pigeon"})
        assert exc.value.status_code == 400

    def test_fallback_needs_both_templates(self):
        from api.routes.workflows import _validate_rule
        with pytest.raises(HTTPException) as exc:
            _validate_rule("status_change", {"to_status": "won"}, "send_template",
                           {"templates": {"sms": 5}, "delivery": "sms_first"})
        assert exc.value.status_code == 400

    def test_bad_channel_key_rejected(self):
        from api.routes.workflows import _validate_rule
        with pytest.raises(HTTPException) as exc:
            _validate_rule("status_change", {"to_status": "won"}, "send_template",
                           {"templates": {"fax": 5}, "delivery": "both"})
        assert exc.value.status_code == 400
