"""Unit tests for the Meta connector parsers (pure, no DB)."""
import json
from datetime import date

from api.connectors import get_parser, PROVIDERS
from api.connectors.meta import (
    parse_ads_manager_csv,
    parse_business_suite_csv,
    parse_dyi_json,
    parse_meta,
    sniff_export_kind,
)


# ── Business Suite daily metrics ──────────────────────────────────────────────

def test_business_suite_daily_metrics():
    csv = (
        "Date,Reach,Impressions,Profile visits,Followers,Net Followers,Content interactions,Link clicks\n"
        "2026-01-01,1000,2000,50,500,5,40,10\n"
        "2026-01-02,1100,2200,60,505,5,44,12\n"
    )
    res = parse_business_suite_csv(csv)
    assert res.export_kind == "business_suite_csv"
    assert len(res.metrics) == 2
    assert res.posts == []
    m = res.metrics[0]
    assert m["metric_date"] == date(2026, 1, 1)
    assert m["reach"] == 1000
    assert m["impressions"] == 2000
    assert m["profile_views"] == 50
    assert m["followers"] == 500
    assert m["follower_delta"] == 5
    assert m["engagements"] == 40
    assert m["link_clicks"] == 10
    assert res.period_start == date(2026, 1, 1)
    assert res.period_end == date(2026, 1, 2)


def test_business_suite_handles_thousands_separators():
    csv = "Date,Reach,Impressions\n2026-03-01,\"1,234\",\"5,678\"\n"
    res = parse_business_suite_csv(csv)
    assert res.metrics[0]["reach"] == 1234
    assert res.metrics[0]["impressions"] == 5678


# ── Business Suite post-level ─────────────────────────────────────────────────

def test_business_suite_post_export_detected():
    csv = (
        "Post ID,Publish time,Post type,Title,Reach,Impressions,Reactions,Comments,Shares,Saves\n"
        "123,2026-01-02 09:00:00,Video,My great reel,800,1500,60,10,5,8\n"
        "124,2026-01-03 18:00:00,Photo,A photo,300,500,20,2,1,3\n"
    )
    res = parse_business_suite_csv(csv)
    assert res.metrics == []
    assert len(res.posts) == 2
    p = res.posts[0]
    assert p["external_id"] == "123"
    assert p["content_type"] == "video"
    assert p["caption"] == "My great reel"
    assert p["reach"] == 800
    assert p["likes"] == 60          # "Reactions" -> likes
    assert p["comments"] == 10
    assert p["shares"] == 5
    assert p["saves"] == 8
    assert p["posted_at"].year == 2026 and p["posted_at"].hour == 9


# ── Ads Manager ───────────────────────────────────────────────────────────────

def test_ads_manager_csv():
    csv = (
        "Day,Campaign name,Amount spent (USD),Impressions,Link clicks,"
        "CPC (cost per link click) (USD),Cost per result,Results,"
        "Purchase ROAS (return on ad spend)\n"
        "2026-01-01,Spring Promo,100.00,5000,200,0.50,10.00,10,3.0\n"
    )
    res = parse_ads_manager_csv(csv)
    assert res.export_kind == "ads_manager_csv"
    assert len(res.metrics) == 1
    m = res.metrics[0]
    assert m["campaign_name"] == "Spring Promo"
    assert m["ad_spend"] == 100.0
    assert m["ad_impressions"] == 5000
    assert m["ad_clicks"] == 200
    assert m["ad_cpc"] == 0.5
    assert m["ad_cpa"] == 10.0
    assert m["ad_results"] == 10
    assert m["ad_roas"] == 3.0


def test_sniff_distinguishes_ads_from_organic():
    ads_headers = ["Day", "Campaign name", "Amount spent (USD)", "Results"]
    organic_headers = ["Date", "Reach", "Impressions", "Followers"]
    assert sniff_export_kind("report.csv", ads_headers) == "ads_manager_csv"
    assert sniff_export_kind("report.csv", organic_headers) == "business_suite_csv"
    assert sniff_export_kind("export.json", []) == "dyi_json"


# ── Download Your Information JSON ─────────────────────────────────────────────

def test_dyi_json_posts_and_followers():
    data = {
        "organic_insights_posts": [
            {
                "creation_timestamp": 1735732800,   # 2025-01-01
                "media_type": "VIDEO",
                "title": "Hello world",
                "string_map_data": {
                    "Accounts reached": {"value": "1200"},
                    "Impressions": {"value": "2000"},
                    "Likes": {"value": "80"},
                },
            }
        ],
        "followers_1": [
            {"string_list_data": [{"timestamp": 1735732800}]},
            {"string_list_data": [{"timestamp": 1735819200}]},
        ],
    }
    res = parse_dyi_json(data)
    assert res.export_kind == "dyi_json"
    assert len(res.posts) == 1
    p = res.posts[0]
    assert p["content_type"] == "video"
    assert p["caption"] == "Hello world"
    assert p["reach"] == 1200
    assert p["impressions"] == 2000
    assert p["likes"] == 80
    # Two follow events on two distinct days -> two follower_delta metric rows.
    assert len(res.metrics) == 2
    assert all(m.get("follower_delta") == 1 for m in res.metrics)


def test_parse_meta_dispatch_by_filename():
    organic = b"Date,Reach,Impressions\n2026-01-01,10,20\n"
    res = parse_meta(organic, "page_overview.csv")
    assert res.export_kind == "business_suite_csv"

    payload = json.dumps({"posts": [{"creation_timestamp": 1735732800, "media_type": "IMAGE", "title": "x"}]}).encode()
    res2 = parse_meta(payload, "instagram.json")
    assert res2.export_kind == "dyi_json"
    assert len(res2.posts) == 1


def test_registry_wires_meta_providers():
    assert set(PROVIDERS) >= {"meta_facebook", "meta_instagram"}
    assert get_parser("meta_facebook") is parse_meta
    assert get_parser("unknown") is None


def test_bad_rows_do_not_abort_parse():
    csv = "Date,Reach\nnot-a-date,100\n2026-01-01,200\n"
    res = parse_business_suite_csv(csv)
    # The undated row is simply skipped (not usable), the good one is kept.
    assert len(res.metrics) == 1
    assert res.metrics[0]["reach"] == 200
