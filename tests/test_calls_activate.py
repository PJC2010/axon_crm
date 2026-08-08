"""Tests for one-click call-tracking activation and the missed-call auto-text
(api/routes/calls.py).

The promise being tested is the whole setup flow in one request: the owner
types the phone their business line rings on, and comes back with a tracking
number in that line's area code, forwarding to it, with auto-texting armed.
Fake conn (SQL matched by prefix) + a fake Twilio client — no DB, no network.
"""
import pytest
from fastapi import HTTPException

from api import call_setup_logic as csl
from api.routes import calls as calls_route


OWNER = {"id": 9, "account_id": 3, "role": "owner"}
REP = {"id": 11, "account_id": 3, "role": "rep"}

NUMBER_COLS = ("id", "phone_number", "friendly_name", "forward_to", "created_at")
NUMBER_ROW = (1, "+17135550100", "(713) 555-0100", "(713) 555-0142", "2026-08-08")

AUTO_REPLY_COLS = ("rule_id", "is_active", "template_id", "body")


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self._cols = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def description(self):
        return [(c,) for c in self._cols]

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        c = self.conn
        c.executed.append((sql, list(params) if params is not None else None))
        self._rows, self._cols = [], ()

        if sql.startswith("SELECT id, phone_number, friendly_name, forward_to, created_at FROM tracking_numbers"):
            self._cols = NUMBER_COLS
            self._rows = [NUMBER_ROW] if c.number else []
        elif sql.startswith("SELECT r.id AS rule_id"):
            self._cols = AUTO_REPLY_COLS
            self._rows = [c.auto_reply] if c.auto_reply else []
        elif sql.startswith("SELECT name FROM accounts"):
            self._rows = [(c.business_name,)]
        elif sql.startswith("INSERT INTO message_templates"):
            self._rows = [(77,)]
        elif sql.startswith("SELECT id FROM workflow_rules"):
            self._rows = [(55,)] if c.auto_reply else []
        elif sql.startswith(("INSERT INTO workflow_rules", "UPDATE workflow_rules SET is_active = TRUE")):
            # Enabling flips the state the subsequent read-back sees.
            c.auto_reply = (55, True, 77, c.business_body)
            self._rows = [(55,)]
        elif sql.startswith("UPDATE workflow_rules SET is_active = FALSE"):
            if c.auto_reply:
                c.auto_reply = (c.auto_reply[0], False, c.auto_reply[2], c.auto_reply[3])
        elif sql.startswith("INSERT INTO tracking_numbers"):
            if c.insert_fails:
                raise RuntimeError("duplicate key")
            c.number = True
            self._rows = [(1,)]
        elif sql.startswith("UPDATE tracking_numbers SET forward_to"):
            self._rows = [(1,)] if c.number else []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, *, number=False, auto_reply=None, insert_fails=False,
                 business_name="Kirby Roofing"):
        self.number = number
        self.auto_reply = auto_reply
        self.insert_fails = insert_fails
        self.business_name = business_name
        self.business_body = "Sorry we missed your call!"
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def sql_starting(self, prefix):
        return [(s, p) for s, p in self.executed if s.startswith(prefix)]


class FakeNumber:
    def __init__(self, phone_number):
        self.phone_number = phone_number
        self.friendly_name = phone_number
        self.sid = f"PN{phone_number[-4:]}"


class FakeAvailable:
    """Stands in for client.available_phone_numbers("US").local."""

    def __init__(self, client):
        self.client = client

    @property
    def local(self):
        return self

    def list(self, area_code=None, **kwargs):
        self.client.searches.append((area_code, kwargs))
        if area_code in self.client.search_raises:
            raise RuntimeError("Twilio search is down")
        return [FakeNumber(n) for n in self.client.inventory.get(area_code, [])]


