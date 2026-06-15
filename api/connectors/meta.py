"""
Meta (Facebook / Instagram) connector — pure parsers for manual export uploads.

Handles the three exports a user can download themselves today, no OAuth/app
review required:

  * Business Suite CSV   — organic page/profile insights, either a daily series
                           (reach/impressions/followers/...) or a post-level
                           breakdown (one row per post).
  * Ads Manager CSV      — paid campaign performance (spend / CPC / CPA / ROAS /
                           results), one row per day and/or campaign.
  * Download-Your-Info   — Facebook/Instagram "Download Your Information" JSON
    JSON                   (posts + follow events).

Column detection is alias-based and tolerant of Meta's frequent label changes and
localization (mirrors the approach in api/import_logic.py). Adding another network
is a new parser module + one entry in api/connectors/__init__.PROVIDERS.
"""
from __future__ import annotations

import csv
import io
import json

from api.connectors.base import (
    ParsedSocial,
    classify_content_type,
    key,
    parse_date,
    parse_datetime,
    parse_int,
    parse_money,
)

# ── Alias maps (normalized header -> target column) ───────────────────────────

# Account/profile-level daily organic metrics (Business Suite "Results" export).
_BS_METRIC_ALIASES = {
    "date": "metric_date",
    "day": "metric_date",
    "reach": "reach",
    "accounts reached": "reach",
    "impressions": "impressions",
    "views": "impressions",
    "profile visits": "profile_views",
    "profile views": "profile_views",
    "followers": "followers",
    "total followers": "followers",
    "net followers": "follower_delta",
    "net follower growth": "follower_delta",
    "new followers": "follower_delta",
    "follows": "follower_delta",
    "content interactions": "engagements",
    "engagement": "engagements",
    "engagements": "engagements",
    "post engagements": "engagements",
    "link clicks": "link_clicks",
}

# Post-level breakdown (Business Suite "Posts" / content export).
_POST_ALIASES = {
    "post id": "external_id",
    "id": "external_id",
    "permalink": "permalink",
    "post permalink": "permalink",
    "permalink url": "permalink",
    "publish time": "posted_at",
    "post publish time": "posted_at",
    "date": "posted_at",
    "time": "posted_at",
    "created time": "posted_at",
    "post type": "content_type",
    "media type": "content_type",
    "type": "content_type",
    "title": "caption",
    "description": "caption",
    "caption": "caption",
    "message": "caption",
    "post message": "caption",
    "reach": "reach",
    "post reach": "reach",
    "impressions": "impressions",
    "post impressions": "impressions",
    "views": "impressions",
    "reactions": "likes",
    "likes": "likes",
    "post reactions": "likes",
    "comments": "comments",
    "post comments": "comments",
    "shares": "shares",
    "post shares": "shares",
    "saves": "saves",
    "saved": "saves",
    "link clicks": "link_clicks",
    "post link clicks": "link_clicks",
    "engagements": "engagements",
    "post engagements": "engagements",
    "content interactions": "engagements",
}

# Headers that mark a CSV as a post-level export rather than a daily series.
_POST_MARKERS = {"external_id", "permalink", "content_type", "caption"}

# Paid campaign performance (Ads Manager export).
_ADS_ALIASES = {
    "day": "metric_date",
    "date": "metric_date",
    "reporting starts": "metric_date",
    "campaign name": "campaign_name",
    "campaign": "campaign_name",
    "ad set name": "campaign_name",
    "amount spent": "ad_spend",
    "amount spent usd": "ad_spend",
    "spend": "ad_spend",
    "impressions": "ad_impressions",
    "link clicks": "ad_clicks",
    "clicks all": "ad_clicks",
    "clicks": "ad_clicks",
    "cpc cost per link click": "ad_cpc",
    "cpc cost per link click usd": "ad_cpc",
    "cpc all": "ad_cpc",
    "cpc": "ad_cpc",
    "cost per result": "ad_cpa",
    "cost per results": "ad_cpa",
    "results": "ad_results",
    "purchase roas return on ad spend": "ad_roas",
    "website purchase roas return on ad spend": "ad_roas",
    "purchase roas": "ad_roas",
    "roas": "ad_roas",
}

# Headers that mark a CSV as an Ads Manager export.
_ADS_MARKERS = {"ad_spend", "ad_roas", "ad_results", "ad_cpa"}

