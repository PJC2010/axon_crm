"""Unit tests for the pure digest composition in api/digest.py."""
from api.digest import compose_digest


def _base(**overrides):
    data = {
        "overdue_tasks": 0,
        "due_today": 0,
        "quotes_to_chase": 0,
        "stale_count": 0,
        "stale_value": 0,
        "top_leads": [],
        "app_url": "https://app.example.com",
    }
    data.update(overrides)
    return data


def test_empty_digest_is_not_sent():
    assert compose_digest(_base()) is None


def test_subject_leads_with_calls_and_quotes():
    subject, html = compose_digest(_base(
        top_leads=[{"label": "1842 Westheimer Rd", "grade": "A", "score": 94},
                   {"label": "504 River Oaks Blvd", "grade": "A", "score": 91},
                   {"label": "3300 Kirby Dr", "grade": "B", "score": 82}],
        quotes_to_chase=1,
    ))
    assert subject == "Axon: 3 leads to call today, 1 quote to chase"
    assert "1842 Westheimer Rd" in html
    assert "grade A" in html


def test_singular_plural_forms():
    subject, _ = compose_digest(_base(
        top_leads=[{"label": "X", "grade": None, "score": None}],
        overdue_tasks=2,
    ))
    assert "1 lead to call today" in subject
    assert "2 overdue tasks" in subject


def test_stale_value_rendered_as_money():
    _, html = compose_digest(_base(stale_count=6, stale_value=18400))
    assert "$18,400" in html
    assert "6 leads" in html


def test_app_url_cta_included():
    _, html = compose_digest(_base(overdue_tasks=1))
    assert "https://app.example.com/home" in html
