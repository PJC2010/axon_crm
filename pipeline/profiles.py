"""Scoring profiles — the config layer between business types and the scorer.

A ScoringProfile bundles everything `pipeline.scoring.compute_score` needs to
score a record: signal weights, the per-signal metadata (which row field each
signal reads, plus UI label/description), and the signal functions themselves.
The property profiles below are built straight from config.py, so existing
home-services scoring is byte-identical to the pre-profile code (enforced by
parity tests in tests/test_scoring.py).

Non-property profiles (e.g. retail RFM over order roll-ups, insurance renewal
proximity) plug in by defining their own factor_meta/signal_fns — the scorer
never assumes property columns.
"""
from dataclasses import dataclass
from typing import Callable

import config
from pipeline import scoring


@dataclass(frozen=True)
class ScoringProfile:
    key: str
    label: str
    weights: dict[str, float]              # must sum to 1.0
    factor_meta: dict[str, dict]           # signal key -> {label, field, description}
    signal_fns: dict[str, Callable]        # signal key -> fn(value) -> 0.0..1.0
    gates: tuple = ()                      # qualifier signals; confirmed absence
                                           # multiplies the score by GATE_MISS_FACTOR


def _property_profile(key: str, weights: dict[str, float]) -> ScoringProfile:
    """A profile over the classic property signal set (config.FACTOR_META).

    Validated at load time (validate_weights) so a typo'd weight key fails at
    import, not mid-score. Qualifier gates come from config.VERTICAL_GATES.
    """
    scoring.validate_weights(weights)
    return ScoringProfile(
        key=key,
        label=key.replace("_", " ").title(),
        weights=weights,
        factor_meta=config.FACTOR_META,
        signal_fns=scoring._SIGNAL_FNS,
        gates=tuple(config.VERTICAL_GATES.get(key, ())),
    )


DEFAULT_PROFILE_KEY = "default"


# ── Non-property profiles (Phase 6 definitions — rescore activation deferred) ──
# These score computed roll-ups, not properties columns. The row fields
# (days_to_expiration, order_count_365d, …) are produced by a future
# account-wide rescore job that aggregates the policies/orders child tables;
# nothing writes lead_score from these yet. Defining them here (with tests)
# pins the signal math and keeps the explanation UI contract ready.

def _renewal_proximity_signal(days_to_expiration) -> float:
    """Closer renewals are hotter: 1.0 at/inside 30 days, fading to 0 at 180+."""
    if days_to_expiration is None or days_to_expiration < 0:
        return 0.0
    if days_to_expiration <= 30:
        return 1.0
    return max(0.0, 1.0 - (days_to_expiration - 30) / 150)


def _mono_line_signal(policy_count) -> float:
    """Cross-sell headroom: one line = prime target, full households less so."""
    if not policy_count or policy_count <= 0:
        return 0.0
    return {1: 1.0, 2: 0.5}.get(int(policy_count), 0.2)


def _premium_signal(premium_in_force) -> float:
    """Account value, saturating at $2,500 annualized premium."""
    if not premium_in_force or premium_in_force <= 0:
        return 0.0
    return min(1.0, premium_in_force / 2500)


def _order_recency_signal(days_since_last_order) -> float:
    """RFM recency: 1.0 for a purchase today, 0 at a year+."""
    if days_since_last_order is None or days_since_last_order < 0:
        return 0.0
    return max(0.0, 1.0 - days_since_last_order / 365)


def _order_frequency_signal(order_count_365d) -> float:
    """RFM frequency, saturating at 6 orders/year."""
    if not order_count_365d or order_count_365d <= 0:
        return 0.0
    return min(1.0, order_count_365d / 6)


def _monetary_signal(lifetime_spend) -> float:
    """RFM monetary, saturating at $1,000 lifetime."""
    if not lifetime_spend or lifetime_spend <= 0:
        return 0.0
    return min(1.0, lifetime_spend / 1000)


def _engagement_signal(activity_count_90d) -> float:
    """How actively the lead is being worked: calls/texts logged, tasks
    completed, and notes added in the last 90 days. For pipeline businesses
    (general sales, professional services) engagement is the single strongest
    conversion predictor — a lead nobody is touching is going cold regardless of
    its deal value. Saturates at 5 touches."""
    if not activity_count_90d or activity_count_90d <= 0:
        return 0.0
    return min(1.0, activity_count_90d / 5)


def _activity_recency_signal(days_since_last_activity) -> float:
    """Freshness of the last touch: 1.0 for activity today, fading linearly to 0
    at 60 days of silence. A recently-worked lead is hotter than a dormant one."""
    if days_since_last_activity is None or days_since_last_activity < 0:
        return 0.0
    return max(0.0, 1.0 - days_since_last_activity / 60)


def _deal_value_signal(deal_value) -> float:
    """Deal / engagement value from the lead's estimated value, saturating at
    $10,000. Bigger deals earn more of the rep's attention, but value is the
    tie-breaker behind engagement and recency — not the headline signal."""
    if not deal_value or deal_value <= 0:
        return 0.0
    return min(1.0, deal_value / 10000)


