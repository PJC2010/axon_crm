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


def _property_profile(key: str, weights: dict[str, float]) -> ScoringProfile:
    """A profile over the classic property signal set (config.FACTOR_META)."""
    return ScoringProfile(
        key=key,
        label=key.replace("_", " ").title(),
        weights=weights,
        factor_meta=config.FACTOR_META,
        signal_fns=scoring._SIGNAL_FNS,
    )


DEFAULT_PROFILE_KEY = "default"

PROFILES: dict[str, ScoringProfile] = {
    DEFAULT_PROFILE_KEY: _property_profile(DEFAULT_PROFILE_KEY, config.DEFAULT_WEIGHTS),
    **{key: _property_profile(key, weights) for key, weights in config.VERTICAL_WEIGHTS.items()},
}


def resolve_profile(key: str | None) -> ScoringProfile:
    """Same fallback rule scorer.score_zip has always used: an unknown or
    missing vertical scores with the default property weights."""
    if key and key in PROFILES:
        return PROFILES[key]
    return PROFILES[DEFAULT_PROFILE_KEY]
