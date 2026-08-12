"""Tests for the pure power-dialer logic (api/dialer_logic.py): identity
encoding, queue-eligibility SQL fragments, and the disposition mappings.
No DB, no network."""
import pytest

from api import dialer_logic as dl


# ── Browser-client identity ───────────────────────────────────────────────────

class TestIdentity:
    def test_roundtrip(self):
        assert dl.parse_client_identity(dl.build_identity(3, 7)) == (3, 7)

    def test_accepts_twilio_client_prefix(self):
        assert dl.parse_client_identity("client:axon-12-34") == (12, 34)

    @pytest.mark.parametrize("raw", [
        None, "", "client:", "axon-", "axon-3", "axon-3-", "axon--7",
        "axon-x-y", "axon-3-7-9", "AXON-3-7", "other-3-7",
        "client:axon-3-7 ", "axon- 3-7", "axon-3.5-7",
    ])
    def test_rejects_malformed(self, raw):
        # A leading/trailing-space variant is stripped, so exclude the one case
        # strip() legitimately repairs.
        if raw == "client:axon-3-7 ":
            assert dl.parse_client_identity(raw) == (3, 7)
        else:
            assert dl.parse_client_identity(raw) is None


# ── Queue eligibility filters ─────────────────────────────────────────────────

class TestQueueFilters:
    def test_default_conditions(self):
        conditions, params = dl.build_queue_filters(3)
        joined = " ".join(conditions)
        assert "p.account_id = %s" in joined
        assert "p.archived_at IS NULL" in joined
        assert "p.do_not_call = FALSE" in joined
        assert "p.status = ANY(%s)" in joined
        assert "regexp_replace(COALESCE(p.contact_phone, ''), '[^0-9]', '', 'g')) >= 10" in joined
        assert "phone_append_meta,litigator" in joined
        assert "NOT EXISTS" in joined and "c2.direction = 'outbound'" in joined
        # Params line up positionally with the %s placeholders.
        assert params == [3, list(dl.QUEUE_DEFAULT_STATUSES), 4]

    def test_grade_filter_appended(self):
        conditions, params = dl.build_queue_filters(3, grade="A")
        assert "p.score_grade = %s" in " ".join(conditions)
        assert params == [3, list(dl.QUEUE_DEFAULT_STATUSES), "A", 4]

    def test_zero_cooldown_omits_not_exists(self):
        conditions, params = dl.build_queue_filters(3, cooldown_hours=0)
        assert "NOT EXISTS" not in " ".join(conditions)
        assert params == [3, list(dl.QUEUE_DEFAULT_STATUSES)]

    def test_custom_statuses(self):
        conditions, params = dl.build_queue_filters(
            3, statuses=("qualified", "contacted"), cooldown_hours=0)
        assert params == [3, ["qualified", "contacted"]]

    def test_unknown_status_raises(self):
        with pytest.raises(ValueError, match="prospect"):
            dl.build_queue_filters(3, statuses=("new", "prospect"))

    def test_unknown_grade_raises(self):
        with pytest.raises(ValueError, match="grade"):
            dl.build_queue_filters(3, grade="F")


# ── Disposition mappings ──────────────────────────────────────────────────────

class TestDispositionMaps:
    def test_every_disposition_is_covered_by_every_map(self):
        for d in dl.DISPOSITIONS:
            assert dl.is_valid_disposition(d)
            assert dl.outcome_for_disposition(d) in ("answered", "no_answer")
            assert dl.history_outcome_for(d)
            assert dl.event_for(d) in ("contacted", "contact_attempted")

    def test_invalid_disposition(self):
        assert not dl.is_valid_disposition("ghosted")
        assert not dl.is_valid_disposition(None)

    @pytest.mark.parametrize("d,outcome", [
        ("no_answer", "no_answer"),
        ("voicemail", "no_answer"),   # nobody picked up; the message is one-way
        ("interested", "answered"),
        ("not_interested", "answered"),
        ("callback", "answered"),
        ("wrong_number", "answered"),
        ("do_not_call", "answered"),
    ])
    def test_manual_outcomes(self, d, outcome):
        assert dl.outcome_for_disposition(d) == outcome

    def test_history_vocabulary_matches_activity_panel(self):
        # These strings render alongside hand-logged history rows — keep them
        # aligned with the ActivityPanel OUTCOME_OPTIONS vocabulary.
        assert dl.history_outcome_for("no_answer") == "No answer"
        assert dl.history_outcome_for("voicemail") == "Left message"
        assert dl.history_outcome_for("interested") == "Interested"
        assert dl.history_outcome_for("not_interested") == "Not interested"

    @pytest.mark.parametrize("d,event", [
        ("interested", "contacted"),
        ("not_interested", "contacted"),
        ("callback", "contacted"),
        ("no_answer", "contact_attempted"),
        ("voicemail", "contact_attempted"),
        ("wrong_number", "contact_attempted"),
        ("do_not_call", "contact_attempted"),
    ])
    def test_feedback_events(self, d, event):
        assert dl.event_for(d) == event


class TestStatusChange:
    @pytest.mark.parametrize("d,current,expected", [
        # A connect advances a brand-new lead into the pipeline…
        ("interested", "new", "contacted"),
        ("callback", "new", "contacted"),
        ("interested", None, "contacted"),
        # …but never demotes one a human already moved further.
        ("interested", "contacted", None),
        ("interested", "qualified", None),
        ("callback", "quote_sent", None),
        # A hard no closes the lead from any live stage…
        ("not_interested", "new", "not_interested"),
        ("not_interested", "contacted", "not_interested"),
        ("not_interested", "quote_sent", "not_interested"),
        # …but leaves already-decided leads alone.
        ("not_interested", "won", None),
        ("not_interested", "lost", None),
        ("not_interested", "not_interested", None),
        # Mechanical outcomes move nothing.
        ("no_answer", "new", None),
        ("voicemail", "new", None),
        ("wrong_number", "new", None),
        ("do_not_call", "new", None),
    ])
    def test_truth_table(self, d, current, expected):
        assert dl.status_change_for(d, current) == expected


# ── Small helpers ─────────────────────────────────────────────────────────────

def test_manual_call_sid_shape():
    sid = dl.manual_call_sid("ab" * 16)
    assert sid.startswith("manual-") and len(sid) == len("manual-") + 32


def test_callback_task_title():
    assert dl.callback_task_title("Jane Doe") == "Callback requested — Jane Doe"
