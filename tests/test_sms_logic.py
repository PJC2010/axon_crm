"""Tests for api/sms_logic.py (pure) and the sender-resolution layer in
api/notifications.py.

The failure these guard against: a send rejected by Twilio 21659 — "'From'
+13466016971 is not a Twilio phone number or Short Code country mismatch" —
surfacing as an opaque 502 that says nothing about which half of the
credentials/number pair is wrong.
"""
import importlib

import pytest

from api import sms_logic


class TestNormalizeSender:
    def test_bare_us_ten_digits_becomes_e164(self):
        assert sms_logic.normalize_sender("3466016971") == "+13466016971"

    def test_formatted_number_becomes_e164(self):
        assert sms_logic.normalize_sender("(346) 601-6971") == "+13466016971"
        assert sms_logic.normalize_sender("346-601-6971") == "+13466016971"
        assert sms_logic.normalize_sender("1 346 601 6971") == "+13466016971"

    def test_already_e164_is_unchanged(self):
        assert sms_logic.normalize_sender("+13466016971") == "+13466016971"

    def test_env_var_whitespace_and_quotes_stripped(self):
        # A value pasted into a dashboard with quotes still resolves.
        assert sms_logic.normalize_sender('  "+13466016971" ') == "+13466016971"
        assert sms_logic.normalize_sender("'3466016971'") == "+13466016971"

    def test_blank_is_empty(self):
        assert sms_logic.normalize_sender(None) == ""
        assert sms_logic.normalize_sender("   ") == ""

    def test_messaging_service_sid_passes_through(self):
        sid = "MG" + "a" * 32
        assert sms_logic.normalize_sender(sid) == sid
        assert sms_logic.is_messaging_service(sid) is True

    def test_short_code_keeps_no_country_prefix(self):
        assert sms_logic.normalize_sender("894546") == "894546"

    def test_alphanumeric_sender_id_untouched(self):
        assert sms_logic.normalize_sender("AXONCRM") == "AXONCRM"

    def test_non_us_e164_preserved(self):
        assert sms_logic.normalize_sender("+442071838750") == "+442071838750"


class TestNormalizeRecipient:
    def test_imported_contact_formats_become_e164(self):
        assert sms_logic.normalize_recipient("(713) 555-0142") == "+17135550142"
        assert sms_logic.normalize_recipient("713-555-0142") == "+17135550142"
        assert sms_logic.normalize_recipient("17135550142") == "+17135550142"

    def test_e164_and_blank_pass_through(self):
        assert sms_logic.normalize_recipient("+17135550142") == "+17135550142"
        assert sms_logic.normalize_recipient("") == ""
        assert sms_logic.normalize_recipient(None) == ""

    def test_extension_text_left_alone_rather_than_mangled(self):
        assert sms_logic.normalize_recipient("713-555-0142 ext 12") == "713-555-0142 ext 12"


class _TwilioError(Exception):
    """Stand-in for twilio.base.exceptions.TwilioRestException."""

    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


class TestErrorTranslation:
    def test_21659_names_the_project_mismatch(self):
        exc = _TwilioError(
            "Unable to create record: 'From' +13466016971 is not a Twilio phone "
            "number or Short Code country mismatch", 21659)
        described = sms_logic.describe_send_failure(exc, sender="+13466016971")
        # Twilio's own wording is kept — it names the offending value.
        assert "+13466016971" in described
        # ...and the cause is spelled out in terms of this app's config.
        assert "TWILIO_ACCOUNT_SID" in described
        assert 21659 in sms_logic.SENDER_ERROR_CODES

    def test_bad_credentials_point_at_the_credentials(self):
        described = sms_logic.describe_send_failure(_TwilioError("Authenticate", 20003))
        assert "TWILIO_AUTH_TOKEN" in described

    def test_opt_out_is_not_blamed_on_config(self):
        described = sms_logic.describe_send_failure(_TwilioError("blocked", 21610),
                                                    sender="+13466016971")
        assert "STOP" in described
        assert 21610 not in sms_logic.SENDER_ERROR_CODES

    def test_unmapped_code_keeps_twilio_wording(self):
        assert sms_logic.describe_send_failure(_TwilioError("odd failure", 99999)) == "odd failure"

    def test_plain_exception_has_no_code(self):
        assert sms_logic.twilio_error_code(RuntimeError("boom")) is None
        assert sms_logic.describe_send_failure(RuntimeError("boom")) == "boom"