class FakeTwilio:
    """inventory maps area code (int) or None -> list of E.164 numbers."""

    def __init__(self, inventory=None, unbuyable=(), search_raises=()):
        self.inventory = inventory if inventory is not None else {713: ["+17135550100"]}
        self.unbuyable = set(unbuyable)
        self.search_raises = set(search_raises)
        self.searches = []
        self.bought = []
        self.released = []

    def available_phone_numbers(self, country):
        assert country == "US"
        return FakeAvailable(self)

    @property
    def incoming_phone_numbers(self):
        client = self

        class _Numbers:
            def create(self, phone_number, **kwargs):
                client.bought.append((phone_number, kwargs))
                if phone_number in client.unbuyable:
                    raise RuntimeError(f"{phone_number} is no longer available")
                return FakeNumber(phone_number)

            def __call__(self, sid):
                class _One:
                    def delete(_self):
                        client.released.append(sid)
                return _One()

        return _Numbers()


@pytest.fixture
def twilio(monkeypatch):
    client = FakeTwilio()
    monkeypatch.setattr(calls_route, "_twilio_client", lambda: client)
    return client


def _activate(conn, twilio=None, **over):
    payload = calls_route.CallActivation(**{"forward_to": "(713) 555-0142", **over})
    request = type("Req", (), {})()   # only reaches _api_base_url, which is stubbed
    return calls_route.activate_call_tracking(payload, request, current_user=OWNER, db=conn)


@pytest.fixture(autouse=True)
def _stub_base_url(monkeypatch):
    monkeypatch.setattr(calls_route, "_api_base_url", lambda request: "https://api.test")


# ── Activation: the happy path ────────────────────────────────────────────────

class TestActivate:
    def test_buys_in_the_business_lines_own_area_code(self, twilio):
        conn = FakeConn()
        result = _activate(conn, twilio)

        assert result["ok"] is True
        assert twilio.searches[0][0] == 713          # derived from forward_to
        assert twilio.bought[0][0] == "+17135550100"
        assert result["number"]["phone_number"] == "+17135550100"

    def test_wires_both_webhooks_at_purchase(self, twilio):
        # A number bought without these rings nowhere and can't receive texts —
        # the app configures them precisely so no console step is needed.
        _activate(FakeConn(), twilio)
        _, kwargs = twilio.bought[0]
        assert kwargs["voice_url"] == "https://api.test/api/public/twilio/voice"
        assert kwargs["sms_url"] == "https://api.test/api/public/twilio/sms"
        assert kwargs["voice_method"] == kwargs["sms_method"] == "POST"

    def test_only_shops_numbers_that_can_both_ring_and_text(self, twilio):
        # A voice-only number would buy a tracking line that can't do two-way SMS.
        _activate(FakeConn(), twilio)
        _, kwargs = twilio.searches[0]
        assert kwargs["voice_enabled"] is True
        assert kwargs["sms_enabled"] is True

    def test_records_the_forwarding_destination(self, twilio):
        conn = FakeConn()
        _activate(conn, twilio, forward_to="7135550142")
        (_, params), = conn.sql_starting("INSERT INTO tracking_numbers")
        assert params[0] == 3                        # account_id
        assert params[2] == "7135550100"             # phone_digits (last 10)
        assert params[4] == "7135550142"             # forward_to

    def test_explicit_area_code_wins(self, twilio):
        twilio.inventory = {832: ["+18325550100"], 713: ["+17135550100"]}
        _activate(FakeConn(), twilio, area_code="832")
        assert twilio.searches[0][0] == 832
        assert twilio.bought[0][0] == "+18325550100"

    def test_rejects_a_phone_that_isnt_one(self, twilio):
        with pytest.raises(HTTPException) as exc:
            _activate(FakeConn(), twilio, forward_to="555-0142")
        assert exc.value.status_code == 400
        assert not twilio.bought

    def test_refuses_a_second_number_for_the_same_account(self, twilio):
        with pytest.raises(HTTPException) as exc:
            _activate(FakeConn(number=True), twilio)
        assert exc.value.status_code == 409
        assert not twilio.bought                     # and spends no money finding out


# ── Activation: live-inventory fallbacks ──────────────────────────────────────

