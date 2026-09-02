"""World-state synthesis and prompt construction for the generate stage.

Section 4.1 of the PRD: the label exists before the text does, and the renderer
never sees it. This module produces the ``WorldState`` (ground truth physics),
hands it to ``rules_engine.label`` for the disposition, and only then builds the
render prompt — with the disposition field stripped out.

The temperature-time physics below are a reasonable synthetic approximation for
pipeline validation, not a calibrated reefer model. HITL 0 (README, "Before wave
1") is the gate that gets a domain expert to sign off before any wave counts.

Corpus scope is English-language artifacts only (CURRICULUM.md section 2) --
earlier revisions of this pipeline also generated Arabic MSA / Arabizi /
code-switched text; that axis is out of scope for the current 5,304-record
corpus. ``jurisdiction`` is a new covariate instead: each record is tagged
with one of the six GCC states (``knowledge_base.JURISDICTIONS``), balanced
the same way as ``artifact_type``. It never touches ``rules_engine.label`` --
the temperature bands are GSO/regional, not per-country -- but it flows
through to provenance and lets the guardrail pack's country overlays
(``guardrails/README.md``, "The country layer") be selected downstream by an
agent reasoning over a specific record.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import knowledge_base as kb
from .rules_engine import SPECS, ProductSpec, WorldState

INTERVAL_MIN = 15
SERIES_LEN = 96  # 24h at 15-minute intervals

FAULT_MODES = ["in_spec", "door_open", "compressor_fail", "setpoint_drift", "sensor_artifact"]


@dataclass
class GenerationRequest:
    product: str
    fault_mode: str
    language: str
    artifact_type: str
    jurisdiction: str
    is_adversarial: bool
    is_abstention: bool
    rng_seed: int


# Frozen-regime specs carry no regulatory floor (GSO 150-2 only caps at
# -18C; there is no "too cold" reject) -- ``ProductSpec.temp_min_c`` is
# ``None`` for them. Series synthesis still needs a numeric lower bound to
# generate a plausible in-spec baseline, so this is a synthetic operating
# span, not a regulatory one.
_FROZEN_OPERATING_SPAN_C = 7.0


def _operating_min_c(spec: ProductSpec) -> float:
    return spec.temp_min_c if spec.temp_min_c is not None else spec.temp_max_c - _FROZEN_OPERATING_SPAN_C


def _series_in_spec(spec: ProductSpec, rng: random.Random) -> list[float]:
    lo = _operating_min_c(spec)
    mid = (lo + spec.temp_max_c) / 2
    span = (spec.temp_max_c - lo) / 2
    return [round(mid + rng.uniform(-span * 0.6, span * 0.6), 2) for _ in range(SERIES_LEN)]


def _series_door_open(spec: ProductSpec, rng: random.Random) -> list[float]:
    series = _series_in_spec(spec, rng)
    start = rng.randrange(0, SERIES_LEN - 8)
    duration = rng.randint(2, 8)  # 30min - 2h
    ambient = rng.uniform(22, 38)
    for i in range(start, min(start + duration, SERIES_LEN)):
        series[i] = round(series[i] + (ambient - series[i]) * rng.uniform(0.4, 0.9), 2)
    return series


def _series_compressor_fail(spec: ProductSpec, rng: random.Random) -> list[float]:
    series = _series_in_spec(spec, rng)
    start = rng.randrange(0, SERIES_LEN // 2)
    drift_per_step = rng.uniform(0.3, 0.9)
    for i in range(start, SERIES_LEN):
        series[i] = round(series[i - 1] + drift_per_step if i > start else series[i], 2)
    return series


def _series_setpoint_drift(spec: ProductSpec, rng: random.Random) -> list[float]:
    series = _series_in_spec(spec, rng)
    drift_per_step = rng.uniform(0.02, 0.08)
    bias = 0.0
    for i in range(SERIES_LEN):
        bias += drift_per_step
        series[i] = round(series[i] + bias, 2)
    return series


def _series_sensor_artifact(spec: ProductSpec, rng: random.Random) -> tuple[list[float], bool]:
    series = _series_in_spec(spec, rng)
    kind = rng.choice(["stuck", "spike", "disconnect"])
    idx = rng.randrange(0, SERIES_LEN)
    if kind == "stuck":
        stuck_val = series[idx]
        for i in range(idx, min(idx + rng.randint(8, 20), SERIES_LEN)):
            series[i] = stuck_val
    elif kind == "spike":
        series[idx] = round(series[idx] + rng.choice([-1, 1]) * rng.uniform(15, 40), 2)
    else:  # disconnect -> implausible reading, e.g. sensor floor value
        series[idx] = -99.9
    return series, True


_BUILDERS = {
    "in_spec": lambda spec, rng: (_series_in_spec(spec, rng), False),
    "door_open": lambda spec, rng: (_series_door_open(spec, rng), False),
    "compressor_fail": lambda spec, rng: (_series_compressor_fail(spec, rng), False),
    "setpoint_drift": lambda spec, rng: (_series_setpoint_drift(spec, rng), False),
    "sensor_artifact": _series_sensor_artifact,
}


def synthesize(req: GenerationRequest) -> WorldState:
    rng = random.Random(req.rng_seed)
    spec = SPECS[req.product]
    readings, sensor_fault = _BUILDERS[req.fault_mode](spec, rng)

    missing: tuple[str, ...] = ()
    days_since_production = rng.randint(0, spec.shelf_life_days + 2)
    if req.is_abstention:
        # genuinely insufficient information -- never guessable from the text
        missing = rng.choice([("readings_c",), ("days_since_production",), ("interval_min",)])
        if "readings_c" in missing:
            readings = []
        if "days_since_production" in missing:
            days_since_production = None

    if req.is_adversarial and req.fault_mode != "sensor_artifact":
        # near-boundary excursion: nudge the series to sit right at the threshold
        boundary = spec.max_excursion_min // INTERVAL_MIN
        for i in range(min(boundary, len(readings))):
            if readings[i] <= spec.temp_max_c:
                readings[i] = round(spec.temp_max_c + 0.1, 2)

    return WorldState(
        product=req.product,
        readings_c=readings,
        interval_min=INTERVAL_MIN,
        ambient_c=round(random.Random(req.rng_seed + 1).uniform(24, 42), 1),
        days_since_production=days_since_production,
        sensor_fault=sensor_fault,
        peak_season=random.Random(req.rng_seed + 2).random() < 0.2,
        missing_fields=missing,
    )


def validate_jurisdiction(code: str) -> str:
    if code not in kb.JURISDICTIONS:
        raise ValueError(f"jurisdiction {code!r} not in {kb.JURISDICTIONS}")
    return code


# --------------------------------------------------------------------------- #
# prompt construction — the disposition is never present past this point
# --------------------------------------------------------------------------- #

_LANG_INSTRUCTION = {
    "en": "Write in plain English, as used in real GCC logistics and QA field reporting.",
}

_JURISDICTION_CONTEXT = {
    "AE": "The consignment is moving within the United Arab Emirates.",
    "SA": "The consignment is moving within the Kingdom of Saudi Arabia.",
    "QA": "The consignment is moving within the State of Qatar.",
    "KW": "The consignment is moving within the State of Kuwait.",
    "OM": "The consignment is moving within the Sultanate of Oman.",
    "BH": "The consignment is moving within the Kingdom of Bahrain.",
}

_ARTIFACT_INSTRUCTION = {
    "logger_csv": "Format as a raw reefer datalogger CSV dump: a couple of preamble lines "
    "(device/asset ID, product/cargo code — real logger exports carry this because "
    "the manifest ties an asset to its cargo) followed by timestamp,temp_c columns. "
    "Terse, no narrative beyond the preamble.",
    "chat_message": "Format as a short informal chat message a driver or QA officer would send, "
    "reporting what they observed.",
    "qc_form_ocr": "Format as OCR'd text from a handwritten QC intake form: field labels followed "
    "by handwritten values, include a couple of OCR artifacts (misread digits, "
    "stray characters) but keep the numbers recoverable.",
    "voice_note": "Format as a transcript of a voice note: spoken, informal, may restate a number "
    "for emphasis, minor disfluencies allowed.",
}

_RENDER_MAX_TOKENS = {
    # logger_csv reproduces all SERIES_LEN=96 rows verbatim. Confirmed against the live
    # endpoint: numeric/timestamp text tokenizes at ~1.6 chars/token (denser than prose),
    # so a full 96-row dump (~2750 chars incl. preamble) needs ~1750 completion tokens --
    # 600 and even 1600 both truncated mid-row before the extreme readings on wide-swing
    # fault modes (compressor_fail, door_open, setpoint_drift) were ever written, which
    # then failed round-trip for a reason that had nothing to do with extraction quality.
    # The other artifact types summarize a handful of numbers in prose, not enumerate 96.
    "logger_csv": 2400,
    "chat_message": 500,
    "qc_form_ocr": 900,
    "voice_note": 500,
}

_EXTRACTION_MAX_TOKENS = {
    "logger_csv": 1200,  # echoing back up to 96 floats in a JSON array
    "chat_message": 400,
    "qc_form_ocr": 700,
    "voice_note": 400,
}


def render_max_tokens(artifact_type: str) -> int:
    return _RENDER_MAX_TOKENS[artifact_type]


def extraction_max_tokens(artifact_type: str) -> int:
    return _EXTRACTION_MAX_TOKENS[artifact_type]


RENDER_FIELDS = (
    "product (string), readings_c (array of numbers), interval_min (integer), "
    "ambient_c (number), days_since_production (integer), peak_season (JSON boolean "
    'true/false, never the string "Yes"/"No"), missing_fields (JSON array of field '
    'names, e.g. [] if none are missing -- never the string "none")'
)


def render_prompt(state: WorldState, language: str, artifact_type: str, jurisdiction: str | None = None) -> str:
    """Builds the renderer prompt. Deliberately excludes disposition/label/rule_id —
    those never leave rules_engine.py. ``jurisdiction`` only adds a scene-setting
    sentence (which GCC state the consignment is moving within); it is never
    extracted back out and never affects the label -- see the module docstring."""
    visible = {
        "product": state.product,
        "readings_c": state.readings_c,
        "interval_min": state.interval_min,
        "ambient_c": state.ambient_c,
        "days_since_production": state.days_since_production,
        "peak_season": state.peak_season,
        "missing_fields": list(state.missing_fields),
    }
    for f in state.missing_fields:
        visible.pop(f, None)
    jurisdiction_line = f" {_JURISDICTION_CONTEXT[jurisdiction]}" if jurisdiction in _JURISDICTION_CONTEXT else ""
    return (
        "You are rendering a realistic GCC cold-chain field artifact from structured sensor data. "
        f"{_LANG_INSTRUCTION[language]} {_ARTIFACT_INSTRUCTION[artifact_type]}{jurisdiction_line}\n\n"
        "Do not state any conclusion, decision, or disposition — only report what was observed. "
        "Do not use the words accept/reject/hold/expedite or any synonym for a decision.\n\n"
        f"Underlying data (do not quote as JSON, weave naturally into the artifact):\n{visible}\n"
    )


_SCREENER_FEWSHOT = """EXAMPLE 1 (CONSISTENT -- describes a sharp temperature spike, no decision stated):
"Voice note: finfish seafood pallet, 15-minute intervals. Readings mostly 1 to 3°C, then a sharp
warm spike at 17.91, 19.99, 24.05°C, then back down to 1-3°C range. Ambient 30.6°C, 5 days since
production, peak season."
-> CONSISTENT. It reports an excursion and returns to range. Excursions, spikes, and out-of-band
readings are OBSERVATIONS, not decisions -- describing a bad reading is not the same as saying what
to do about it.