class TestSenderResolution:
    """notifications.resolve_sms_sender / sms_configured — which number wins."""

    def _notif(self, monkeypatch, *, from_number="+15550001111", sid="AC1", token="tok"):
        import api.notifications as notif
        importlib.reload(notif)
        monkeypatch.setattr(notif, "TWILIO_FROM_NUMBER", from_number, raising=False)
        monkeypatch.setattr(notif, "TWILIO_ACCOUNT_SID", sid, raising=False)
        monkeypatch.setattr(notif, "TWILIO_AUTH_TOKEN", token, raising=False)
        return notif

    def test_account_number_beats_global_default(self, monkeypatch):
        notif = self._notif(monkeypatch)
        assert notif.resolve_sms_sender("+13466016971") == "+13466016971"

    def test_falls_back_to_global_default(self, monkeypatch):
        notif = self._notif(monkeypatch)
        assert notif.resolve_sms_sender(None) == "+15550001111"

    def test_global_default_is_normalized(self, monkeypatch):
        notif = self._notif(monkeypatch, from_number=" 5550001111 ")
        assert notif.resolve_sms_sender(None) == "+15550001111"

    def test_account_number_covers_a_blank_global_default(self, monkeypatch):
        notif = self._notif(monkeypatch, from_number="")
        assert notif.sms_configured() is False
        assert notif.sms_configured("+13466016971") is True

    def test_missing_credentials_are_never_configured(self, monkeypatch):
        notif = self._notif(monkeypatch, sid="", token="")
        assert notif.sms_configured("+13466016971") is False


class TestSendSms:
    """The single outbound chokepoint: what actually reaches Twilio."""

    def _patched(self, monkeypatch, *, raises=None, from_number="+15550001111"):
        import api.notifications as notif
        importlib.reload(notif)
        monkeypatch.setattr(notif, "TWILIO_FROM_NUMBER", from_number, raising=False)
        monkeypatch.setattr(notif, "TWILIO_ACCOUNT_SID", "AC1", raising=False)
        monkeypatch.setattr(notif, "TWILIO_AUTH_TOKEN", "tok", raising=False)
        calls = []

        class _Messages:
            def create(self, **kwargs):
                calls.append(kwargs)
                if raises:
                    raise raises

        class _Client:
            messages = _Messages()

        monkeypatch.setattr(notif, "_twilio_client", lambda: _Client())
        return notif, calls

    def test_sends_from_the_account_number_in_e164(self, monkeypatch):
        notif, calls = self._patched(monkeypatch)
        notif.send_sms(to_phone="(713) 555-0142", body="hi", from_number="3466016971")
        assert calls == [{"body": "hi", "to": "+17135550142", "from_": "+13466016971"}]

    def test_messaging_service_sid_goes_to_its_own_field(self, monkeypatch):
        sid = "MG" + "b" * 32
        notif, calls = self._patched(monkeypatch, from_number=sid)
        notif.send_sms(to_phone="+17135550142", body="hi")
        assert calls[0]["messaging_service_sid"] == sid
        assert "from_" not in calls[0]

    def test_invoice_mms_carries_media_and_sender(self, monkeypatch):
        notif, calls = self._patched(monkeypatch)
        notif.send_invoice_sms(to_phone="+17135550142", business_name="Acme",
                               invoice_number="INV-1", amount_due=250.0,
                               pdf_url="https://x/inv.pdf", from_number="+13466016971")
        assert calls[0]["from_"] == "+13466016971"
        assert calls[0]["media_url"] == ["https://x/inv.pdf"]

    def test_quote_sms_uses_the_account_number(self, monkeypatch):
        notif, calls = self._patched(monkeypatch)
        notif.send_quote_sms(to_phone="+17135550142", business_name="Acme",
                             quote_number="Q-1", total=99.0, from_number="+13466016971")
        assert calls[0]["from_"] == "+13466016971"

    def test_twilio_rejection_becomes_an_explained_error(self, monkeypatch):
        exc = _TwilioError("Unable to create record: 'From' +13466016971 is not a "
                           "Twilio phone number or Short Code country mismatch", 21659)
        notif, _ = self._patched(monkeypatch, raises=exc, from_number="+13466016971")
        with pytest.raises(notif.SmsSendError) as caught:
            notif.send_sms(to_phone="+17135550142", body="hi")
        assert caught.value.code == 21659
        assert caught.value.sender == "+13466016971"
        assert "TWILIO_ACCOUNT_SID" in str(caught.value)
        # Still a RuntimeError, so the routes' existing handlers keep catching it.
        assert isinstance(caught.value, RuntimeError)

    def test_unconfigured_sms_raises_before_touching_twilio(self, monkeypatch):
        notif, calls = self._patched(monkeypatch, from_number="")
        with pytest.raises(RuntimeError):
            notif.send_sms(to_phone="+17135550142", body="hi")
        assert calls == []