class TestActivateFallbacks:
    def test_falls_back_to_any_area_code_when_the_local_one_is_empty(self, twilio):
        twilio.inventory = {713: [], None: ["+19045550100"]}
        result = _activate(FakeConn(), twilio)
        assert [s[0] for s in twilio.searches] == [713, None]
        assert result["number"] is not None

    def test_walks_past_a_number_someone_else_just_bought(self, twilio):
        # Inventory is live: a search hit can be sold a second later.
        twilio.inventory = {713: ["+17135550100", "+17135550101"]}
        twilio.unbuyable = {"+17135550100"}
        _activate(FakeConn(), twilio)
        assert [n for n, _ in twilio.bought] == ["+17135550100", "+17135550101"]

    def test_a_failing_search_tries_the_next_area_code(self, twilio):
        twilio.search_raises = {713}
        twilio.inventory = {None: ["+19045550100"]}
        result = _activate(FakeConn(), twilio)
        assert result["number"] is not None

    def test_502_naming_what_was_tried_when_nothing_is_available(self, twilio):
        twilio.inventory = {}
        with pytest.raises(HTTPException) as exc:
            _activate(FakeConn(), twilio)
        assert exc.value.status_code == 502
        assert "713" in exc.value.detail and "any" in exc.value.detail

    def test_a_number_that_cannot_be_recorded_is_released_not_stranded(self, twilio):
        # Real money was spent; an unrecorded number bills monthly and rings
        # nowhere, because the webhook resolves tenants through the DB row.
        conn = FakeConn(insert_fails=True)
        with pytest.raises(HTTPException) as exc:
            _activate(conn, twilio)
        assert exc.value.status_code == 500
        assert twilio.released == ["PN0100"]
        assert conn.rollbacks == 1


# ── Activation: the missed-call auto-text ─────────────────────────────────────

class TestActivateAutoReply:
    def test_on_by_default(self, twilio):
        conn = FakeConn()
        result = _activate(conn, twilio)
        assert result["auto_reply"]["enabled"] is True

        (_, tpl_params), = conn.sql_starting("INSERT INTO message_templates")
        assert tpl_params[1] == csl.AUTO_REPLY_TEMPLATE_NAME
        assert "{{business_name}}" in tpl_params[2]   # the seeded default body

        (rule_sql, rule_params), = conn.sql_starting("INSERT INTO workflow_rules")
        assert "'call_event'" in rule_sql and "'send_template'" in rule_sql
        assert rule_params[1] == csl.AUTO_REPLY_RULE_NAME
        assert rule_params[2].adapted == {"event": "missed"}
        assert rule_params[3].adapted == {"template_id": 77}

    def test_can_be_declined(self, twilio):
        conn = FakeConn()
        result = _activate(conn, twilio, auto_reply=False)
        assert result["auto_reply"]["enabled"] is False
        assert not conn.sql_starting("INSERT INTO message_templates")

    def test_custom_wording_is_used_verbatim(self, twilio):
        conn = FakeConn()
        _activate(conn, twilio, auto_reply_body="  On a roof — texting back shortly.  ")
        (_, params), = conn.sql_starting("INSERT INTO message_templates")
        assert params[2] == "On a roof — texting back shortly."

    def test_blank_custom_wording_is_a_400_before_any_purchase(self, twilio):
        with pytest.raises(HTTPException) as exc:
            _activate(FakeConn(), twilio, auto_reply_body="   ")
        assert exc.value.status_code == 400
        assert not twilio.bought

    def test_auto_reply_failure_does_not_undo_a_live_number(self, twilio, monkeypatch):
        # The number is bought, wired and forwarding by this point. A failed
        # auto-text is something the owner can switch on later; it must not
        # read as "activation failed" and leave them paying for a lost number.
        def boom(*a, **k):
            raise RuntimeError("workflow_rules is unhappy")
        monkeypatch.setattr(calls_route, "_enable_auto_reply", boom)
        result = _activate(FakeConn(), twilio)
        assert result["ok"] is True
        assert result["number"] is not None
        assert result["auto_reply"]["enabled"] is False


# ── Settings: reading and changing the auto-text ──────────────────────────────

