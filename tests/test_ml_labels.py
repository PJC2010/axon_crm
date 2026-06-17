"""Outcome labeling rules."""
from datetime import date, timedelta

from pipeline.ml import labels


def test_won_status_is_positive():
    assert labels.derive_label({"status": "won"}) == 1
    assert labels.derive_label({"status": "converted"}) == 1


def test_lost_statuses_are_negative():
    assert labels.derive_label({"status": "lost"}) == 0
    assert labels.derive_label({"status": "not_interested"}) == 0


def test_revenue_hint_overrides_open_status():
    assert labels.derive_label({"status": "quote_sent"}, outcome_hint="paid_invoice") == 1
    assert labels.derive_label({"status": "new"}, outcome_hint="accepted_quote") == 1


def test_fresh_open_lead_is_censored():
    row = {"status": "new", "created_at": date.today() - timedelta(days=10)}
    assert labels.derive_label(row, stale_open_days=120) is None


def test_stale_open_lead_becomes_soft_loss():
    row = {"status": "contacted", "created_at": date.today() - timedelta(days=200)}
    assert labels.derive_label(row, stale_open_days=120) == 0


def test_qualified_open_lead_is_censored_not_aged_out():
    row = {"status": "qualified", "created_at": date.today() - timedelta(days=400)}
    assert labels.derive_label(row, stale_open_days=120) is None


def test_job_value_prefers_realized_revenue():
    assert labels.derive_job_value({"invoice_total": 5000, "estimated_job_value": 9000}) == 5000.0
    assert labels.derive_job_value({"estimated_job_value": 9000}) == 9000.0
    assert labels.derive_job_value({}) is None
