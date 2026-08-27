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


# ── ledger behavior (fake db) ─────────────────────────────────────────────────
# A tiny in-memory stand-in for the psycopg2 connection: just enough SQL for
# the ledger reads/writes apply_quota and the mutation guards issue, so the
# consume/no-consume/degrade-open contracts are pinned without a database.

from api.scoring_quota import apply_quota, check_reveal, require_actionable


class _FakeCursor:
    def __init__(self, db):
        self.db = db
        self._rows = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        if self.db.fail:
            raise RuntimeError("ledger down")
        s = " ".join(sql.split())
        if s.startswith("SELECT COUNT(*) FROM scoring_reveals"):
            account_id, month = params
            self._rows = [(sum(1 for a, _, m in self.db.reveals
                               if a == account_id and m == month),)]
        elif s.startswith("SELECT property_id FROM scoring_reveals"):
            account_id, month, ids = params
            self._rows = [(p,) for a, p, m in self.db.reveals
                          if a == account_id and m == month and p in ids]
        elif s.startswith("INSERT INTO scoring_reveals"):
            account_id, month, _, ids = params
            new = [(account_id, p, month) for p in ids
                   if (account_id, p, month) not in self.db.reveals]
            self.db.reveals.extend(new)
            self.db.insert_calls += 1
            self.rowcount = len(new)
        elif "FROM account_plans" in s:
            self._rows = [self.db.plan_row] if self.db.plan_row else []
        else:
            raise AssertionError(f"unexpected SQL: {s}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDb:
    def __init__(self, plan_row=None):
        self.reveals = []          # (account_id, property_id, month)
        self.plan_row = plan_row   # (plan_name, scoring_monthly_limit)
        self.fail = False
        self.insert_calls = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_apply_quota_reveals_in_display_order_then_masks():
    db = _FakeDb()
    rows = [_lead(id=1), _lead(id=2), _lead(id=3)]
    out, state = apply_quota(db, 7, rows, limit=2)
    assert [r.get("quota_masked") for r in out] == [None, None, True]
    assert state == {"limit": 2, "used": 2, "remaining": 0}
    assert {p for _, p, _ in db.reveals} == {1, 2}
    assert db.commits == 1


def test_apply_quota_already_revealed_stays_open_without_recount():
    db = _FakeDb()
    db.reveals.append((7, 3, month_start()))
    rows = [_lead(id=1), _lead(id=2), _lead(id=3)]
    out, state = apply_quota(db, 7, rows, limit=2)
    # Lead 3 was revealed earlier this month: it stays open and only one fresh
    # reveal fits the allowance, so lead 2 is the one masked.
    assert [r.get("quota_masked") for r in out] == [None, True, None]
    assert state == {"limit": 2, "used": 2, "remaining": 0}


def test_apply_quota_skips_non_candidates():
    db = _FakeDb()
    rows = [_lead(id=1, status="won"), _lead(id=2, lead_score=None), _lead(id=3)]
    out, state = apply_quota(db, 7, rows, limit=1)
    assert all(not r.get("quota_masked") for r in out)
    assert {p for _, p, _ in db.reveals} == {3}
    assert state["used"] == 1


def test_apply_quota_consume_false_masks_without_spending():
    db = _FakeDb()
    db.reveals.append((7, 1, month_start()))
    rows = [_lead(id=1), _lead(id=2)]
    out, state = apply_quota(db, 7, rows, limit=25, consume=False)
    # Already-revealed stays open; the unrevealed candidate is masked even
    # though 24 reveals remain, and the ledger is never written.
    assert [r.get("quota_masked") for r in out] == [None, True]
    assert db.insert_calls == 0 and db.commits == 0
    assert state == {"limit": 25, "used": 1, "remaining": 24}


def test_apply_quota_degrades_open_on_ledger_failure():
    db = _FakeDb()
    db.fail = True
    rows = [_lead(id=1)]
    out, state = apply_quota(db, 7, rows, limit=0)
    assert out is rows and state is None
    assert db.rollbacks == 1


def test_check_reveal_consumes_within_allowance():
    db = _FakeDb()
    assert check_reveal(db, 7, _lead(id=5), limit=1)
    assert (7, 5, month_start()) in db.reveals
    # Idempotent: the same lead re-checks open without a second slot.
    assert check_reveal(db, 7, _lead(id=5), limit=1)
    # A different candidate now exceeds the allowance.
    assert not check_reveal(db, 7, _lead(id=6), limit=1)


def test_check_reveal_ignores_non_candidates_and_unlimited():
    db = _FakeDb()
    assert check_reveal(db, 7, _lead(id=5, status="contacted"), limit=0)
    assert check_reveal(db, 7, _lead(id=6), limit=None)
    assert db.reveals == []


def test_check_reveal_degrades_open_on_ledger_failure():
    db = _FakeDb()
    db.fail = True
    assert check_reveal(db, 7, _lead(id=5), limit=0)


def test_require_actionable_403_past_allowance():
    from fastapi import HTTPException
    import pytest

    db = _FakeDb(plan_row=("starter", 1))
    require_actionable(db, 7, _lead(id=1))          # consumes the one reveal
    require_actionable(db, 7, _lead(id=1))          # same lead: still open
    with pytest.raises(HTTPException) as exc:
        require_actionable(db, 7, _lead(id=2))
    assert exc.value.status_code == 403
    assert exc.value.detail["quota"] is True and exc.value.detail["upgrade"] is True


def test_require_actionable_open_for_unlimited_plan():
    db = _FakeDb(plan_row=("pro", None))
    require_actionable(db, 7, _lead(id=1))
    assert db.reveals == []


# ── provenance: the tenant's own book is never a candidate ────────────────────

def test_own_book_lead_sources_are_never_candidates():
    for src in ("csv_import", "inbound_call", "inbound_sms", "manual",
                "website_quote_form", "website_intake_form"):
        assert not is_quota_candidate(_lead(lead_source=src)), src


def test_engine_lead_sources_stay_candidates():
    for src in (None, "prospecting", "rentcast", "hcad"):
        assert is_quota_candidate(_lead(lead_source=src)), src


def test_missing_lead_source_defaults_to_engine_candidate():
    row = _lead()
    row.pop("lead_source", None)
    assert is_quota_candidate(row)


# ── mask_named_fields (secondary surfaces) ────────────────────────────────────

from api.scoring_quota import mask_named_fields


def test_mask_named_fields_blanks_only_candidates_past_allowance():
    db = _FakeDb()
    db.reveals.append((7, 101, month_start()))          # 101 already revealed
    rows = [
        {"property_id": 101, "address": "1 A St", "owner_name": "Rev Ealed",
         "lead_score": 90.0, "status": "new"},          # revealed → visible
        {"property_id": 102, "address": "2 B St", "owner_name": "Hidden Sam",
         "lead_score": 88.0, "status": "new"},          # unrevealed → masked
        {"property_id": 103, "address": "3 C St", "owner_name": "Worked Jo",
         "lead_score": 70.0, "status": "contacted"},    # not a candidate
        {"property_id": 104, "address": "4 D St", "owner_name": "My Import",
         "lead_score": 95.0, "status": "new", "lead_source": "csv_import"},  # own book
    ]
    mask_named_fields(db, 7, rows, limit=25, id_key="property_id",
                      fields=("address", "owner_name"))
    assert rows[0]["owner_name"] == "Rev Ealed" and rows[0]["address"] == "1 A St"
    assert rows[1]["owner_name"] is None and rows[1]["address"] == "X B St"
    assert rows[2]["owner_name"] == "Worked Jo"
    assert rows[3]["owner_name"] == "My Import"          # provenance protects own book
    # Read-only: nothing written to the ledger.
    assert db.insert_calls == 0 and db.commits == 0


def test_mask_named_fields_noop_when_unlimited():
    db = _FakeDb()
    rows = [{"property_id": 1, "address": "1 A St", "owner_name": "X",
             "lead_score": 90.0, "status": "new"}]
    mask_named_fields(db, 7, rows, limit=None, id_key="property_id",
                      fields=("address", "owner_name"))
    assert rows[0]["owner_name"] == "X"