class TestSettings:
    def test_get_reports_number_and_auto_reply(self, monkeypatch):
        monkeypatch.setattr(calls_route, "voice_configured", lambda: True)
        conn = FakeConn(number=True, auto_reply=(55, True, 77, "Sorry we missed you"))
        result = calls_route.get_call_settings(current_user=OWNER, db=conn)
        assert result["configured"] is True
        assert result["number"]["phone_number"] == "+17135550100"
        assert result["auto_reply"] == {
            "enabled": True, "rule_id": 55, "template_id": 77, "body": "Sorry we missed you",
        }

    def test_get_reports_auto_reply_off_when_never_set_up(self, monkeypatch):
        monkeypatch.setattr(calls_route, "voice_configured", lambda: True)
        result = calls_route.get_call_settings(current_user=OWNER, db=FakeConn(number=True))
        assert result["auto_reply"]["enabled"] is False

    def _patch(self, conn, user=OWNER, **fields):
        return calls_route.update_call_settings(
            calls_route.CallSettingsUpdate(**fields), current_user=user, db=conn)

    def test_forwarding_alone_still_works(self, monkeypatch):
        conn = FakeConn(number=True)
        result = self._patch(conn, forward_to="(832) 555-0199")
        (_, params), = conn.sql_starting("UPDATE tracking_numbers SET forward_to")
        assert params[0] == "(832) 555-0199"
        assert result["ok"] is True

    def test_forwarding_without_a_number_is_a_404(self):
        with pytest.raises(HTTPException) as exc:
            self._patch(FakeConn(number=False), forward_to="(832) 555-0199")
        assert exc.value.status_code == 404

    def test_empty_patch_is_rejected_rather_than_silently_doing_nothing(self):
        with pytest.raises(HTTPException) as exc:
            self._patch(FakeConn(number=True))
        assert exc.value.status_code == 400

    def test_turning_the_auto_text_on(self):
        conn = FakeConn(number=True)
        result = self._patch(conn, auto_reply=True)
        assert result["auto_reply"]["enabled"] is True
        assert conn.sql_starting("INSERT INTO workflow_rules")

    def test_turning_it_off_keeps_the_wording_for_next_time(self):
        conn = FakeConn(number=True, auto_reply=(55, True, 77, "my own words"))
        result = self._patch(conn, auto_reply=False)
        assert result["auto_reply"]["enabled"] is False
        assert result["auto_reply"]["body"] == "my own words"      # rule disabled, not deleted
        assert not conn.sql_starting("DELETE")

    def test_re_enabling_does_not_clobber_an_edited_body(self):
        # COALESCE(NULL, existing) on the conflict path: no explicit body means
        # whatever the owner wrote survives.
        conn = FakeConn(number=True, auto_reply=(55, False, 77, "my own words"))
        self._patch(conn, auto_reply=True)
        (_, params), = conn.sql_starting("INSERT INTO message_templates")
        assert params[-1] is None                                  # the COALESCE arg

    def test_editing_the_wording_implies_keeping_it_on(self):
        conn = FakeConn(number=True, auto_reply=(55, False, 77, "old"))
        result = self._patch(conn, auto_reply_body="new wording")
        assert result["auto_reply"]["enabled"] is True
        (_, params), = conn.sql_starting("INSERT INTO message_templates")
        assert params[-1] == "new wording"

    def test_overlong_wording_is_a_400(self):
        with pytest.raises(HTTPException) as exc:
            self._patch(FakeConn(number=True), auto_reply_body="x" * 5000)
        assert exc.value.status_code == 400

    def test_rewriting_and_switching_off_at_once_keeps_the_rewrite(self):
        # The wording is written before the switch is applied, so the edit
        # survives for whenever they turn it back on.
        conn = FakeConn(number=True, auto_reply=(55, True, 77, "old"))
        result = self._patch(conn, auto_reply=False, auto_reply_body="new wording")
        (_, params), = conn.sql_starting("INSERT INTO message_templates")
        assert params[-1] == "new wording"
        assert result["auto_reply"]["enabled"] is False

    def test_a_rep_can_fix_forwarding(self):
        # Forwarding is operational — anyone in the account can repair it.
        conn = FakeConn(number=True)
        self._patch(conn, user=REP, forward_to="(832) 555-0199")
        assert conn.sql_starting("UPDATE tracking_numbers SET forward_to")

    def test_a_rep_cannot_change_what_the_account_auto_texts(self):
        with pytest.raises(HTTPException) as exc:
            self._patch(FakeConn(number=True), user=REP, auto_reply=False)
        assert exc.value.status_code == 403
