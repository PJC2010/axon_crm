"""
Marketing insights — customer-acquisition recommendations from imported social data.

GET /api/insights/marketing?days=90&provider=meta_facebook

Aggregates the account's social_metrics / social_posts (and cross-references CRM
social leads) into a structured InsightInputs, then asks the configured generator
(rule-based today; swap to an LLM via INSIGHTS_GENERATOR) for the findings. All DB
access lives here; the rule logic is pure in api/marketing_insights.py.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from psycopg2.extensions import connection as PGConn

from api.deps import dict_fetchall, get_current_user, get_db
from api.marketing_insights import Benchmarks, aggregate_inputs, get_generator
from api.models import MarketingInsightsResponse
from config import (
    INSIGHTS_ENGAGEMENT_BENCHMARK, INSIGHTS_GENERATOR, INSIGHTS_MAX_CPA,
    INSIGHTS_MIN_CTR, INSIGHTS_MIN_POSTS_PER_WEEK, INSIGHTS_STALE_DAYS,
    INSIGHTS_TARGET_ROAS,
)

router = APIRouter()

_METRIC_COLS = (
    "provider, metric_date, reach, impressions, profile_views, followers, "
    "follower_delta, engagements, link_clicks, ad_spend, ad_impressions, "
    "ad_clicks, ad_cpc, ad_cpa, ad_roas, ad_results, campaign_name"
)
_POST_COLS = (
    "provider, posted_at, content_type, caption, reach, impressions, likes, "
    "comments, shares, saves, engagements, link_clicks"
)


def _coerce(row: dict) -> dict:
    """psycopg2 returns NUMERIC columns as Decimal; the pure engine expects floats."""
    for k, v in row.items():
        if isinstance(v, Decimal):
            row[k] = float(v)
    return row


@router.get("/insights/marketing", response_model=MarketingInsightsResponse)
def marketing_insights(
    days: int = Query(90, ge=1, le=730),
    provider: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    account_id = user["account_id"]
    prov_filter = " AND provider = %s" if provider else ""
    prov_args: tuple = (provider,) if provider else ()

    with db.cursor() as cur:
        # Anchor the window to the latest available data so historical uploads
        # still produce insights (rather than to a possibly-empty "last N days").
        cur.execute(
            f"SELECT MAX(metric_date) FROM social_metrics WHERE account_id = %s{prov_filter}",
            (account_id, *prov_args),
        )
        latest_metric = cur.fetchone()[0]
        cur.execute(
            f"SELECT MAX(posted_at)::date FROM social_posts WHERE account_id = %s{prov_filter}",
            (account_id, *prov_args),
        )
        latest_post = cur.fetchone()[0]

        cur.execute(
            "SELECT array_agg(DISTINCT provider) AS p, MAX(last_synced_at) AS s "
            "FROM connections WHERE account_id = %s",
            (account_id,),
        )
        conn_row = cur.fetchone()
        providers = conn_row[0] or []
        last_synced_at = conn_row[1]

        anchor = max([d for d in (latest_metric, latest_post) if d], default=None)
        if anchor is None:
            return MarketingInsightsResponse(
                insights=[], period_days=days, has_data=False, last_synced_at=last_synced_at,
            )
        start = date.fromordinal(anchor.toordinal() - days)

        cur.execute(
            f"SELECT {_METRIC_COLS} FROM social_metrics "
            f"WHERE account_id = %s AND metric_date BETWEEN %s AND %s{prov_filter}",
            (account_id, start, anchor, *prov_args),
        )
        metrics = [_coerce(r) for r in dict_fetchall(cur)]

        cur.execute(
            f"SELECT {_POST_COLS} FROM social_posts "
            f"WHERE account_id = %s AND posted_at::date BETWEEN %s AND %s{prov_filter}",
            (account_id, start, anchor, *prov_args),
        )
        posts = [_coerce(r) for r in dict_fetchall(cur)]

        cur.execute(
            "SELECT COUNT(*) FROM properties "
            "WHERE account_id = %s AND lead_source IN ('facebook', 'instagram') "
            "AND created_at >= %s",
            (account_id, start),
        )
        social_leads = cur.fetchone()[0] or 0

    benchmarks = Benchmarks(
        engagement_rate=INSIGHTS_ENGAGEMENT_BENCHMARK,
        min_posts_per_week=INSIGHTS_MIN_POSTS_PER_WEEK,
        target_roas=INSIGHTS_TARGET_ROAS,
        max_cpa=INSIGHTS_MAX_CPA,
        min_ctr=INSIGHTS_MIN_CTR,
        stale_days=INSIGHTS_STALE_DAYS,
    )
    inputs = aggregate_inputs(
        metrics, posts,
        providers=[provider] if provider else list(providers),
        last_synced_at=last_synced_at,
        period_days=days,
        social_leads_count=social_leads,
        benchmarks=benchmarks,
    )
    generator = get_generator(INSIGHTS_GENERATOR)
    insights = generator.generate(inputs)

    return MarketingInsightsResponse(
        insights=[i.to_dict() for i in insights],
        period_days=days,
        has_data=inputs.has_data,
        last_synced_at=last_synced_at,
    )
