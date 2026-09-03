"""Random truck-scenario generation and grounded narration for LiveOps
(``/liveops/scenario``, ``/liveops/narrate``).

LiveOps answers a different question than the Ask chat
(``compliance_qa.py``): not "is this specific documented reading a
violation" but "here is a random live-feeling truck situation -- narrate
what happened, what the problem is, and what GSO-aligned action to take."
The physics and disposition are never LLM-generated here either -- this
module reuses the exact same deterministic pipeline the rest of the repo
relies on (``simulate.synthesize`` -> ``rules_engine.label``, the same two
calls ``api/simulation.py`` makes for the Simulation page) to build the
scenario's ground truth *before* any model call happens, then hands K2 the
scenario facts as given data to narrate, not something to infer or invent.

Scenario generation is intentionally behind a small interface
(``ScenarioSource``) rather than a bare function. Today the only
implementation is synthetic/random (``RandomScenarioSource``); the shape
exists so that a future real-time feed -- Azure IoT Hub device telemetry,
most plausibly -- can be swapped in later as a second implementation without
touching the narration side at all. That integration is NOT built here: it
would need a real IoT Hub connection string, device twins, and something to
test it against, none of which exist in this environment. Faking that
wiring against no real backend would be worse than not having it -- see
``AzureIoTHubScenarioSource`` below, which documents the shape and raises
rather than pretending to work.
"""

from __future__ import annotations

import random
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .catalog import ARTIFACTS, FAULT_MODES, JURISDICTIONS, PRODUCTS
from .rules_engine import SPECS, label
from .simulate import GenerationRequest, synthesize

# -- scenario ----------------------------------------------------------- #


@dataclass
class TruckScenario:
    scenario_id: str
    source: str  # "synthetic_random" today; "azure_iot_hub" once/if that source ships
    truck_id: str
    product: str
    jurisdiction: str
    fault_mode: str
    artifact_type: str
    seed: int
    readings_c: list[float]
    interval_min: int
    ambient_c: float | None
    days_since_production: int | None
    sensor_fault: bool
    peak_season: bool
    disposition: str
    rule_id: str
    excursion_minutes: int
    peak_temp_c: float | None
    remaining_shelf_days: int | None
    temp_band_min_c: float | None
    temp_band_max_c: float
    spec_regime: str
    spec_clause: str
    narrative_opening: str  # short, officer-facing plain-language framing of the scenario
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "source": self.source,
            "truck_id": self.truck_id,
            "product": self.product,
            "jurisdiction": self.jurisdiction,
            "fault_mode": self.fault_mode,
            "artifact_type": self.artifact_type,
            "seed": self.seed,
            "readings_c": self.readings_c,
            "interval_min": self.interval_min,
            "ambient_c": self.ambient_c,
            "days_since_production": self.days_since_production,
            "sensor_fault": self.sensor_fault,
            "peak_season": self.peak_season,
            "disposition": self.disposition,
            "rule_id": self.rule_id,
            "excursion_minutes": self.excursion_minutes,
            "peak_temp_c": self.peak_temp_c,
            "remaining_shelf_days": self.remaining_shelf_days,
            "temp_band_min_c": self.temp_band_min_c,
            "temp_band_max_c": self.temp_band_max_c,
            "spec_regime": self.spec_regime,
            "spec_clause": self.spec_clause,
            "narrative_opening": self.narrative_opening,
            "generated_at": self.generated_at,
        }


def _truck_id(rng: random.Random, jurisdiction: str) -> str:
    return f"REEFER-{jurisdiction}-{rng.randint(1000, 9999)}"


def _narrative_opening(truck_id: str, product: str, jurisdiction: str, fault_mode: str, ambient_c: float | None) -> str:
    fault_phrase = {
        "in_spec": "running normally, no fault reported",
        "door_open": "a prolonged door-open event flagged by the door sensor",
        "compressor_fail": "a suspected compressor failure",
        "setpoint_drift": "a gradual setpoint drift away from the target band",
        "sensor_artifact": "a data logger anomaly that may or may not reflect real conditions",
    }.get(fault_mode, fault_mode)
    ambient_phrase = f" Ambient conditions are around {ambient_c}°C." if ambient_c is not None else ""
    return (
        f"Truck {truck_id} is in transit through {jurisdiction} carrying a {product.replace('_', ' ')} "
        f"consignment. The telemetry feed shows {fault_phrase}.{ambient_phrase}"
    )


class ScenarioSource(ABC):
    """Anything that can hand LiveOps a :class:`TruckScenario`. Kept
    deliberately minimal (one method) so a real-time source can be dropped
    in later without any change to the narration code, which only ever
    depends on this interface."""

    @abstractmethod
    def next_scenario(self) -> TruckScenario:
        raise NotImplementedError