_METRIC_INT_FIELDS = {
    "reach", "impressions", "profile_views", "followers", "follower_delta",
    "engagements", "link_clicks", "ad_impressions", "ad_clicks", "ad_results",
}
_METRIC_MONEY_FIELDS = {"ad_spend", "ad_cpc", "ad_cpa", "ad_roas"}
_POST_INT_FIELDS = {
    "reach", "impressions", "likes", "comments", "shares", "saves",
    "engagements", "link_clicks",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect(raw: dict, aliases: dict) -> dict:
    """Map a raw CSV row to target fields, taking the first non-empty value per
    target (so duplicate/variant columns don't clobber each other)."""
    out: dict = {}
    for header, val in raw.items():
        target = aliases.get(key(header))
        if not target or target in out or val is None:
            continue
        sval = str(val).strip()
        if sval:
            out[target] = sval
    return out


def _read_csv(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    return headers, list(reader)


def _header_targets(headers: list[str], aliases: dict) -> set[str]:
    return {aliases[key(h)] for h in headers if aliases.get(key(h))}


# ── Business Suite organic CSV ────────────────────────────────────────────────

def parse_business_suite_csv(text: str) -> ParsedSocial:
    """Parse a Meta Business Suite organic export — auto-detecting whether it is a
    post-level breakdown or an account-level daily series."""
    result = ParsedSocial(export_kind="business_suite_csv")
    headers, rows = _read_csv(text)
    if not headers:
        result.errors.append("No columns found in file")
        return result

    is_post_export = bool(_header_targets(headers, _POST_ALIASES) & _POST_MARKERS)

    for i, raw in enumerate(rows, start=1):
        try:
            if is_post_export:
                post = _build_post(raw, "facebook")
                if post:
                    result.posts.append(post)
            else:
                metric = _build_metric(raw, _BS_METRIC_ALIASES, "facebook")
                if metric:
                    result.metrics.append(metric)
        except Exception as exc:  # never let one row abort the parse
            result.errors.append(f"row {i}: {exc}")

    return result.finalize()


# ── Ads Manager CSV ───────────────────────────────────────────────────────────

def parse_ads_manager_csv(text: str) -> ParsedSocial:
    """Parse a Meta Ads Manager paid-performance export into metric rows."""
    result = ParsedSocial(export_kind="ads_manager_csv")
    headers, rows = _read_csv(text)
    if not headers:
        result.errors.append("No columns found in file")
        return result

    for i, raw in enumerate(rows, start=1):
        try:
            metric = _build_metric(raw, _ADS_ALIASES, "facebook")
            if metric:
                result.metrics.append(metric)
        except Exception as exc:
            result.errors.append(f"row {i}: {exc}")

    return result.finalize()


# ── Download-Your-Information JSON ────────────────────────────────────────────

def parse_dyi_json(data) -> ParsedSocial:
    """Parse a Facebook/Instagram "Download Your Information" JSON export.

    Meta's JSON shapes vary widely, so this walks defensively: it pulls any
    post-like objects (timestamp + media/type) into posts, and aggregates follow
    events into per-day follower_delta metric rows.
    """
    result = ParsedSocial(export_kind="dyi_json")

    for obj in _walk_posts(data):
        try:
            post = _post_from_dyi(obj)
            if post:
                result.posts.append(post)
        except Exception as exc:
            result.errors.append(f"post: {exc}")

    follows = _follow_dates(data)
    if follows:
        per_day: dict = {}
        for d in follows:
            per_day[d] = per_day.get(d, 0) + 1
        for d, count in sorted(per_day.items()):
            result.metrics.append({
                "metric_date": d,
                "follower_delta": count,
                "raw": {"new_followers": count},
            })

    return result.finalize()


# ── Row builders ──────────────────────────────────────────────────────────────

def _build_metric(raw: dict, aliases: dict, provider: str) -> dict | None:
    collected = _collect(raw, aliases)
    metric_date = parse_date(collected.get("metric_date"))
    if not metric_date:
        return None

    out: dict = {"metric_date": metric_date}
    if collected.get("campaign_name"):
        out["campaign_name"] = collected["campaign_name"]

    for fld in _METRIC_INT_FIELDS:
        if fld in collected:
            v = parse_int(collected[fld])
            if v is not None:
                out[fld] = v
    for fld in _METRIC_MONEY_FIELDS:
        if fld in collected:
            v = parse_money(collected[fld])
            if v is not None:
                out[fld] = v

    # A row is only worth storing if it carries at least one actual metric.
    if not any(k not in ("metric_date", "campaign_name") for k in out):
        return None
    out["raw"] = {k: v for k, v in raw.items() if v not in (None, "")}
    return out


def _build_post(raw: dict, provider: str) -> dict | None:
    collected = _collect(raw, _POST_ALIASES)
    out: dict = {}

    posted_at = parse_datetime(collected.get("posted_at"))
    if posted_at:
        out["posted_at"] = posted_at
    for fld in ("external_id", "permalink", "caption"):
        if collected.get(fld):
            out[fld] = collected[fld]
    if collected.get("content_type"):
        out["content_type"] = classify_content_type(collected["content_type"])
    for fld in _POST_INT_FIELDS:
        if fld in collected:
            v = parse_int(collected[fld])
            if v is not None:
                out[fld] = v

    if not out.get("external_id") and out.get("permalink"):
        out["external_id"] = out["permalink"]
    # Usable only if we can identify or place the post.
    if not (out.get("external_id") or out.get("posted_at") or out.get("caption")):
        return None
    out["raw"] = {k: v for k, v in raw.items() if v not in (None, "")}
    return out


# ── DYI JSON walking ──────────────────────────────────────────────────────────

_POST_LIST_KEYS = (
    "organic_insights_posts", "posts", "media", "photos", "videos",
    "ig_posts", "post", "string_list_data",
)
_TS_KEYS = ("creation_timestamp", "timestamp", "create_time", "taken_at", "time")
_MEDIA_KEYS = ("media_type", "type", "post_type")


def _walk_posts(data, _depth: int = 0):
    """Yield dicts that look like posts (have a timestamp + media/caption/insights)."""
    if _depth > 8:
        return
    if isinstance(data, dict):
        looks_like_post = (
            any(k in data for k in _TS_KEYS)
            and (any(k in data for k in _MEDIA_KEYS)
                 or "string_map_data" in data
                 or "media_map_data" in data
                 or "title" in data
                 or "caption" in data)
        )
        if looks_like_post:
            yield data
        for v in data.values():
            yield from _walk_posts(v, _depth + 1)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_posts(item, _depth + 1)


def _smd_value(obj: dict, *names: str):
    """Pull a value out of Meta's `string_map_data` insight maps by label."""
    smd = obj.get("string_map_data") or {}
    wanted = {key(n) for n in names}
    for label, entry in smd.items():
        if key(label) in wanted and isinstance(entry, dict):
            return entry.get("value")
    return None


def _post_from_dyi(obj: dict) -> dict | None:
    out: dict = {}
    ts = next((obj[k] for k in _TS_KEYS if obj.get(k)), None)
    posted_at = parse_datetime(str(ts)) if ts is not None else None
    if posted_at:
        out["posted_at"] = posted_at

    media = next((obj[k] for k in _MEDIA_KEYS if obj.get(k)), None)
    if media:
        out["content_type"] = classify_content_type(str(media))

    caption = obj.get("title") or obj.get("caption")
    if caption:
        out["caption"] = str(caption)

    for tgt, labels in (
        ("reach", ("Accounts reached", "Reach")),
        ("impressions", ("Impressions",)),
        ("likes", ("Likes",)),
        ("comments", ("Comments",)),
        ("shares", ("Shares",)),
        ("saves", ("Saves", "Saved")),
    ):
        v = parse_int(_smd_value(obj, *labels))
        if v is not None:
            out[tgt] = v

    if not (out.get("posted_at") or out.get("caption")):
        return None
    return out


def _follow_dates(data, _depth: int = 0) -> list:
    """Collect timestamps from follower/following list_data entries."""
    dates: list = []
    if _depth > 8:
        return dates
    if isinstance(data, dict):
        for k, v in data.items():
            if "follower" in key(k) and isinstance(v, list):
                for item in v:
                    sld = item.get("string_list_data") if isinstance(item, dict) else None
                    for entry in (sld or []):
                        d = parse_date(str(entry.get("timestamp"))) if isinstance(entry, dict) else None
                        if d:
                            dates.append(d)
            else:
                dates.extend(_follow_dates(v, _depth + 1))
    elif isinstance(data, list):
        for item in data:
            dates.extend(_follow_dates(item, _depth + 1))
    return dates


# ── Dispatch ──────────────────────────────────────────────────────────────────

def sniff_export_kind(filename: str, headers: list[str] | None = None) -> str:
    """Pick the parser for an upload from its name + detected columns."""
    name = (filename or "").lower()
    if name.endswith(".json"):
        return "dyi_json"
    if headers and (_header_targets(headers, _ADS_ALIASES) & _ADS_MARKERS):
        return "ads_manager_csv"
    return "business_suite_csv"


def parse_meta(content: bytes, filename: str) -> ParsedSocial:
    """Top-level entry: decode an uploaded Meta export and dispatch to a parser."""
    name = (filename or "").lower()
    if name.endswith(".json"):
        try:
            data = json.loads(content.decode("utf-8-sig", errors="replace"))
        except json.JSONDecodeError as exc:
            res = ParsedSocial(export_kind="dyi_json")
            res.errors.append(f"Invalid JSON: {exc}")
            return res
        return parse_dyi_json(data)

    text = content.decode("utf-8-sig", errors="replace")
    headers, _ = _read_csv(text)
    kind = sniff_export_kind(filename, headers)
    if kind == "ads_manager_csv":
        return parse_ads_manager_csv(text)
    return parse_business_suite_csv(text)
