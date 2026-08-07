"""Tests for pipeline/http.py — retry/backoff and the answered/unanswered split.

`requests` is stubbed, so nothing here touches the network.
"""
import pytest
import requests

from pipeline import http


class _Response:
    def __init__(self, status_code=200, payload=None, raises=None):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if self._raises:
            raise self._raises
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    """Queue up responses (or exceptions) for successive GETs."""
    def install(*outcomes):
        calls = []

        def _get(url, **kwargs):
            calls.append(url)
            outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(http.requests, "get", _get)
        monkeypatch.setattr(http.time, "sleep", lambda s: None)
        return calls

    return install


def test_success_returns_payload_and_reports_answered(fake_get):
    fake_get(_Response(200, {"ok": True}))
    assert http.get_json_result("http://x") == ({"ok": True}, True)


def test_not_found_is_an_answer_not_a_failure(fake_get):
    """A vendor 404 means "no record for this address". It is a real answer, and
    callers that stamp a row as asked depend on telling it from an outage."""
    calls = fake_get(_Response(404))
    assert http.get_json_result("http://x") == (None, True)
    assert len(calls) == 1, "a 404 cannot change — do not spend retries on it"


def test_timeout_is_not_an_answer(fake_get):
    fake_get(requests.ConnectionError("boom"))
    data, answered = http.get_json_result("http://x", retries=2)
    assert (data, answered) == (None, False)


def test_retryable_status_that_never_clears_is_not_an_answer(fake_get):
    calls = fake_get(_Response(503))
    data, answered = http.get_json_result("http://x", retries=2)
    assert (data, answered) == (None, False)
    assert len(calls) == 3      # initial attempt + 2 retries


def test_retryable_status_that_recovers_returns_the_payload(fake_get):
    fake_get(_Response(500), _Response(200, {"ok": True}))
    assert http.get_json_result("http://x", retries=2) == ({"ok": True}, True)


def test_rate_limit_is_retried_not_treated_as_a_definitive_no(fake_get):
    calls = fake_get(_Response(429), _Response(200, {"ok": True}))
    assert http.get_json_result("http://x", retries=2)[0] == {"ok": True}
    assert len(calls) == 2


def test_unparseable_body_is_retried_then_reported_unanswered(fake_get):
    calls = fake_get(_Response(200, raises=ValueError("not json")))
    assert http.get_json_result("http://x", retries=1) == (None, False)
    assert len(calls) == 2


def test_get_json_keeps_its_original_contract(fake_get):
    """Existing callers still get plain data-or-None and never see an exception."""
    fake_get(_Response(200, [{"a": 1}]))
    assert http.get_json("http://x") == [{"a": 1}]

    fake_get(requests.Timeout("slow"))
    assert http.get_json("http://x", retries=0) is None

    fake_get(_Response(404))
    assert http.get_json("http://x") is None