class RandomScenarioSource(ScenarioSource):
    """Synthesizes a random truck scenario using the same deterministic
    physics + rules-engine pipeline the Simulation page uses
    (``api/simulation.py``), just with every input randomized instead of
    operator-chosen. This is the only scenario source that actually exists
    today; LiveOps is otherwise identical in spirit to the Simulation page,
    just narrated as a live event instead of shown as a static preview."""

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()

    def next_scenario(self) -> TruckScenario:
        rng = self._rng
        product = rng.choice(PRODUCTS)
        fault_mode = rng.choice(FAULT_MODES)
        jurisdiction = rng.choice(JURISDICTIONS)
        artifact_type = rng.choice(ARTIFACTS)
        seed = rng.randint(0, 2**31 - 1)

        gen_req = GenerationRequest(
            product=product,
            fault_mode=fault_mode,
            language="en",
            artifact_type=artifact_type,
            jurisdiction=jurisdiction,
            is_adversarial=False,
            is_abstention=False,
            rng_seed=seed,
        )
        state = synthesize(gen_req)
        spec = SPECS[product]
        disposition = label(state)
        truck_id = _truck_id(rng, jurisdiction)

        return TruckScenario(
            scenario_id=str(uuid.uuid4()),
            source="synthetic_random",
            truck_id=truck_id,
            product=product,
            jurisdiction=jurisdiction,
            fault_mode=fault_mode,
            artifact_type=artifact_type,
            seed=seed,
            readings_c=state.readings_c,
            interval_min=state.interval_min,
            ambient_c=state.ambient_c,
            days_since_production=state.days_since_production,
            sensor_fault=state.sensor_fault,
            peak_season=state.peak_season,
            disposition=disposition.disposition,
            rule_id=disposition.rule_id,
            excursion_minutes=disposition.excursion_minutes,
            peak_temp_c=disposition.peak_temp_c,
            remaining_shelf_days=disposition.remaining_shelf_days,
            temp_band_min_c=spec.temp_min_c,
            temp_band_max_c=spec.temp_max_c,
            spec_regime=spec.regime,
            spec_clause=spec.clause,
            narrative_opening=_narrative_opening(truck_id, product, jurisdiction, fault_mode, state.ambient_c),
        )


class AzureIoTHubScenarioSource(ScenarioSource):
    """NOT IMPLEMENTED. Placeholder documenting the intended shape of a real
    Azure IoT Hub-backed scenario feed, so this integration point is
    discoverable without being faked.

    A real implementation would: (1) hold an IoT Hub connection string /
    device-twin query, most likely via ``azure-iot-hub`` +
    ``azure-eventhub`` reading the Hub's built-in Event Hub-compatible
    endpoint; (2) map each device's reported telemetry (temperature series,
    door/compressor signals, device id) onto the same ``TruckScenario``
    fields ``RandomScenarioSource`` populates, so narration code needs zero
    changes; (3) still run the reading series through
    ``rules_engine.label`` for the disposition -- a live feed changes where
    the numbers come from, never who is allowed to compute the disposition.

    This is deliberately left unimplemented rather than stubbed with fake
    Azure SDK calls: there is no IoT Hub connection string, device registry,
    or live telemetry to test against in this environment, and untested
    integration code that only *looks* wired up is worse than an honest
    "not built yet."
    """

    def __init__(self, connection_string: str | None = None):
        self._connection_string = connection_string

    def next_scenario(self) -> TruckScenario:
        raise NotImplementedError(
            "Azure IoT Hub live scenario feed is not implemented in this deployment. "
            "Configure a real IoT Hub connection string and device registry, then "
            "implement AzureIoTHubScenarioSource.next_scenario() to map device "
            "telemetry onto TruckScenario fields (see class docstring)."
        )


def generate_random_scenario(seed: int | None = None) -> TruckScenario:
    """Convenience entry point for the API route: one random scenario from
    the only scenario source that actually exists today."""
    rng = random.Random(seed) if seed is not None else random.Random()
    return RandomScenarioSource(rng).next_scenario()


# -- 3-step grounded narration ------------------------------------------- #

STEP_WHAT_HAPPENED = "what_happened"
STEP_THE_PROBLEM = "the_problem"
STEP_GSO_SOLUTION = "gso_solution"

LIVEOPS_STEPS: tuple[tuple[str, str], ...] = (
    (STEP_WHAT_HAPPENED, "What Happened"),
    (STEP_THE_PROBLEM, "The Problem"),
    (STEP_GSO_SOLUTION, "GSO-Aligned Solution"),
)

_LIVEOPS_SYSTEM = (
    "You are a GCC cold-chain compliance reasoning assistant narrating a live "
    "truck scenario for a food-safety compliance officer (GSO-aligned, "
    "covering Saudi Arabia, UAE, Qatar, Bahrain, Kuwait, and Oman). You are "
    "one step in a 3-step narration; only produce this step's output, not "
    "the others. Hard rules for every step: (1) The SCENARIO FACTS block is "
    "ground truth from a deterministic rules engine, already computed -- "
    "never contradict, re-derive, or second-guess the disposition or rule ID "
    "given there. (2) You may cite ONLY rule IDs, GSO clause numbers, and "
    "jurisdiction/authority names given to you in the CONTEXT block; if "
    "nothing in CONTEXT supports a claim, say so plainly instead of "
    "inventing a citation. (3) Never recommend or imply 'expedite_sale' or "
    "any variant of releasing product under commercial pressure -- "
    "GCC-EDGE-015: commercial pressure never converts an excursion into a "
    "release. (4) This is decision support for a human officer, not an "
    "automated release/reject action and not legal advice."
)