class TestVerifySmsSender:
    """The diagnostics probe — answers "is this number on this project?"."""

    def _notif(self, monkeypatch, numbers, *, from_number="+13466016971"):
        import api.notifications as notif
        importlib.reload(notif)
        monkeypatch.setattr(notif, "TWILIO_FROM_NUMBER", from_number, raising=False)
        monkeypatch.setattr(notif, "TWILIO_ACCOUNT_SID", "AC" + "1" * 32, raising=False)
        monkeypatch.setattr(notif, "TWILIO_AUTH_TOKEN", "tok", raising=False)

        class _Number:
            def __init__(self, phone, sms=True):
                self.phone_number, self.capabilities = phone, {"sms": sms, "voice": True}

        class _Incoming:
            def list(self, limit=100):
                return [_Number(*n) if isinstance(n, tuple) else _Number(n) for n in numbers]

        class _Client:
            incoming_phone_numbers = _Incoming()

        monkeypatch.setattr(notif, "_twilio_client", lambda: _Client())
        return notif

    def test_sender_missing_from_the_project_is_reported(self, monkeypatch):
        notif = self._notif(monkeypatch, ["+18325550100"])
        report = notif.verify_sms_sender()
        assert report["owned"] is False
        assert "not on this Twilio project" in report["error"]
        assert report["source"] == "TWILIO_FROM_NUMBER"

    def test_owned_sms_capable_sender_is_clean(self, monkeypatch):
        notif = self._notif(monkeypatch, ["+13466016971"])
        report = notif.verify_sms_sender()
        assert report["owned"] is True and report["sms_capable"] is True
        assert report["error"] is None

    def test_voice_only_number_is_flagged(self, monkeypatch):
        notif = self._notif(monkeypatch, [("+13466016971", False)])
        report = notif.verify_sms_sender()
        assert report["owned"] is True and report["sms_capable"] is False
        assert "no SMS capability" in report["error"]

    def test_account_number_is_reported_as_the_source(self, monkeypatch):
        notif = self._notif(monkeypatch, ["+18325550100"])
        report = notif.verify_sms_sender("+18325550100")
        assert report["source"] == "account_tracking_number"
        assert report["owned"] is True

    def test_account_sid_is_masked(self, monkeypatch):
        notif = self._notif(monkeypatch, ["+13466016971"])
        report = notif.verify_sms_sender()
        assert "…" in report["account_sid"]
        assert len(report["account_sid"]) < 34

    def test_missing_credentials_short_circuit(self, monkeypatch):
        notif = self._notif(monkeypatch, [])
        monkeypatch.setattr(notif, "TWILIO_ACCOUNT_SID", "", raising=False)
        report = notif.verify_sms_sender()
        assert report["checked"] is False
        assert "TWILIO_ACCOUNT_SID" in report["error"]
