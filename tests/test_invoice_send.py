"""
Tests for invoice delivery (api/notifications.py) that run without a database.

Covers the per-channel provider-config guards. The DB-backed send flow
(POST /api/invoices/{id}/send) is exercised manually / in integration.
"""
import importlib

import pytest


def test_notifications_config_guards(monkeypatch):
    import api.notifications as notif
    importlib.reload(notif)
    # With empty creds (default in test env), both channels report unconfigured.
    monkeypatch.setattr(notif, "RESEND_API_KEY", "", raising=False)
    monkeypatch.setattr(notif, "RESEND_FROM_EMAIL", "", raising=False)
    monkeypatch.setattr(notif, "TWILIO_ACCOUNT_SID", "", raising=False)
    assert notif.email_configured() is False
    assert notif.sms_configured() is False

    with pytest.raises(RuntimeError):
        notif.send_invoice_email(to_email="a@b.com", business_name="Biz",
                                 invoice_number="INV-1", amount_due=10.0)
    with pytest.raises(RuntimeError):
        notif.send_invoice_sms(to_phone="+15555550123", business_name="Biz",
                               invoice_number="INV-1", amount_due=10.0)


def test_email_configured_requires_both_key_and_from(monkeypatch):
    import api.notifications as notif
    importlib.reload(notif)
    monkeypatch.setattr(notif, "RESEND_API_KEY", "re_test", raising=False)
    monkeypatch.setattr(notif, "RESEND_FROM_EMAIL", "", raising=False)
    assert notif.email_configured() is False
    monkeypatch.setattr(notif, "RESEND_FROM_EMAIL", "billing@x.com", raising=False)
    assert notif.email_configured() is True
