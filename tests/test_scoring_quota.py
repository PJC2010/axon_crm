"""Pure-logic tests for the monthly scored-lead reveal quota (api/scoring_quota.py)."""
from datetime import date

from api.scoring_quota import (
    MASKED_FIELDS, is_quota_candidate, mask_lead_row, month_start,
)


def _lead(**overrides):
    row = {
        "id": 1,
        "address": "1842 Westheimer Rd",
        "account_number": "C-01001",
        "owner_name": "Maria Alvarez",
        "contact_name": "Maria Alvarez",
        "contact_phone": "713-555-0101",
        "contact_email": "maria@example.com",
        "contact_phone_alt": "713-555-0102",
        "contact_email_alt": "maria.alt@example.com",
        "mailing_address": "PO Box 100, Houston TX",
        "latitude": 29.74,
        "longitude": -95.39,
        "lead_score": 94.0,
        "score_grade": "A",
        "status": "new",
    }
    row.update(overrides)
    return row


# ── candidate selection ───────────────────────────────────────────────────────

def test_scored_new_lead_is_candidate():
    assert is_quota_candidate(_lead())


def test_unscored_lead_is_never_candidate():
    # Records the user created/imported without a score are their own book.
    assert not is_quota_candidate(_lead(lead_score=None))


def test_worked_lead_is_never_candidate():
    # Any status beyond 'new' means the user has engaged — never re-mask it.
    for status in ("contacted", "qualified", "quote_sent", "won", "lost"):
        assert not is_quota_candidate(_lead(status=status)), status


def test_missing_status_defaults_to_new():
    assert is_quota_candidate(_lead(status=None))


# ── masking ───────────────────────────────────────────────────────────────────

def test_mask_hides_identity_but_keeps_score():
    masked = mask_lead_row(_lead())
    assert masked["quota_masked"] is True
    assert masked["address"] == "18XX Westheimer Rd"
    for field in MASKED_FIELDS:
        assert masked[field] is None, field
    # The value proof stays visible — same contract as the public ZIP teaser.
    assert masked["lead_score"] == 94.0
    assert masked["score_grade"] == "A"


def test_mask_does_not_mutate_the_original():
    row = _lead()
    mask_lead_row(row)
    assert row["owner_name"] == "Maria Alvarez"
    assert "quota_masked" not in row


def test_mask_tolerates_missing_fields():
    masked = mask_lead_row({"id": 2, "address": None, "lead_score": 50.0, "status": "new"})
    assert masked["quota_masked"] is True
    assert masked["address"] == ""


# ── month bucketing ───────────────────────────────────────────────────────────

def test_month_start_truncates_to_first_of_month():
    assert month_start(date(2026, 7, 19)) == date(2026, 7, 1)
    assert month_start(date(2026, 1, 1)) == date(2026, 1, 1)