def scenario_facts_block(scenario: TruckScenario) -> str:
    """Deterministic ground-truth facts about the scenario, handed to the
    model as given data -- exactly the same "never let the model
    re-derive the label" discipline as the rest of this repository."""
    band = (
        f"{scenario.temp_band_min_c}–{scenario.temp_band_max_c}°C"
        if scenario.temp_band_min_c is not None
        else f"≤{scenario.temp_band_max_c}°C"
    )
    peak = f"{scenario.peak_temp_c}°C" if scenario.peak_temp_c is not None else "n/a"
    shelf = f"{scenario.remaining_shelf_days} days" if scenario.remaining_shelf_days is not None else "n/a"
    return (
        f"Truck: {scenario.truck_id} ({scenario.source})\n"
        f"Product: {scenario.product} ({scenario.spec_regime}); band {band}; basis: {scenario.spec_clause}\n"
        f"Jurisdiction: {scenario.jurisdiction}\n"
        f"Fault mode reported by telemetry: {scenario.fault_mode}\n"
        f"Ambient: {scenario.ambient_c}°C; days since production: {scenario.days_since_production}\n"
        f"Peak reading: {peak}; excursion: {scenario.excursion_minutes} cumulative minutes out of band\n"
        f"DISPOSITION (deterministic, already decided -- narrate it, do not re-derive it): "
        f"{scenario.disposition} via {scenario.rule_id}\n"
        f"Remaining shelf life if released: {shelf}"
    )


def scenario_question_text(scenario: TruckScenario, officer_note: str | None) -> str:
    """Turns a scenario into free-text suitable for ``compliance_qa.retrieve()``
    so LiveOps reuses exactly the same keyword/jurisdiction/product retrieval
    as the Ask chat -- no separate retrieval logic to keep in sync."""
    text = (
        f"{scenario.product} shipment, fault mode {scenario.fault_mode}, "
        f"jurisdiction {scenario.jurisdiction}, disposition {scenario.disposition} "
        f"under {scenario.rule_id}, excursion {scenario.excursion_minutes} minutes."
    )
    if officer_note:
        text += f" Officer note: {officer_note}"
    return text


def build_narration_messages(
    step_id: str,
    *,
    scenario: TruckScenario,
    context_block: str,
    officer_note: str | None,
    prior_outputs: dict[str, str],
) -> list[dict[str, str]]:
    """Mirrors ``compliance_qa.build_step_messages`` -- each step is a fresh,
    independently-run K2 call conditioned on the previous step's real
    output, not a single completion split into sections."""
    history = "\n\n".join(
        f"--- {title} (already completed) ---\n{prior_outputs[sid]}"
        for sid, title in LIVEOPS_STEPS
        if sid in prior_outputs
    )
    officer_block = f"\n\nOFFICER NOTE (optional, free text from the compliance officer):\n{officer_note}" if officer_note else ""
    header = (
        f"SCENARIO FACTS:\n{scenario_facts_block(scenario)}"
        f"{officer_block}\n\nCONTEXT (law/guardrail data you may cite from):\n{context_block}"
    )
    if history:
        header += f"\n\n{history}"

    if step_id == STEP_WHAT_HAPPENED:
        instruction = (
            "STEP 1 — What Happened. In plain, officer-facing language, "
            "narrate what the telemetry shows for this truck: the fault "
            "mode, the temperature behaviour, and the operational picture. "
            "State only what SCENARIO FACTS actually supports -- do not "
            "invent details the facts do not contain. Keep it to a few "
            "sentences; this is scene-setting, not the verdict."
        )
    elif step_id == STEP_THE_PROBLEM:
        instruction = (
            "STEP 2 — The Problem. Explain precisely why this scenario is or "
            "is not a compliance problem: which threshold(s) from CONTEXT "
            "and SCENARIO FACTS are implicated, how the excursion compares "
            "to the hold/reject thresholds for this product, and what "
            "specific GSO clause or guardrail rule governs the situation. "
            "If the officer note raises a claim (e.g. an exemption) that "
            "CONTEXT does not support, say so explicitly here."
        )
    else:
        instruction = (
            "STEP 3 — GSO-Aligned Solution. Give the officer a direct, "
            "actionable recommendation consistent with the DISPOSITION "
            "already decided in SCENARIO FACTS (do not contradict it): what "
            "to do with the consignment, what to document, and who to "
            "escalate to if applicable. Cite the specific rule ID(s) and/or "
            "GSO clause(s) relied on. Close with the standard disclaimer "
            "that this is decision support for a human officer, not an "
            "automated release/reject action and not legal advice."
        )

    return [
        {"role": "system", "content": _LIVEOPS_SYSTEM},
        {"role": "user", "content": f"{header}\n\n{instruction}"},
    ]
