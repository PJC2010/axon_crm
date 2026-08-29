"""
Regional scoring calibration — a layer over the national matrix, not a fork.

`config.py` holds one national weight matrix and one set of signal thresholds.
This module applies per-market deltas on top of them at score time, resolved
from the ZIP being scored, so a future national recalibration propagates into
every market instead of being re-litigated per region. The deltas themselves —
and the sourcing behind each number — live in `config.REGIONAL_CALIBRATION_MATRIX`
and `docs/regional_calibration.md`.

Pure and DB-free, like `pipeline/scoring.py`. It imports `scoring` (to build a
market's signal functions) but never `profiles`, which imports this — that is
what keeps the dependency one-directional.

The rule that decides what may live in this layer at all:

    A regional factor earns a WEIGHT only if it varies between two homes in the
    same market.

Cooling degree days, electricity price, net-metering policy, growing-season
length and relative humidity are all real drivers of regional demand and none of
them are scoring signals: they are identical for every lead in the market, so
weighting them adds the same constant to every score, moves no lead past any
other, and inflates the grade distribution while pretending to rank. Those land
in `base_rate()` (a forecasting prior) and `job_value_multiplier()` (ticket
size). Only the within-market discriminators — component age, storm and hail
exposure, floor area, garage count, occupancy, equity — reach `weights`.
"""
import logging

import config
from pipeline import scoring

log = logging.getLogger(__name__)

NATIONAL = "us"

# A region key is only trusted for a ZIP whose state agrees. A mistyped ZIP on a
# Louisiana row must not silently pick up Texas hail calibration.
REGION_STATES = {
    "tx":         "TX",
    "tx_houston": "TX",
}


# ── Region resolution ─────────────────────────────────────────────────────────

def _region_for_zip3(zip3: str) -> str:
    """ZIP3 → region key. Unknown, malformed and uncalibrated ZIPs score nationally."""
    if len(zip3) != 3 or not zip3.isdigit():
        return NATIONAL
    if zip3 in config.TX_GULF_ZIP3:
        return "tx_houston"
    n = int(zip3)
    if any(lo <= n <= hi for lo, hi in config.TX_ZIP3_RANGES):
        return "tx"
    return NATIONAL


def is_enabled() -> bool:
    """False when REGIONAL_CALIBRATION=off — every market scores nationally."""
    return config.REGIONAL_CALIBRATION != "off"


def region_for_zip(zip_code: str | None, state: str | None = None) -> str:
    """The most specific region key covering a ZIP, or NATIONAL.

    `state` is a cross-check, not an input: when the row carries one and it
    disagrees with the ZIP's region, the ZIP is the thing that's wrong, so the
    lead falls back to national rather than being calibrated for a market it
    isn't in.
    """
    if not zip_code:
        return NATIONAL
    region = _region_for_zip3(str(zip_code).strip()[:3])
    expected = REGION_STATES.get(region)
    if expected and state and str(state).strip().upper() != expected:
        return NATIONAL
    return region


def resolve_region(zip_code: str | None = None, state: str | None = None) -> str:
    """The region a lead scores in, honouring the REGIONAL_CALIBRATION setting.

    "auto" derives it from the ZIP; "off" forces national; anything else pins
    every lead to that region (how you reproduce a customer's numbers locally).
    """
    setting = config.REGIONAL_CALIBRATION
    if setting == "off":
        return NATIONAL
    if setting and setting != "auto":
        if setting in config.REGIONAL_CALIBRATION_MATRIX:
            return setting
        log.warning("REGIONAL_CALIBRATION=%r is not a known region; scoring nationally", setting)
        return NATIONAL
    return region_for_zip(zip_code, state)


def region_chain(region: str) -> list[str]:
    """[root … leaf] — the inheritance path deltas merge along.

    Root first, so a plain `dict.update` per step leaves the most specific
    region's values on top. Unknown regions degrade to the national chain
    rather than raising: a bad env var must not stop the pipeline scoring.
    """
    if region not in config.REGIONAL_CALIBRATION_MATRIX:
        return [NATIONAL]
    chain = []
    seen = set()
    node = region
    while node and node not in seen:
        seen.add(node)
        chain.append(node)
        node = config.REGION_PARENTS.get(node)
    chain.reverse()
    return chain


def label(region: str) -> str:
    """Human-readable market name, for the score-explanation UI."""
    return config.REGION_LABELS.get(region, region)


# ── Delta merging ─────────────────────────────────────────────────────────────

def _merge(region: str, section: str, vertical: str | None = None) -> dict:
    """Merge one section of the matrix down the region chain.

    With `vertical`, merges that vertical's sub-dict of the section instead of
    the section itself — the shape `verticals` uses.
    """
    out: dict = {}
    for node in region_chain(region):
        block = config.REGIONAL_CALIBRATION_MATRIX.get(node, {}).get(section) or {}
        if vertical is not None:
            block = (block.get(vertical) or {})
        out.update(block)
    return out


def thresholds_for(region: str, vertical: str | None = None) -> dict:
    """Signal thresholds for a market, region-wide overrides then vertical ones.

    Only keys the market actually states appear; `scoring.build_signal_fns`
    fills the rest from the national defaults.
    """
    out = _merge(region, "thresholds")
    if vertical:
        for node in region_chain(region):
            spec = (config.REGIONAL_CALIBRATION_MATRIX.get(node, {})
                    .get("verticals") or {}).get(vertical) or {}
            out.update(spec.get("thresholds") or {})
    unknown = set(out) - set(scoring.DEFAULT_THRESHOLDS)
    if unknown:
        raise ValueError(
            f"Region {region!r}/{vertical!r} overrides unknown threshold(s): {sorted(unknown)}"
        )
    return out


