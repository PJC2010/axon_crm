"""
Marketing insights engine — turns imported digital-presence data into concrete
customer-acquisition recommendations.

Pure and DB-free (same style as pipeline/scoring.py and api/import_logic.py): the
route in api/routes/insights.py fetches social_metrics / social_posts rows, calls
``aggregate_inputs`` to build a structured ``InsightInputs``, then asks a generator
for the findings. Rules are deterministic today.

The LLM seam: ``InsightGenerator`` is the swap point. ``RuleBasedGenerator`` runs
the deterministic rule catalog now; a future ``ClaudeGenerator`` would consume the
*identical* ``InsightInputs`` and return the *identical* ``list[Insight]``, so the
endpoint and frontend never change — only the ``INSIGHTS_GENERATOR`` env var flips.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Callable, Optional, Protocol


# ── Output contract (mirrors the frontend Insight card shape) ─────────────────

@dataclass
class Insight:
    id: str
    severity: str            # 'positive' | 'warning' | 'action'
    category: str            # 'content' | 'audience' | 'paid' | 'cadence' | 'conversion'
    title: str
    message: str
    recommended_action: str
    supporting_metric: dict = field(default_factory=dict)  # {label, value, comparison?}

    def to_dict(self) -> dict:
        return asdict(self)


# ── Tunable benchmarks (defaults come from config in the route) ───────────────

@dataclass
class Benchmarks:
    engagement_rate: float = 0.03    # 3% of reach
    min_posts_per_week: int = 3
    target_roas: float = 2.0
    max_cpa: float = 50.0
    min_ctr: float = 0.01            # 1% of impressions
    stale_days: int = 30


# ── Structured engine input ───────────────────────────────────────────────────

@dataclass
class ContentTypeStat:
    content_type: str
    count: int
    avg_reach: float
    avg_engagement_rate: float       # engagement / reach


@dataclass
class CampaignStat:
    name: str
    spend: float
    results: int
    roas: Optional[float]
    cpa: Optional[float]


@dataclass
class InsightInputs:
    period_days: int
    benchmarks: Benchmarks
    providers: list[str] = field(default_factory=list)
    last_synced_at: Optional[datetime] = None
    has_data: bool = False
    # organic totals
    total_reach: int = 0
    total_impressions: int = 0
    total_engagements: int = 0
    total_link_clicks: int = 0
    total_profile_views: int = 0
    engagement_rate: Optional[float] = None   # total_engagements / total_reach
    ctr: Optional[float] = None               # total_link_clicks / total_impressions
    # audience trend (net follower change, first vs last half of the window)
    follower_delta_first: int = 0
    follower_delta_last: int = 0
    follower_delta_total: int = 0
    # posts
    posts_count: int = 0
    posts_per_week: float = 0.0
    days_since_last_post: Optional[int] = None
    by_content_type: list[ContentTypeStat] = field(default_factory=list)
    best_hour: Optional[tuple[int, float]] = None   # (hour, avg_reach)
    best_weekday: Optional[tuple[str, float]] = None
    top_post: Optional[dict] = None
    # paid
    total_ad_spend: float = 0.0
    total_ad_results: int = 0
    avg_roas: Optional[float] = None
    avg_cpa: Optional[float] = None
    campaigns: list[CampaignStat] = field(default_factory=list)
    # per-provider organic reach-per-follower, for channel comparison
    channel_reach_per_follower: dict[str, float] = field(default_factory=dict)
    # CRM cross-reference
    social_leads_count: int = 0


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _post_engagement(p: dict) -> Optional[int]:
    if p.get("engagements") is not None:
        return p["engagements"]
    parts = [p.get(k) for k in ("likes", "comments", "shares", "saves")]
    vals = [v for v in parts if v is not None]
    return sum(vals) if vals else None


def aggregate_inputs(
    metrics: list[dict],
    posts: list[dict],
    *,
    providers: list[str],
    last_synced_at: Optional[datetime],
    period_days: int,
    social_leads_count: int = 0,
    benchmarks: Optional[Benchmarks] = None,
    now: Optional[date] = None,
) -> InsightInputs:
    """Roll raw social_metrics / social_posts rows up into a structured
    ``InsightInputs``. Pure — every value the rules need is precomputed here."""
    bm = benchmarks or Benchmarks()
    now = now or date.today()
    inp = InsightInputs(
        period_days=period_days,
        benchmarks=bm,
        providers=sorted(set(providers)),
        last_synced_at=last_synced_at,
        has_data=bool(metrics or posts),
        social_leads_count=social_leads_count,
    )

    # ── Organic + paid totals from metric rows ────────────────────────────────
    follower_rows: list[tuple[date, int]] = []
    per_provider_reach: dict[str, int] = defaultdict(int)
    per_provider_followers: dict[str, int] = defaultdict(int)
    ad_rows: list[dict] = []
    roas_weighted_sum = 0.0
    roas_weight = 0.0

    for m in metrics:
        prov = m.get("provider") or ""
        inp.total_reach += m.get("reach") or 0
        inp.total_impressions += m.get("impressions") or 0
        inp.total_engagements += m.get("engagements") or 0
        inp.total_link_clicks += m.get("link_clicks") or 0
        inp.total_profile_views += m.get("profile_views") or 0
        if m.get("reach"):
            per_provider_reach[prov] += m["reach"]
        if m.get("followers"):
            per_provider_followers[prov] = max(per_provider_followers[prov], m["followers"])
        if m.get("follower_delta") is not None and m.get("metric_date"):
            follower_rows.append((m["metric_date"], m["follower_delta"]))
        # An ad row is any row carrying spend or a campaign label.
        if m.get("ad_spend") is not None or m.get("campaign_name"):
            ad_rows.append(m)
            spend = m.get("ad_spend") or 0.0
            inp.total_ad_spend += spend
            inp.total_ad_results += m.get("ad_results") or 0
            if m.get("ad_roas") is not None and spend > 0:
                roas_weighted_sum += m["ad_roas"] * spend
                roas_weight += spend

    if inp.total_reach > 0:
        inp.engagement_rate = round(inp.total_engagements / inp.total_reach, 4)
    if inp.total_impressions > 0:
        inp.ctr = round(inp.total_link_clicks / inp.total_impressions, 4)

    # ── Follower trend (first vs last half of the window) ─────────────────────
    follower_rows.sort(key=lambda r: r[0])
    inp.follower_delta_total = sum(d for _, d in follower_rows)
    if follower_rows:
        mid = len(follower_rows) // 2
        inp.follower_delta_first = sum(d for _, d in follower_rows[:mid or 1])
        inp.follower_delta_last = sum(d for _, d in follower_rows[mid:])

    # ── Paid rollups ──────────────────────────────────────────────────────────
    if inp.total_ad_results > 0:
        inp.avg_cpa = round(inp.total_ad_spend / inp.total_ad_results, 2)
    if roas_weight > 0:
        inp.avg_roas = round(roas_weighted_sum / roas_weight, 2)

    camp: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "results": 0, "rw": 0.0, "rws": 0.0})
    for m in ad_rows:
        name = m.get("campaign_name") or "(unnamed)"
        c = camp[name]
        spend = m.get("ad_spend") or 0.0
        c["spend"] += spend
        c["results"] += m.get("ad_results") or 0
        if m.get("ad_roas") is not None and spend > 0:
            c["rws"] += m["ad_roas"] * spend
            c["rw"] += spend
    for name, c in camp.items():
        inp.campaigns.append(CampaignStat(
            name=name,
            spend=round(c["spend"], 2),
            results=c["results"],
            roas=round(c["rws"] / c["rw"], 2) if c["rw"] > 0 else None,
            cpa=round(c["spend"] / c["results"], 2) if c["results"] > 0 else None,
        ))
    inp.campaigns.sort(key=lambda c: c.spend, reverse=True)

    # ── Channel reach-per-follower ────────────────────────────────────────────
    for prov, reach in per_provider_reach.items():
        followers = per_provider_followers.get(prov, 0)
        if followers > 0:
            inp.channel_reach_per_follower[prov] = round(reach / followers, 3)

    # ── Post-level rollups ────────────────────────────────────────────────────
    inp.posts_count = len(posts)
    weeks = max(period_days / 7.0, 1.0)
    inp.posts_per_week = round(inp.posts_count / weeks, 1)

    posted_dates = [p["posted_at"] for p in posts if isinstance(p.get("posted_at"), datetime)]
    if posted_dates:
        inp.days_since_last_post = (now - max(posted_dates).date()).days

    by_type: dict[str, dict] = defaultdict(lambda: {"count": 0, "reach": 0, "er_sum": 0.0, "er_n": 0})
    by_hour: dict[int, dict] = defaultdict(lambda: {"count": 0, "reach": 0})
    by_wday: dict[int, dict] = defaultdict(lambda: {"count": 0, "reach": 0})
    top_post = None
    for p in posts:
        ct = p.get("content_type") or "other"
        eng = _post_engagement(p)
        reach = p.get("reach") or 0
        t = by_type[ct]
        t["count"] += 1
        t["reach"] += reach
        if reach > 0 and eng is not None:
            t["er_sum"] += eng / reach
            t["er_n"] += 1
        if isinstance(p.get("posted_at"), datetime):
            h = by_hour[p["posted_at"].hour]
            h["count"] += 1
            h["reach"] += reach
            w = by_wday[p["posted_at"].weekday()]
            w["count"] += 1
            w["reach"] += reach
        if top_post is None or reach > (top_post.get("reach") or 0):
            top_post = p
    inp.top_post = top_post

    for ct, t in by_type.items():
        inp.by_content_type.append(ContentTypeStat(
            content_type=ct,
            count=t["count"],
            avg_reach=round(t["reach"] / t["count"], 1) if t["count"] else 0.0,
            avg_engagement_rate=round(t["er_sum"] / t["er_n"], 4) if t["er_n"] else 0.0,
        ))
    inp.by_content_type.sort(key=lambda s: s.avg_engagement_rate, reverse=True)

    def _best(bucket: dict):
        best_k, best_avg = None, -1.0
        for k, v in bucket.items():
            if v["count"] >= 1:
                avg = v["reach"] / v["count"]
                if avg > best_avg:
                    best_k, best_avg = k, avg
        return (best_k, round(best_avg, 1)) if best_k is not None else None

    bh = _best(by_hour)
    inp.best_hour = bh
    bw = _best(by_wday)
    inp.best_weekday = (_WEEKDAYS[bw[0]], bw[1]) if bw else None

    return inp


def _pct(x: Optional[float]) -> str:
    return f"{round((x or 0) * 100, 1)}%"


# ── Rule catalog (each returns an Insight or None) ────────────────────────────

def _rule_best_content_type(inp: InsightInputs) -> Optional[Insight]:
    ranked = [s for s in inp.by_content_type if s.count >= 2 and s.avg_engagement_rate > 0]
    if len(ranked) < 2:
        return None
    best = ranked[0]
    rest = ranked[1:]
    avg_rest = sum(s.avg_engagement_rate for s in rest) / len(rest)
    if avg_rest <= 0 or best.avg_engagement_rate <= avg_rest:
        return None
    mult = round(best.avg_engagement_rate / avg_rest, 1)
    return Insight(
        id="best_content_type", severity="positive", category="content",
        title=f"{best.content_type.title()} posts engage best",
        message=(f"Your {best.content_type} posts earn a {_pct(best.avg_engagement_rate)} "
                 f"engagement rate — about {mult}× your other formats."),
        recommended_action=f"Publish more {best.content_type} content to reach more potential customers.",
        supporting_metric={"label": f"{best.content_type.title()} engagement rate",
                           "value": _pct(best.avg_engagement_rate),
                           "comparison": f"{mult}× other formats"},
    )


def _rule_best_posting_time(inp: InsightInputs) -> Optional[Insight]:
    if not inp.best_weekday and not inp.best_hour:
        return None
    day = inp.best_weekday[0] if inp.best_weekday else None
    hour = inp.best_hour[0] if inp.best_hour else None
    when = ", ".join(x for x in [day, f"{hour:02d}:00" if hour is not None else None] if x)
    reach = inp.best_weekday[1] if inp.best_weekday else inp.best_hour[1]
    return Insight(
        id="best_posting_time", severity="action", category="cadence",
        title="Best time to post",
        message=f"Posts published around {when} reach the most people (avg {int(reach)} reached).",
        recommended_action=f"Schedule your key posts around {when} to maximize reach.",
        supporting_metric={"label": "Top posting window", "value": when,
                           "comparison": f"avg {int(reach)} reached"},
    )


def _rule_engagement_vs_benchmark(inp: InsightInputs) -> Optional[Insight]:
    if inp.engagement_rate is None or inp.total_reach < 100:
        return None
    bm = inp.benchmarks.engagement_rate
    if inp.engagement_rate >= bm:
        return Insight(
            id="engagement_above_benchmark", severity="positive", category="content",
            title="Strong engagement rate",
            message=(f"Your audience engages at {_pct(inp.engagement_rate)}, above the "
                     f"{_pct(bm)} benchmark — content is resonating."),
            recommended_action="Keep this content style and add a clear call-to-action to convert engagement into leads.",
            supporting_metric={"label": "Engagement rate", "value": _pct(inp.engagement_rate),
                               "comparison": f"benchmark {_pct(bm)}"},
        )
    return Insight(
        id="engagement_below_benchmark", severity="warning", category="content",
        title="Engagement below benchmark",
        message=(f"Engagement is {_pct(inp.engagement_rate)}, under the {_pct(bm)} benchmark. "
                 f"Weak engagement limits how far your reach grows."),
        recommended_action="Ask questions, use stronger hooks, and post more of what already works to lift engagement.",
        supporting_metric={"label": "Engagement rate", "value": _pct(inp.engagement_rate),
                           "comparison": f"benchmark {_pct(bm)}"},
    )


def _rule_audience_growth_trend(inp: InsightInputs) -> Optional[Insight]:
    if not any(d for d in (inp.follower_delta_first, inp.follower_delta_last, inp.follower_delta_total)):
        return None
    if inp.follower_delta_last > inp.follower_delta_first and inp.follower_delta_total > 0:
        return Insight(
            id="audience_growing", severity="positive", category="audience",
            title="Your audience is growing",
            message=(f"You netted {inp.follower_delta_total} new followers this period, and growth "
                     f"is accelerating — more reach for every post."),
            recommended_action="Capitalize on momentum: post consistently and pin a clear offer to convert new followers.",
            supporting_metric={"label": "Net new followers", "value": inp.follower_delta_total,
                               "comparison": "accelerating"},
        )
    if inp.follower_delta_total <= 0 or inp.follower_delta_last < inp.follower_delta_first:
        return Insight(
            id="audience_stalling", severity="warning", category="audience",
            title="Follower growth is stalling",
            message=(f"Net follower change is {inp.follower_delta_total} and slowing. A flat audience "
                     f"caps how many new customers you can reach organically."),
            recommended_action="Run a follower-growth push — collaborations, a giveaway, or a small boost on your best post.",
            supporting_metric={"label": "Net new followers", "value": inp.follower_delta_total,
                               "comparison": "slowing"},
        )
    return None


def _rule_posting_cadence_gap(inp: InsightInputs) -> Optional[Insight]:
    target = inp.benchmarks.min_posts_per_week
    if inp.posts_count == 0:
        return None
    if inp.posts_per_week >= target and (inp.days_since_last_post or 0) <= 7:
        return None
    gap_note = (f" Your last post was {inp.days_since_last_post} days ago."
                if inp.days_since_last_post and inp.days_since_last_post > 7 else "")
    return Insight(
        id="posting_cadence_gap", severity="action", category="cadence",
        title="Post more consistently",
        message=(f"You averaged {inp.posts_per_week} posts/week, below the {target}/week that keeps "
                 f"you top-of-feed.{gap_note}"),
        recommended_action=f"Aim for at least {target} posts per week to stay visible to prospective customers.",
        supporting_metric={"label": "Posts per week", "value": inp.posts_per_week,
                           "comparison": f"target {target}"},
    )


def _rule_ad_spend_efficiency(inp: InsightInputs) -> Optional[Insight]:
    if inp.total_ad_spend <= 0:
        return None
    bm = inp.benchmarks
    if inp.avg_roas is not None:
        if inp.avg_roas >= bm.target_roas:
            return Insight(
                id="ad_roas_strong", severity="positive", category="paid",
                title="Ads are profitable — scale them",
                message=(f"Your ads return {inp.avg_roas}× on ${inp.total_ad_spend:,.0f} spent, above your "
                         f"{bm.target_roas}× target."),
                recommended_action="Increase budget on your winning campaigns to acquire more customers at the same return.",
                supporting_metric={"label": "Return on ad spend", "value": f"{inp.avg_roas}×",
                                   "comparison": f"target {bm.target_roas}×"},
            )
        return Insight(
            id="ad_roas_weak", severity="warning", category="paid",
            title="Ad return below target",
            message=(f"Ads return {inp.avg_roas}× on ${inp.total_ad_spend:,.0f} spent, under your "
                     f"{bm.target_roas}× target — you may be overspending."),
            recommended_action="Pause low-return campaigns and shift budget to your best audiences/creatives.",
            supporting_metric={"label": "Return on ad spend", "value": f"{inp.avg_roas}×",
                               "comparison": f"target {bm.target_roas}×"},
        )
    if inp.avg_cpa is not None and inp.avg_cpa > bm.max_cpa:
        return Insight(
            id="ad_cpa_high", severity="warning", category="paid",
            title="Cost per result is high",
            message=(f"You're paying ${inp.avg_cpa:,.2f} per result, above your ${bm.max_cpa:,.0f} ceiling."),
            recommended_action="Tighten targeting and refresh creative to bring your cost per customer down.",
            supporting_metric={"label": "Cost per result", "value": f"${inp.avg_cpa:,.2f}",
                               "comparison": f"max ${bm.max_cpa:,.0f}"},
        )
    return None


def _rule_reallocate_budget(inp: InsightInputs) -> Optional[Insight]:
    rated = [c for c in inp.campaigns if c.roas is not None and c.spend > 0]
    if len(rated) < 2:
        return None
    best = max(rated, key=lambda c: c.roas)
    worst = min(rated, key=lambda c: c.roas)
    if best.name == worst.name or best.roas <= worst.roas:
        return None
    return Insight(
        id="reallocate_budget", severity="action", category="paid",
        title="Reallocate ad budget",
        message=(f"'{best.name}' returns {best.roas}× while '{worst.name}' returns {worst.roas}×. "
                 f"You're spending ${worst.spend:,.0f} on the weaker one."),
        recommended_action=f"Move budget from '{worst.name}' to '{best.name}' to win more customers at the same spend.",
        supporting_metric={"label": "Best vs worst ROAS", "value": f"{best.roas}× vs {worst.roas}×",
                           "comparison": f"${worst.spend:,.0f} reallocatable"},
    )


def _rule_underperforming_channel(inp: InsightInputs) -> Optional[Insight]:
    rpf = inp.channel_reach_per_follower
    if len(rpf) < 2:
        return None
    strong = max(rpf, key=rpf.get)
    weak = min(rpf, key=rpf.get)
    if strong == weak or rpf[weak] <= 0 or rpf[strong] < rpf[weak] * 1.5:
        return None
    label = {"meta_facebook": "Facebook", "meta_instagram": "Instagram"}
    return Insight(
        id="underperforming_channel", severity="warning", category="audience",
        title=f"{label.get(weak, weak)} is underperforming",
        message=(f"{label.get(weak, weak)} reaches {rpf[weak]}× its followers vs "
                 f"{rpf[strong]}× on {label.get(strong, strong)} — that channel is under-leveraged."),
        recommended_action=f"Cross-post your best {label.get(strong, strong)} content to {label.get(weak, weak)} to expand reach.",
        supporting_metric={"label": "Reach per follower", "value": f"{rpf[weak]}× vs {rpf[strong]}×",
                           "comparison": f"{label.get(weak, weak)} lagging"},
    )


def _rule_high_intent_audience(inp: InsightInputs) -> Optional[Insight]:
    intent = inp.total_profile_views + inp.total_link_clicks
    if intent < 25 or intent <= inp.social_leads_count * 3:
        return None
    return Insight(
        id="high_intent_audience", severity="action", category="conversion",
        title="High-intent visitors aren't converting",
        message=(f"You had {intent:,} profile visits and link clicks but only "
                 f"{inp.social_leads_count} social leads in your CRM — interest isn't turning into contacts."),
        recommended_action="Add a booking link or lead form to your profile and posts to capture these visitors.",
        supporting_metric={"label": "Profile visits + clicks", "value": f"{intent:,}",
                           "comparison": f"{inp.social_leads_count} CRM leads"},
    )


def _rule_top_post_amplify(inp: InsightInputs) -> Optional[Insight]:
    p = inp.top_post
    if not p or not p.get("reach"):
        return None
    caption = (p.get("caption") or "").strip()
    snippet = (caption[:40] + "…") if len(caption) > 40 else (caption or "your top post")
    return Insight(
        id="top_post_amplify", severity="action", category="content",
        title="Amplify your best post",
        message=(f"“{snippet}” reached {p['reach']:,} people — already your strongest content."),
        recommended_action="Boost this post with a small budget to extend its reach to similar new customers.",
        supporting_metric={"label": "Top post reach", "value": f"{p['reach']:,}",
                           "comparison": "organic"},
    )


def _rule_impressions_to_clicks(inp: InsightInputs) -> Optional[Insight]:
    if inp.ctr is None or inp.total_impressions < 500:
        return None
    if inp.ctr >= inp.benchmarks.min_ctr:
        return None
    return Insight(
        id="low_click_through", severity="warning", category="content",
        title="People see you but don't click",
        message=(f"Your click-through rate is {_pct(inp.ctr)} on {inp.total_impressions:,} impressions — "
                 f"below the {_pct(inp.benchmarks.min_ctr)} benchmark."),
        recommended_action="Add a clear call-to-action and a link in your posts so viewers take the next step.",
        supporting_metric={"label": "Click-through rate", "value": _pct(inp.ctr),
                           "comparison": f"benchmark {_pct(inp.benchmarks.min_ctr)}"},
    )


def _rule_data_freshness(inp: InsightInputs) -> Optional[Insight]:
    if not inp.has_data:
        return None
    stale_days = inp.benchmarks.stale_days
    if inp.last_synced_at is not None:
        age = (datetime.utcnow() - inp.last_synced_at.replace(tzinfo=None)).days
        if age <= stale_days:
            return None
        note = f"Your last upload was {age} days ago."
    else:
        note = "We don't have a recent upload on record."
    return Insight(
        id="data_freshness", severity="warning", category="audience",
        title="Refresh your data",
        message=f"{note} Insights are most accurate with recent data.",
        recommended_action="Upload a fresh Meta export so your recommendations stay current.",
        supporting_metric={"label": "Data age", "value": f"> {stale_days} days"},
    )


RULES: list[Callable[[InsightInputs], Optional[Insight]]] = [
    _rule_best_content_type,
    _rule_best_posting_time,
    _rule_engagement_vs_benchmark,
    _rule_audience_growth_trend,
    _rule_posting_cadence_gap,
    _rule_ad_spend_efficiency,
    _rule_reallocate_budget,
    _rule_underperforming_channel,
    _rule_high_intent_audience,
    _rule_top_post_amplify,
    _rule_impressions_to_clicks,
    _rule_data_freshness,
]

# Render order: actionable acquisition moves first, then wins, then warnings.
_SEVERITY_ORDER = {"action": 0, "positive": 1, "warning": 2}


def build_insights(inp: InsightInputs, limit: int = 8) -> list[Insight]:
    """Run the deterministic rule catalog over the inputs and rank the findings."""
    found = [ins for rule in RULES if (ins := rule(inp)) is not None]
    found.sort(key=lambda i: _SEVERITY_ORDER.get(i.severity, 9))
    return found[:limit]


# ── Generator seam (swap in an LLM later without touching route/frontend) ─────

class InsightGenerator(Protocol):
    def generate(self, inp: InsightInputs) -> list[Insight]:
        ...


class RuleBasedGenerator:
    """Deterministic generator — the default today."""
    def generate(self, inp: InsightInputs) -> list[Insight]:
        return build_insights(inp)


# A future ClaudeGenerator would implement the same .generate(inp) -> list[Insight]
# contract, consuming the identical InsightInputs. Register it here and select via
# the INSIGHTS_GENERATOR env var.
GENERATORS: dict[str, Callable[[], InsightGenerator]] = {
    "rules": RuleBasedGenerator,
}


def get_generator(name: str) -> InsightGenerator:
    factory = GENERATORS.get(name) or GENERATORS["rules"]
    return factory()
