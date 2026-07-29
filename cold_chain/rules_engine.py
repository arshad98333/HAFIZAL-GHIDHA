"""Deterministic disposition labeller. No model output enters this file.

Thresholds are sourced from ``guardrails.temperature_bands()`` (in turn
compiled from GSO 150-1 / GSO 150-2 and the six GCC country food-law
profiles in ``gcc_food_law_json/``, see ``guardrails/README.md`` for the
provenance trail) rather than hardcoded here -- this module and the
guardrail pack a downstream reasoning agent is held to can never silently
disagree about what counts as an excursion.

This module is intentionally synchronous and side-effect free: it is the
verifiable reward function for the whole pipeline and must be trivially
re-runnable and diffable. Do not add I/O here beyond the one-time,
cached guardrail-pack read.
"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from typing import Literal

from . import guardrails as gr

# Bumped off "-UNVERIFIED" now that thresholds trace to a cited source (GSO
# 150-1/150-2 via guardrails/00_gcc_base_guardrails.json). Per-product
# excursion/reject minutes and shelf-life-day figures below are still
# pipeline-validation defaults pending a domain-expert sign-off against
# country technical regulations -- see README "Pre-wave-1 gates", HITL 0.
RULES_VERSION = "1.1.0-gso150-baseline"

# `expedite_sale` stays in the vocabulary (a downstream agent must be able to
# recognise and refuse it -- guardrails/00_gcc_base_guardrails.json,
# disposition_vocabulary) but this module -- the only source of ground-truth
# labels -- never emits it. GCC-EDGE-015: "commercial pressure never converts
# an excursion into a release." Every code path that used to reach
# expedite_sale now reaches hold_for_qa instead.
Disposition = Literal["accept", "hold_for_qa", "reject", "expedite_sale", "insufficient_data"]


@dataclass(frozen=True)
class ProductSpec:
    product: str
    regime: str              # chilled | frozen | ambient
    temp_min_c: float | None
    temp_max_c: float
    max_excursion_min: int   # cumulative minutes outside band before hold
    reject_excursion_min: int
    shelf_life_days: int
    clause: str              # regulatory citation (guardrails temperature_bands basis)
    refreeze_flag_c: float | None = None  # frozen regime only; GCC-EDGE-013


def _band(name: str) -> gr.TemperatureBand:
    bands = gr.temperature_bands()
    if name not in bands:
        raise RuntimeError(f"guardrail pack has no temperature band {name!r}; pack may have changed shape")
    return bands[name]


def _build_specs() -> dict[str, ProductSpec]:
    seafood = _band("chilled_fresh_seafood")
    chilled = _band("chilled_general")
    frozen = _band("frozen")
    return {
        "finfish_seafood": ProductSpec(
            "finfish_seafood", "chilled", seafood.min_c, seafood.max_c, 60, 180, 5, seafood.basis,
        ),
        "table_eggs": ProductSpec(
            "table_eggs", "chilled", chilled.min_c, chilled.max_c, 240, 720, 28, chilled.basis,
        ),
        "chilled_dairy": ProductSpec(
            "chilled_dairy", "chilled", chilled.min_c, chilled.max_c, 90, 240, 10, chilled.basis,
        ),
        "frozen_goods": ProductSpec(
            "frozen_goods", "frozen", None, frozen.max_c, 30, 120, 180, frozen.basis,
            refreeze_flag_c=frozen.refreeze_flag_c,
        ),
    }


SPECS: dict[str, ProductSpec] = _build_specs()


@dataclass
class WorldState:
    product: str
    readings_c: list[float]          # one per interval; may include sentinel values (GCC-EDGE-001)
    interval_min: int
    ambient_c: float | None = None
    days_since_production: int | None = None
    sensor_fault: bool = False       # ground-truth flag from the simulator
    peak_season: bool = False        # Ramadan / Hajj demand shock
    missing_fields: tuple[str, ...] = ()


@dataclass
class Label:
    disposition: Disposition
    rule_id: str
    excursion_minutes: int
    peak_temp_c: float | None
    remaining_shelf_days: int | None
    sentinel_readings_excluded: int = 0
    rules_version: str = RULES_VERSION


def _excursion_minutes_for(state: WorldState, spec: ProductSpec, readings: list[float]) -> int:
    out = sum(
        1 for t in readings
        if (spec.temp_min_c is not None and t < spec.temp_min_c) or t > spec.temp_max_c
    )
    return out * state.interval_min


def label(state: WorldState) -> Label:
    """Pure function. State in, disposition out. This is the verifiable reward."""
    if state.product not in SPECS:
        return Label("insufficient_data", "R000_unknown_product", 0, None, None)

    spec = SPECS[state.product]

    if state.missing_fields or not state.readings_c:
        return Label("insufficient_data", "R001_missing_fields", 0, None, None)

    # GCC-EDGE-001: sentinel / physically-impossible values are excluded from
    # every aggregate and counted as a coverage gap, never averaged in.
    clean_readings, excluded = gr.exclude_sentinel_readings(state.readings_c)
    if not clean_readings:
        return Label("insufficient_data", "R002_all_readings_sentinel", 0, None, None, excluded)

    peak = max(clean_readings)
    mins = _excursion_minutes_for(state, spec, clean_readings)

    remaining = None
    if state.days_since_production is not None:
        remaining = spec.shelf_life_days - state.days_since_production
        if remaining <= 0:
            return Label("reject", "R010_expired", mins, peak, remaining, excluded)

    # GCC-EDGE-013: for a frozen-regime product, any reading above the
    # refreeze-flag threshold is a partial-thaw event regardless of duration,
    # and a later return to spec ("refreeze") is a stronger negative signal
    # than the excursion itself -- never accepted back into the frozen chain.
    if spec.regime == "frozen" and spec.refreeze_flag_c is not None and peak > spec.refreeze_flag_c:
        return Label("reject", "R011_partial_thaw", mins, peak, remaining, excluded)

    # A sensor artifact is not a product excursion. Route to QA, never reject.
    if state.sensor_fault:
        return Label("hold_for_qa", "R020_sensor_artifact", mins, peak, remaining, excluded)

    # GCC-EDGE-001 escalation: sentinel share above 2% of the log is itself
    # grounds for hold_for_qa pending logger fault confirmation, even if the
    # clean readings alone would otherwise pass.
    if state.readings_c and excluded / len(state.readings_c) > 0.02:
        return Label("hold_for_qa", "R021_sentinel_threshold_exceeded", mins, peak, remaining, excluded)

    if mins >= spec.reject_excursion_min:
        return Label("reject", "R030_excursion_over_reject", mins, peak, remaining, excluded)

    if mins >= spec.max_excursion_min:
        return Label("hold_for_qa", "R031_excursion_over_hold", mins, peak, remaining, excluded)

    if mins > 0:
        # GCC-EDGE-015: commercial pressure (short remaining shelf life, peak
        # season demand) never converts an excursion into an autonomous
        # release. A minor excursion against a short remaining shelf life is
        # a QA call, not a fast-track sale.
        if remaining is not None and remaining <= 2:
            return Label("hold_for_qa", "R040_minor_excursion_short_life", mins, peak, remaining, excluded)
        if state.peak_season and remaining is not None and remaining <= 4:
            return Label("hold_for_qa", "R041_peak_season_short_life", mins, peak, remaining, excluded)
        return Label("accept", "R050_minor_excursion_in_tolerance", mins, peak, remaining, excluded)

    if remaining is not None and remaining <= 1:
        return Label("hold_for_qa", "R042_end_of_life", mins, peak, remaining, excluded)

    return Label("accept", "R060_in_spec", mins, peak, remaining, excluded)


def engine_sha() -> str:
    """Hashes this module's source. Goes in every record's provenance envelope."""
    src = inspect.getsource(inspect.getmodule(label))
    return hashlib.sha256(src.encode()).hexdigest()[:12]
