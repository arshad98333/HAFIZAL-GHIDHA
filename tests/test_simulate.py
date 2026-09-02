from __future__ import annotations

import pytest

from cold_chain import simulate as sim
from cold_chain.rules_engine import SPECS


def _req(product="finfish_seafood", fault_mode="in_spec", jurisdiction="AE", **kw):
    defaults = dict(
        language="en",
        artifact_type="chat_message",
        is_adversarial=False,
        is_abstention=False,
        rng_seed=42,
    )
    defaults.update(kw)
    return sim.GenerationRequest(product=product, fault_mode=fault_mode, jurisdiction=jurisdiction, **defaults)


def test_languages_only_english():
    assert set(sim._LANG_INSTRUCTION) == {"en"}


@pytest.mark.parametrize("fault_mode", sim.FAULT_MODES)
def test_synthesize_produces_full_length_series(fault_mode):
    state = sim.synthesize(_req(fault_mode=fault_mode))
    assert len(state.readings_c) == sim.SERIES_LEN


@pytest.mark.parametrize("product", list(SPECS))
def test_synthesize_in_spec_stays_near_band_for_every_product(product):
    state = sim.synthesize(_req(product=product, fault_mode="in_spec"))
    spec = SPECS[product]
    lo = sim._operating_min_c(spec)
    # generous slack: this only checks the synthesizer produced something in the
    # right neighbourhood, not that it's a calibrated reefer model (see simulate.py docstring)
    assert all(lo - 5 <= r <= spec.temp_max_c + 5 for r in state.readings_c)


def test_abstention_request_drops_a_field():
    state = sim.synthesize(_req(fault_mode="in_spec", is_abstention=True))
    assert state.missing_fields
    if "readings_c" in state.missing_fields:
        assert state.readings_c == []
    if "days_since_production" in state.missing_fields:
        assert state.days_since_production is None


def test_validate_jurisdiction_accepts_known_codes():
    for code in ("AE", "SA", "QA", "KW", "OM", "BH"):
        assert sim.validate_jurisdiction(code) == code


def test_validate_jurisdiction_rejects_unknown():
    with pytest.raises(ValueError):
        sim.validate_jurisdiction("ZZ")


def test_render_prompt_never_contains_disposition_field():
    state = sim.synthesize(_req())
    prompt = sim.render_prompt(state, "en", "chat_message", "AE")
    # WorldState has no disposition attribute at all -- structurally impossible
    # to leak it into the prompt. This just documents that guarantee.
    assert not hasattr(state, "disposition")
    assert "United Arab Emirates" in prompt


def test_render_prompt_handles_missing_jurisdiction_gracefully():
    state = sim.synthesize(_req())
    prompt = sim.render_prompt(state, "en", "chat_message", jurisdiction=None)
    assert "You are rendering" in prompt