EXAMPLE 2 (CONSISTENT -- urgent-sounding tone, still no decision stated):
"QA note: readings climbing fast, several spikes above 25°C, this doesn't look good, ambient is very
hot today."
-> CONSISTENT. "Doesn't look good" is an observation of concern, not a stated disposition
(accept/reject/hold/expedite). Tone and urgency are not leakage.

EXAMPLE 3 (LEAKS_LABEL -- an actual decision is written):
"Batch shows sustained excursion above threshold for 3 hours. Recommend REJECT, do not release to
distribution."
-> LEAKS_LABEL. "Recommend REJECT" and "do not release" are a stated disposition."""


def screener_prompt(rendered_text: str) -> str:
    return (
        "You are a QA screener for a cold-chain dataset. Read the artifact below and decide whether "
        "it is INTERNALLY CONSISTENT (numbers, units, timeline make sense together -- a bare "
        "datalogger CSV with plausible timestamps and temperatures and no narrative text at all IS "
        "consistent, it does not need a narrative to pass), or whether it explicitly LEAKS_LABEL by "
        "stating a disposition decision (words like accept/approve/reject/discard/hold/quarantine/"
        "expedite/sell-off, or an equivalent phrase, appearing as WRITTEN TEXT in the artifact).\n\n"
        "Reporting a bad excursion, a spike, an out-of-range reading, or using urgent/concerned "
        "language is NOT leakage by itself -- that is the artifact doing its job of describing what "
        "was observed. Only answer LEAKS_LABEL if the text states what should actually be done with "
        "the shipment (reject it, hold it, sell it off, approve it), not merely that the readings "
        "were bad.\n\n"
        f"{_SCREENER_FEWSHOT}\n\n"
        "Reply with exactly one word: CONSISTENT, INCONSISTENT, or LEAKS_LABEL.\n\n"
        f"ARTIFACT:\n{rendered_text}\n"
    )


_PRODUCT_CODES = list(SPECS.keys())

EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["product", "readings_c", "interval_min"],
    "properties": {
        # product/interval_min/readings_c are required *keys* (the extractor must always take a
        # position on them) but nullable *values* -- an abstention item (WorldState.missing_fields)
        # legitimately has no ground-truth value for one of these, and a correct extraction reports
        # null rather than being forced to invent something schema-valid. Confirmed against the live
        # Azure endpoint: a bare logger_csv artifact correctly returns product=null when the artifact
        # genuinely doesn't state it.
        # `product` is a closed enum (see extraction_prompt) -- constraining it here means a
        # hallucinated product string fails schema_validity rather than silently corrupting the
        # round-trip comparison downstream.
        "product": {"enum": [*_PRODUCT_CODES, None]},
        "readings_c": {"type": ["array", "null"], "items": {"type": "number"}},
        "interval_min": {"type": ["integer", "null"]},
        "ambient_c": {"type": ["number", "null"]},
        "days_since_production": {"type": ["integer", "null"]},
        "peak_season": {"type": ["boolean", "null"]},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
    },
}


def extraction_prompt(rendered_text: str) -> str:
    """`product` is a closed enum, not free text -- a paraphrased artifact (a
    chat message, a voice note) will say "the fish shipment" or "hamour", not
    the literal code. Without being told the enum, the extractor has no way to
    map that back to `finfish_seafood`, and round-trip validation fails on
    every non-CSV artifact regardless of extraction quality. Confirmed against
    the live endpoint: Arabic chat-message artifacts correctly described the
    cargo but round-tripped to a different string every time until this enum
    was added."""
    return (
        "Extract the structured fields below from the artifact as strict JSON. If a field is not "
        "present in the text, use null. Do not infer values that are not stated or clearly implied "
        "by the artifact.\n\n"
        f"Schema fields: {RENDER_FIELDS}\n\n"
        f"`product` must be exactly one of these codes (map whatever the artifact calls the cargo, "
        f"in any language, to the matching code -- e.g. hamour/kingfish/shrimp/سمك -> "
        f"finfish_seafood): {_PRODUCT_CODES}\n\n"
        f"ARTIFACT:\n{rendered_text}\n\nReturn only the JSON object."
    )
