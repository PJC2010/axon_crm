"""Unit tests for the marketing insights engine (pure, no DB)."""
from datetime import date, datetime

from api.marketing_insights import (
    Benchmarks,
    InsightInputs,
    aggregate_inputs,
    build_insights,
    _rule_ad_spend_efficiency,
    _rule_audience_growth_trend,
    _rule_best_content_type,
    _rule_data_freshness,
    _rule_engagement_vs_benchmark,
    _rule_high_intent_audience,
    _rule_reallocate_budget,
)


def _sample_inputs(**over):
    metrics = [
        {"provider": "meta_facebook", "metric_date": date(2026, 1, 1), "reach": 1000,
         "impressions": 2000, "engagements": 40, "link_clicks": 10, "profile_views": 50,
         "followers": 500, "follower_delta": 2},
        {"provider": "meta_facebook", "metric_date": date(2026, 1, 10), "reach": 1000,
         "impressions": 2000, "engagements": 40, "link_clicks": 10, "profile_views": 50,
         "followers": 520, "follower_delta": 8},
        {"provider": "meta_facebook", "metric_date": date(2026, 1, 5), "campaign_name": "A",
         "ad_spend": 100.0, "ad_results": 10, "ad_roas": 3.0},
        {"provider": "meta_facebook", "metric_date": date(2026, 1, 6), "campaign_name": "B",
         "ad_spend": 100.0, "ad_results": 2, "ad_roas": 0.5},
    ]
    posts = [
        {"content_type": "video", "posted_at": datetime(2026, 1, 2, 9), "reach": 800, "engagements": 160},
        {"content_type": "video", "posted_at": datetime(2026, 1, 4, 9), "reach": 600, "engagements": 120},
        {"content_type": "photo", "posted_at": datetime(2026, 1, 3, 18), "reach": 400, "engagements": 20},
        {"content_type": "photo", "posted_at": datetime(2026, 1, 5, 18), "reach": 300, "engagements": 15},
    ]
    return aggregate_inputs(
        metrics, posts, providers=["meta_facebook"], last_synced_at=None,
        period_days=30, now=date(2026, 1, 15), **over,
    )


# ── aggregate_inputs ──────────────────────────────────────────────────────────

def test_aggregate_totals_and_rates():
    inp = _sample_inputs()
    assert inp.total_reach == 2000          # ad rows carry no organic reach
    assert inp.total_engagements == 80
    assert inp.engagement_rate == 0.04       # 80 / 2000
    assert inp.ctr == 0.005                  # 20 / 4000
    assert inp.total_profile_views == 100


def test_aggregate_follower_trend_accelerating():
    inp = _sample_inputs()
    assert inp.follower_delta_total == 10
    assert inp.follower_delta_first == 2
    assert inp.follower_delta_last == 8


def test_aggregate_paid_and_campaigns():
    inp = _sample_inputs()
    assert inp.total_ad_spend == 200.0
    assert inp.total_ad_results == 12
    assert inp.avg_cpa == round(200 / 12, 2)
    assert inp.avg_roas == 1.75              # spend-weighted (3*100 + 0.5*100)/200
    names = {c.name: c for c in inp.campaigns}
    assert names["A"].roas == 3.0
    assert names["B"].roas == 0.5


def test_aggregate_content_type_and_best_time():
    inp = _sample_inputs()
    assert inp.by_content_type[0].content_type == "video"     # ranked by engagement rate
    assert inp.by_content_type[0].avg_engagement_rate == 0.2
    assert inp.best_hour[0] == 9                              # videos at 09:00 reach most
    assert inp.top_post["reach"] == 800
    assert inp.posts_count == 4
    assert inp.days_since_last_post == 10                     # 2026-01-15 minus 2026-01-05


# ── Individual rules: fire / abstain ──────────────────────────────────────────

def test_rule_best_content_type_fires():
    ins = _rule_best_content_type(_sample_inputs())
    assert ins is not None
    assert ins.id == "best_content_type"
    assert ins.severity == "positive"
    assert "video" in ins.recommended_action.lower()


def test_rule_engagement_above_and_below_benchmark():
    base = InsightInputs(period_days=30, benchmarks=Benchmarks(), total_reach=1000)
    base.engagement_rate = 0.05
    assert _rule_engagement_vs_benchmark(base).id == "engagement_above_benchmark"
    base.engagement_rate = 0.01
    assert _rule_engagement_vs_benchmark(base).id == "engagement_below_benchmark"


def test_rule_engagement_abstains_on_thin_data():
    base = InsightInputs(period_days=30, benchmarks=Benchmarks(), total_reach=10)
    base.engagement_rate = 0.5
    assert _rule_engagement_vs_benchmark(base) is None


def test_rule_audience_growth_trend():
    assert _rule_audience_growth_trend(_sample_inputs()).id == "audience_growing"
    flat = InsightInputs(period_days=30, benchmarks=Benchmarks(),
                         follower_delta_first=10, follower_delta_last=1, follower_delta_total=-5)
    assert _rule_audience_growth_trend(flat).id == "audience_stalling"


def test_rule_ad_spend_efficiency_abstains_without_spend():
    no_ads = InsightInputs(period_days=30, benchmarks=Benchmarks())
    assert _rule_ad_spend_efficiency(no_ads) is None


def test_rule_ad_spend_efficiency_weak_roas():
    ins = _rule_ad_spend_efficiency(_sample_inputs())
    assert ins.id == "ad_roas_weak"          # avg_roas 1.75 < target 2.0
    assert ins.severity == "warning"


def test_rule_reallocate_budget_needs_two_campaigns():
    ins = _rule_reallocate_budget(_sample_inputs())
    assert ins.id == "reallocate_budget"
    assert "A" in ins.recommended_action and "B" in ins.message

    single = InsightInputs(period_days=30, benchmarks=Benchmarks())
    assert _rule_reallocate_budget(single) is None


def test_rule_high_intent_audience():
    inp = _sample_inputs()           # 100 profile views + 20 clicks, 0 CRM leads
    ins = _rule_high_intent_audience(inp)
    assert ins is not None and ins.category == "conversion"


def test_rule_data_freshness_abstains_without_data():
    empty = InsightInputs(period_days=30, benchmarks=Benchmarks(), has_data=False)
    assert _rule_data_freshness(empty) is None


# ── Engine assembly ───────────────────────────────────────────────────────────

def test_build_insights_returns_ranked_unique_cards():
    cards = build_insights(_sample_inputs())
    assert cards, "expected at least one insight"
    ids = [c.id for c in cards]
    assert len(ids) == len(set(ids))                 # no duplicate rule ids
    assert len(cards) <= 8
    # Actionable acquisition moves are ranked ahead of warnings.
    severities = [c.severity for c in cards]
    assert severities == sorted(severities, key={"action": 0, "positive": 1, "warning": 2}.get)
    for c in cards:
        assert c.title and c.message and c.recommended_action
        assert c.severity in {"action", "positive", "warning"}
        assert c.category in {"content", "audience", "paid", "cadence", "conversion"}


def test_empty_inputs_produce_no_insights():
    empty = aggregate_inputs([], [], providers=[], last_synced_at=None, period_days=90)
    assert empty.has_data is False
    assert build_insights(empty) == []
