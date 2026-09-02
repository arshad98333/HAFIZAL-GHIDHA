from __future__ import annotations

import itertools

import pytest

from cold_chain import guardrails as gr
from cold_chain import rules_engine as re_


def test_specs_match_guardrail_bands():
    bands = gr.temperature_bands()
    seafood = re_.SPECS["finfish_seafood"]
    assert seafood.temp_min_c == bands["chilled_fresh_seafood"].min_c
    assert seafood.temp_max_c == bands["chilled_fresh_seafood"].max_c

    frozen = re_.SPECS["frozen_goods"]
    assert frozen.temp_min_c is None
    assert frozen.temp_max_c == bands["frozen"].max_c
    assert frozen.refreeze_flag_c == bands["frozen"].refreeze_flag_c


def test_unknown_product_is_insufficient_data():
    state = re_.WorldState(product="unobtanium", readings_c=[1.0], interval_min=15)
    result = re_.label(state)
    assert result.disposition == "insufficient_data"
    assert result.rule_id == "R000_unknown_product"


def test_missing_fields_is_insufficient_data():
    state = re_.WorldState(product="finfish_seafood", readings_c=[], interval_min=15, missing_fields=("readings_c",))
    result = re_.label(state)
    assert result.disposition == "insufficient_data"


def test_sentinel_reading_excluded_and_flagged():
    # One real sentinel among otherwise in-spec readings -- excluded from the
    # aggregate, and the record halts as hold_for_qa per GCC-EDGE-001's escalation.
    state = re_.WorldState(
        product="finfish_seafood",
        readings_c=[1.0, 2.0, -99.9],
        interval_min=15,
        days_since_production=0,
    )
    result = re_.label(state)
    assert result.sentinel_readings_excluded == 1
    assert result.disposition == "hold_for_qa"
    assert result.rule_id == "R021_sentinel_threshold_exceeded"


def test_literal_zero_is_not_treated_as_sentinel():
    # 0.0C is a legitimate in-band reading for chilled seafood (target 0-2C) --
    # must not be excluded as a sentinel even though it's in the raw sentinel_set.
    state = re_.WorldState(
        product="finfish_seafood",
        readings_c=[0.0, 1.0, 2.0],
        interval_min=15,
        days_since_production=0,
    )
    result = re_.label(state)
    assert result.sentinel_readings_excluded == 0
    assert result.disposition == "accept"


def test_frozen_partial_thaw_is_rejected_regardless_of_duration():
    # Single reading above the refreeze-flag threshold (-12C), even briefly,
    # even with a return to spec elsewhere in the log -- GCC-EDGE-013.
    readings = [-20.0] * 90 + [-10.0] + [-19.0] * 5
    state = re_.WorldState(product="frozen_goods", readings_c=readings, interval_min=15, days_since_production=1)
    result = re_.label(state)
    assert result.disposition == "reject"
    assert result.rule_id == "R011_partial_thaw"


def test_frozen_in_spec_is_accepted():
    state = re_.WorldState(product="frozen_goods", readings_c=[-20.0] * 20, interval_min=15, days_since_production=5)
    result = re_.label(state)
    assert result.disposition == "accept"


def test_expired_product_is_rejected():
    state = re_.WorldState(product="finfish_seafood", readings_c=[1.0], interval_min=15, days_since_production=999)
    result = re_.label(state)
    assert result.disposition == "reject"
    assert result.rule_id == "R010_expired"


def test_sensor_fault_never_rejects():
    state = re_.WorldState(
        product="finfish_seafood",
        readings_c=[1.0, 2.0],
        interval_min=15,
        days_since_production=0,
        sensor_fault=True,
    )
    result = re_.label(state)
    assert result.disposition == "hold_for_qa"
    assert result.rule_id == "R020_sensor_artifact"


PRODUCTS = list(re_.SPECS)


@pytest.mark.parametrize(
    "product,peak,days,peak_season,sensor_fault",
    list(itertools.product(PRODUCTS, [0.0, 3.0, 30.0], [0, 1, 2, 4, 10], [False, True], [False, True])),
)
def test_expedite_sale_never_emitted(product, peak, days, peak_season, sensor_fault):
    """GCC-EDGE-015: commercial pressure never converts an excursion into an
    autonomous release. Fuzz across every code path that historically could
    reach expedite_sale (short remaining shelf life, peak season) and assert
    the rule engine -- the only source of ground truth -- never emits it."""
    spec = re_.SPECS[product]
    readings = (
        [spec.temp_max_c + peak]
        if peak
        else [(spec.temp_min_c if spec.temp_min_c is not None else spec.temp_max_c - 5) + 0.1]
    )
    state = re_.WorldState(
        product=product,
        readings_c=readings,
        interval_min=15,
        days_since_production=days,
        peak_season=peak_season,
        sensor_fault=sensor_fault,
    )
    result = re_.label(state)
    assert result.disposition != "expedite_sale"
    assert result.disposition in ("accept", "hold_for_qa", "reject", "insufficient_data")


def test_engine_sha_is_deterministic():
    assert re_.engine_sha() == re_.engine_sha()
    assert len(re_.engine_sha()) == 12