INSURANCE_RENEWAL_PROFILE = ScoringProfile(
    key="insurance_renewal",
    label="Insurance renewal & cross-sell",
    weights={"renewal_proximity": 0.5, "mono_line": 0.3, "premium": 0.2},
    factor_meta={
        "renewal_proximity": {
            "label": "Renewal proximity",
            "field": "days_to_expiration",
            "description": "Policies renewing soon (inside 30–180 days) are the moment to remarket.",
        },
        "mono_line": {
            "label": "Cross-sell headroom",
            "field": "policy_count",
            "description": "Mono-line clients (one policy) are the strongest cross-sell targets.",
        },
        "premium": {
            "label": "Premium in force",
            "field": "premium_in_force",
            "description": "Larger books (toward $2,500 annualized) justify more attention.",
        },
    },
    signal_fns={
        "renewal_proximity": _renewal_proximity_signal,
        "mono_line": _mono_line_signal,
        "premium": _premium_signal,
    },
)

RETAIL_RFM_PROFILE = ScoringProfile(
    key="retail_rfm",
    label="Retail RFM",
    weights={"recency": 0.45, "frequency": 0.30, "monetary": 0.25},
    factor_meta={
        "recency": {
            "label": "Purchase recency",
            "field": "days_since_last_order",
            "description": "Customers who bought recently (within the year) respond best.",
        },
        "frequency": {
            "label": "Purchase frequency",
            "field": "order_count_365d",
            "description": "More orders in the last 12 months (toward 6) means a stronger habit.",
        },
        "monetary": {
            "label": "Lifetime spend",
            "field": "lifetime_spend",
            "description": "Higher lifetime spend (toward $1,000) marks the customers to retain.",
        },
    },
    signal_fns={
        "recency": _order_recency_signal,
        "frequency": _order_frequency_signal,
        "monetary": _monetary_signal,
    },
)


PIPELINE_ENGAGEMENT_PROFILE = ScoringProfile(
    key="pipeline_engagement",
    label="Pipeline engagement",
    weights={"engagement": 0.45, "recency": 0.30, "deal_value": 0.25},
    factor_meta={
        "engagement": {
            "label": "Engagement",
            "field": "activity_count_90d",
            "description": "Calls, tasks, and notes logged on the lead in the last 90 days — an actively worked lead converts best.",
        },
        "recency": {
            "label": "Last activity",
            "field": "days_since_last_activity",
            "description": "How recently the lead was touched; a fresh follow-up beats a dormant deal.",
        },
        "deal_value": {
            "label": "Deal value",
            "field": "deal_value",
            "description": "Estimated deal / engagement value (toward $10,000) — the tie-breaker behind engagement.",
        },
    },
    signal_fns={
        "engagement": _engagement_signal,
        "recency": _activity_recency_signal,
        "deal_value": _deal_value_signal,
    },
)


PROFILES: dict[str, ScoringProfile] = {
    DEFAULT_PROFILE_KEY: _property_profile(DEFAULT_PROFILE_KEY, config.DEFAULT_WEIGHTS),
    **{key: _property_profile(key, weights) for key, weights in config.VERTICAL_WEIGHTS.items()},
    INSURANCE_RENEWAL_PROFILE.key: INSURANCE_RENEWAL_PROFILE,
    RETAIL_RFM_PROFILE.key: RETAIL_RFM_PROFILE,
    PIPELINE_ENGAGEMENT_PROFILE.key: PIPELINE_ENGAGEMENT_PROFILE,
}

# Rows that max out every signal of the non-property profiles — used by the
# profile-invariant tests (property profiles use their own PERFECT_ROW).
PROFILE_PERFECT_ROWS: dict[str, dict] = {
    "insurance_renewal": {"days_to_expiration": 15, "policy_count": 1, "premium_in_force": 2500},
    "retail_rfm": {"days_since_last_order": 0, "order_count_365d": 6, "lifetime_spend": 1000},
    "pipeline_engagement": {"activity_count_90d": 5, "days_since_last_activity": 0, "deal_value": 10000},
}

# Which scoring profile an account uses when it isn't property/vertical-driven.
# Property business types (home_services, …) score per-vertical via score_zip;
# these types score account-wide over child-object roll-ups (see
# pipeline/account_rescore.py). A business type absent here has no account-wide
# scoring — its records keep whatever score the pipeline set (usually none).
SCORING_PROFILE_BY_BUSINESS_TYPE: dict[str, str] = {
    "insurance_agency": "insurance_renewal",
    "retail": "retail_rfm",
    # Non-property pipeline businesses have no child-object roll-up; they score
    # from the lead's own engagement, freshness, and deal value (see
    # pipeline/account_rescore.py _ROLLUPS["pipeline_engagement"]).
    "general_sales": "pipeline_engagement",
    "professional_services": "pipeline_engagement",
}


def resolve_profile(key: str | None) -> ScoringProfile:
    """Same fallback rule scorer.score_zip has always used: an unknown or
    missing vertical scores with the default property weights."""
    if key and key in PROFILES:
        return PROFILES[key]
    return PROFILES[DEFAULT_PROFILE_KEY]
