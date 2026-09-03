"""Orchestrates a deterministic cold-chain record walkthrough for the UI demo."""

from __future__ import annotations

from cold_chain.api.schemas import SimulateRequest, SimulateResponse, SimulateStep
from cold_chain.domain import guardrails as gr
from cold_chain.domain.rules_engine import SPECS, label
from cold_chain.domain.simulate import (
    FAULT_MODES,
    GenerationRequest,
    render_prompt,
    synthesize,
    validate_jurisdiction,
)

_ARTIFACT_SAMPLE_LINES = 24


def _template_artifact(
    state,
    artifact_type: str,
    jurisdiction: str,
) -> str:
    peak = max(state.readings_c) if state.readings_c else None
    low = min(state.readings_c) if state.readings_c else None
    ambient = state.ambient_c
    days = state.days_since_production

    if artifact_type == "logger_csv":
        lines = [
            f"# device=REEFER-{jurisdiction}-7731 product={state.product}",
            "timestamp,temp_c",
        ]
        for i, temp in enumerate(state.readings_c[:_ARTIFACT_SAMPLE_LINES]):
            hh = (i * state.interval_min) // 60
            mm = (i * state.interval_min) % 60
            lines.append(f"2025-06-15T{hh:02d}:{mm:02d}:00,{temp}")
        if len(state.readings_c) > _ARTIFACT_SAMPLE_LINES:
            lines.append(f"# ... {len(state.readings_c) - _ARTIFACT_SAMPLE_LINES} more rows")
        return "\n".join(lines)

    if artifact_type == "chat_message":
        return (
            f"QA note ({jurisdiction}): {state.product} pallet — readings mostly {low}–{peak}°C, "
            f"15-min intervals. Ambient ~{ambient}°C, {days} days since production."
        )

    if artifact_type == "qc_form_ocr":
        return (
            f"Product: {state.product}\n"
            f"Peak temp: {peak} C  (OCR: {str(peak).replace('.', ',')})\n"
            f"Ambient: {ambient} C\n"
            f"Days since prod: {days}\n"
            f"Interval: {state.interval_min} min"
        )

    return (
        f"Voice note: {state.product} shipment in {jurisdiction}. "
        f"Logger shows {low} to {peak} degrees, ambient {ambient}, day {days}."
    )


def run_simulation(req: SimulateRequest) -> SimulateResponse:
    product = req.product
    fault_mode = req.fault_mode
    jurisdiction = validate_jurisdiction(req.jurisdiction)
    artifact_type = req.artifact_type
    seed = req.seed

    if product not in SPECS:
        raise ValueError(f"unknown product {product!r}")
    if fault_mode not in FAULT_MODES:
        raise ValueError(f"unknown fault_mode {fault_mode!r}")

    gen_req = GenerationRequest(
        product=product,
        fault_mode=fault_mode,
        language="en",
        artifact_type=artifact_type,
        jurisdiction=jurisdiction,
        is_adversarial=req.is_adversarial,
        is_abstention=req.is_abstention,
        rng_seed=seed,
    )
    state = synthesize(gen_req)
    spec = SPECS[product]
    disposition = label(state)
    prompt = render_prompt(state, "en", artifact_type, jurisdiction, style_seed=seed % 5)
    artifact_preview = _template_artifact(state, artifact_type, jurisdiction)
    violations = gr.check_artifact_text(artifact_preview, artifact_type)
    violation_codes = [v.code for v in violations]

    steps = [
        SimulateStep(
            id="synthesize",
            title="Synthesize world state",
            detail=(
                f"Generated {len(state.readings_c)} temperature readings "
                f"({fault_mode}) for {product} in {jurisdiction}."
            ),
            status="done",
        ),
        SimulateStep(
            id="label",
            title="Rules engine labels (before any LLM)",
            detail=(
                f"Disposition: {disposition.disposition} via {disposition.rule_id}. "
                f"Excursion {disposition.excursion_minutes} min, peak {disposition.peak_temp_c}°C."
            ),
            status="done",
        ),
        SimulateStep(
            id="render",
            title="Build render prompt (LLM would run here)",
            detail="The disposition is stripped from the prompt — the renderer never sees the label.",
            status="done",
        ),
        SimulateStep(
            id="artifact",
            title="Field artifact preview",
            detail="Template preview of what the LLM would produce (demo only, not model output).",
            status="done",
        ),
        SimulateStep(
            id="guardrails",
            title="Guardrail scan",
            detail=(f"{len(violations)} violation(s): {', '.join(violation_codes) or 'none'}"),
            status="done" if not violations else "warn",
        ),
    ]

    band_lo = spec.temp_min_c
    band_hi = spec.temp_max_c

    return SimulateResponse(
        product=product,
        fault_mode=fault_mode,
        jurisdiction=jurisdiction,
        artifact_type=artifact_type,
        seed=seed,
        readings_c=state.readings_c,
        interval_min=state.interval_min,
        ambient_c=state.ambient_c,
        days_since_production=state.days_since_production,
        sensor_fault=state.sensor_fault,
        peak_season=state.peak_season,
        missing_fields=list(state.missing_fields),
        temp_band_min_c=band_lo,
        temp_band_max_c=band_hi,
        disposition=disposition.disposition,
        rule_id=disposition.rule_id,
        excursion_minutes=disposition.excursion_minutes,
        peak_temp_c=disposition.peak_temp_c,
        remaining_shelf_days=disposition.remaining_shelf_days,
        render_prompt=prompt,
        artifact_preview=artifact_preview,
        guardrail_violations=violation_codes,
        steps=steps,
        spec_regime=spec.regime,
        spec_clause=spec.clause,
    )