def weight_spec_for(region: str, vertical: str) -> dict:
    """The merged {scale, set} delta for one vertical in one market."""
    scale: dict = {}
    pin: dict = {}
    for node in region_chain(region):
        spec = (config.REGIONAL_CALIBRATION_MATRIX.get(node, {})
                .get("verticals") or {}).get(vertical) or {}
        scale.update(spec.get("scale") or {})
        pin.update(spec.get("set") or {})
    return {"scale": scale, "set": pin}


# ── Weight arithmetic ─────────────────────────────────────────────────────────

def apply_weight_spec(weights: dict, spec: dict) -> dict:
    """Apply a regional delta to a national weight profile. Sums to exactly 1.0.

    Two operations, deliberately different in kind:

      scale — multiply a weight the national profile already carries. Relative,
              so it survives a national recalibration: "storm matters ~15% more
              in Texas" stays true whatever storm's national share becomes.
              0.0 removes the signal.
      set   — pin an EXACT final share. This is how a signal the national profile
              doesn't carry at all gets introduced, and the only way to state a
              weight in absolute terms. Everything not pinned rescales to fill
              1 − Σset, preserving the national profile's internal proportions.

    Scaling a signal the profile doesn't weight is a typo, not a no-op, and
    raises: it would otherwise fail silently and forever.
    """
    scale = spec.get("scale") or {}
    pinned = {k: float(v) for k, v in (spec.get("set") or {}).items()}

    unknown_scale = set(scale) - set(weights)
    if unknown_scale:
        raise ValueError(
            f"Regional 'scale' names signal(s) absent from the base profile "
            f"(use 'set' to introduce one): {sorted(unknown_scale)}"
        )
    for key, value in pinned.items():
        if not 0.0 <= value < 1.0:
            raise ValueError(f"Regional 'set' weight for {key!r} must be in [0, 1): {value}")

    scaled = {k: w * scale.get(k, 1.0) for k, w in weights.items()}
    rest = {k: w for k, w in scaled.items() if k not in pinned}

    pinned_total = sum(pinned.values())
    if pinned_total >= 1.0:
        raise ValueError(f"Regional pinned weights sum to {pinned_total}, leaving nothing to rank on")
    rest_total = sum(rest.values())
    if rest_total <= 0:
        raise ValueError("Regional spec scaled every unpinned weight to zero")

    factor = (1.0 - pinned_total) / rest_total
    out = {k: w * factor for k, w in rest.items()}
    out.update(pinned)

    # Keep the national profile's key order so a diff of two profiles reads
    # cleanly, with introduced signals appended.
    order = list(weights) + [k for k in pinned if k not in weights]
    return _normalize_exact({k: out[k] for k in order})


def _normalize_exact(weights: dict, places: int = 4) -> dict:
    """Round to `places` and push the rounding residual onto the largest weight.

    Weights are read by humans in the explanation UI and diffed in review, so
    they are rounded rather than left at full float precision — but they must
    still sum to exactly 1.0 or `validate_weights` rejects the profile.
    """
    out = {k: round(w, places) for k, w in weights.items()}
    residual = round(1.0 - sum(out.values()), places + 2)
    if residual and out:
        biggest = max(out, key=lambda k: out[k])
        out[biggest] = round(out[biggest] + residual, places + 2)
    return out


# ── Public calibration entry point ────────────────────────────────────────────

def calibrate(vertical: str | None, region: str) -> dict:
    """Everything a market changes about scoring one vertical.

    Returns a plain dict rather than a ScoringProfile so this module stays free
    of `pipeline.profiles`, which imports it. `profiles.resolve_profile` is the
    caller that turns this into a profile.
    """
    key = vertical if vertical in config.VERTICAL_WEIGHTS else "default"
    base = config.VERTICAL_WEIGHTS.get(key, config.DEFAULT_WEIGHTS)

    thresholds = thresholds_for(region, key)
    spec = weight_spec_for(region, key)
    weights = apply_weight_spec(base, spec) if (spec["scale"] or spec["set"]) else dict(base)

    return {
        "region":               region,
        "label":                label(region),
        "vertical":             key,
        "weights":              weights,
        "thresholds":           thresholds,
        "signal_fns":           scoring.build_signal_fns(thresholds),
        "job_value_multiplier": job_value_multiplier(region, key),
        "base_rate":            base_rate(region, key),
    }


# ── Market priors (never touch a lead's rank) ─────────────────────────────────

def job_value_multiplier(region: str, vertical: str | None) -> float:
    """Multiplier on JOB_VALUE_MODEL's output for a market.

    Note that `us` is NOT a neutral baseline here: `config.JOB_VALUE_MODEL`'s
    numbers were written as rough Houston-market defaults, so a Texas multiplier
    above 1.0 is claiming a market is dearer *than Houston already is*, not
    dearer than the nation. Only the two verticals the research separates from
    that baseline — season-length-driven landscaping and humidity-driven epoxy —
    carry one.
    """
    if not vertical:
        return 1.0
    return float(_merge(region, "job_value").get(vertical, 1.0))


def base_rate(region: str, vertical: str | None) -> float | None:
    """Annual purchase incidence prior for a vertical in a market, or None.

    A forecasting input — expected jobs per thousand homes — deliberately
    separate from the score. Base rate is a property of the market, identical
    for every lead in it, so folding it into a lead's score would shift the
    whole grade distribution without reordering a single lead. These are priors
    from published research, not fitted values: re-fit them against outcome data
    before trusting them for revenue forecasting.
    """
    if not vertical:
        return None
    rate = _merge(region, "base_rates").get(vertical)
    return float(rate) if rate is not None else None
