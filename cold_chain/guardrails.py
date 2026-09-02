"""Loader and deterministic checks for the GCC cold-chain guardrail pack
(``guardrails/``).

The pack is 85 rules (25 base + 10 per country x 6 countries) written for an
*agent's* disposition reasoning, mined from a real failure sample
(``wave_9001.jsonl``) and the six country food-law profiles in
``gcc_food_law_json/``. Most of the 85 rules describe things a downstream
reasoning agent must or must not do and are not mechanically checkable here
-- they belong in the student model's system prompt / eval rubric, not in
Python. This module implements the subset that *is* mechanically checkable
against a candidate training record, and uses it two ways:

1. ``rules_engine.py`` imports the physical constants (temperature bands,
   sentinel-value set, the frozen refreeze threshold) so the deterministic
   labeller and the guardrail pack can never silently disagree about what
   counts as an excursion.
2. ``gates.py`` / the runner's generation loop call ``check_artifact_text``
   as a second, independent line of defence on the rendered artifact text --
   catching metadata leakage or a disposition word slipping through even if
   the LLM screener (``simulate.screener_prompt``) missed it.

See ``guardrails/README.md`` for the full rule catalogue and the provenance
of every rule ("what wave_9001 actually taught the pack").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "guardrails"

BASE_FILE = "00_gcc_base_guardrails.json"

# ISO 3166-1 alpha-2 -> overlay filename, same jurisdiction codes as knowledge_base.py
COUNTRY_FILES: dict[str, str] = {
    "AE": "01_uae_cold_chain_guardrails.json",
    "SA": "02_saudi_arabia_cold_chain_guardrails.json",
    "QA": "03_qatar_cold_chain_guardrails.json",
    "KW": "04_kuwait_cold_chain_guardrails.json",
    "OM": "05_oman_cold_chain_guardrails.json",
    "BH": "06_bahrain_cold_chain_guardrails.json",
}


class GuardrailError(RuntimeError):
    """Missing or malformed guardrail pack -- a startup-time configuration
    error, not a per-record failure."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GuardrailError(f"guardrail pack file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GuardrailError(f"guardrail pack file is not valid JSON: {path} ({exc})") from exc


@lru_cache(maxsize=1)
def base_pack(dir_: Path = DEFAULT_DIR) -> dict[str, Any]:
    return _load_json(dir_ / BASE_FILE)


@lru_cache(maxsize=8)
def country_pack(jurisdiction: str, dir_: Path = DEFAULT_DIR) -> dict[str, Any]:
    code = jurisdiction.upper()
    if code not in COUNTRY_FILES:
        raise GuardrailError(f"unknown jurisdiction {jurisdiction!r}; expected one of {sorted(COUNTRY_FILES)}")
    return _load_json(dir_ / COUNTRY_FILES[code])


def rules_for(jurisdiction: str | None = None, dir_: Path = DEFAULT_DIR) -> list[dict[str, Any]]:
    """Base rules, plus the country overlay if a jurisdiction is given. Rule
    IDs are globally unique across the pack (see guardrails/README.md), so
    this is a concatenation, not a merge-by-key -- there is nothing for a
    country rule to override in the base file's rule_ids."""
    rules = list(base_pack(dir_)["rules"])
    if jurisdiction:
        rules += country_pack(jurisdiction, dir_)["rules"]
    return rules


def rule_by_id(rule_id: str, dir_: Path = DEFAULT_DIR) -> dict[str, Any] | None:
    for r in base_pack(dir_)["rules"]:
        if r["rule_id"] == rule_id:
            return r
    for code in COUNTRY_FILES:
        for r in country_pack(code, dir_)["rules"]:
            if r["rule_id"] == rule_id:
                return r
    return None


def validate_loaded(dir_: Path = DEFAULT_DIR) -> list[str]:
    """Load every file and sanity-check rule_id uniqueness / required keys.
    Used by the smoke test; not a substitute for the pack's own README claims."""
    problems: list[str] = []
    seen: set[str] = set()
    try:
        packs = [base_pack(dir_)] + [country_pack(c, dir_) for c in COUNTRY_FILES]
    except GuardrailError as exc:
        return [str(exc)]
    for pack in packs:
        for r in pack.get("rules", []):
            rid = r.get("rule_id")
            if not rid:
                problems.append(f"rule missing rule_id in {pack.get('meta', {}).get('file_role')}")
                continue
            if rid in seen:
                problems.append(f"duplicate rule_id across pack: {rid}")
            seen.add(rid)
    return problems


# --------------------------------------------------------------------------- #
# physical constants -- shared source of truth with rules_engine.py
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TemperatureBand:
    name: str
    min_c: float | None
    max_c: float | None
    refreeze_flag_c: float | None
    basis: str


def temperature_bands(dir_: Path = DEFAULT_DIR) -> dict[str, TemperatureBand]:
    raw = base_pack(dir_)["temperature_bands"]
    out: dict[str, TemperatureBand] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        rng = spec.get("range_c")
        min_c, max_c = (rng[0], rng[1]) if rng else (None, spec.get("max_c"))
        out[name] = TemperatureBand(
            name=name,
            min_c=min_c,
            max_c=max_c,
            refreeze_flag_c=spec.get("refreeze_flag_c"),
            basis=spec.get("basis", ""),
        )
    return out


def sentinel_values(dir_: Path = DEFAULT_DIR) -> frozenset[float]:
    """Numeric sentinel values from GCC-EDGE-001's trigger, e.g. -99.9. Falls
    back to the rule's own documented set if the pack changes shape."""
    rule = rule_by_id("GCC-EDGE-001", dir_)
    raw = (rule or {}).get("trigger", {}).get("sentinel_set", [-99.9, -999, 999, 0.0])
    return frozenset(v for v in raw if isinstance(v, (int, float)))


def temperature_sentinel_values(dir_: Path = DEFAULT_DIR) -> frozenset[float]:
    """``sentinel_values()`` scoped to temperature readings specifically.

    GCC-EDGE-001's raw ``sentinel_set`` includes ``0.0000`` as an example of
    a generic "default missing value" logger fault code. Taken literally for
    a *temperature* reading that would be wrong: 0C is a physically valid,
    common reading in this domain -- it's the freezing point, and sits
    inside both the chilled_general (0-5C) and chilled_fresh_seafood (0-4C)
    target bands. Treating every 0.0C reading as a sentinel would misfire on
    a large share of genuinely in-spec chilled telemetry. This deliberately
    drops 0.0 from the set used against temperature readings; the magnitude
    check in ``is_sentinel_reading`` (<=-50C or >=80C) still catches any
    value that is actually implausible for a refrigerated asset."""
    return sentinel_values(dir_) - {0.0}


def is_sentinel_reading(value: float | None, dir_: Path = DEFAULT_DIR) -> bool:
    """Mirrors GCC-EDGE-001's trigger expression: an explicit sentinel value,
    or a physically impossible reading for a refrigerated asset (<=-50C or
    >=80C). See ``temperature_sentinel_values`` for why literal 0.0 is
    excluded from the sentinel set in this temperature-specific context."""
    if value is None:
        return True
    return value in temperature_sentinel_values(dir_) or value <= -50 or value >= 80


def exclude_sentinel_readings(readings: list[float], dir_: Path = DEFAULT_DIR) -> tuple[list[float], int]:
    """GCC-EDGE-001: sentinel values are excluded from every aggregate and
    counted as a coverage gap, never averaged in or treated as a cold
    reading. Returns (clean_readings, excluded_count)."""
    clean = [r for r in readings if not is_sentinel_reading(r, dir_)]
    return clean, len(readings) - len(clean)


def refreeze_flag_c(dir_: Path = DEFAULT_DIR) -> float:
    """GCC-EDGE-013: any rise above this threshold in a frozen-regime
    consignment is a partial-thaw event regardless of duration or whether the
    log later shows a return to spec."""
    band = temperature_bands(dir_).get("frozen")
    return band.refreeze_flag_c if band and band.refreeze_flag_c is not None else -12.0


# --------------------------------------------------------------------------- #
# text-pattern checks -- a second, independent line of defence on rendered
# artifact text, run in addition to (not instead of) the LLM screener
# --------------------------------------------------------------------------- #

_METADATA_LEAK = re.compile(
    r"product_code\s*=|\bcell\s*[:=]|\bscenario\s*[:=]|rule_engine_sha|prompt_template_hash",
    re.IGNORECASE,
)
_EXPEDITE_WORDING = re.compile(r"\bexpedite[\s_-]?sale\b|\bexpedite\b[^.\n]{0,30}\bsale\b", re.IGNORECASE)
_TRUNCATED_CSV_TAIL = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\s*$")


@dataclass(frozen=True)
class Violation:
    rule_id: str
    detail: str


def check_artifact_text(text: str, artifact_type: str | None = None) -> list[Violation]:
    """Cheap, dependency-free regex checks. Not a replacement for the
    self-consistency-voted screener/leakage checks elsewhere in the pipeline
    -- a defense-in-depth net for exactly the failure modes the guardrail
    pack's provenance section documents wave_9001 actually hitting."""
    violations: list[Violation] = []
    if _METADATA_LEAK.search(text):
        violations.append(
            Violation(
                "GCC-EDGE-018",
                "artifact contains raw pipeline metadata (product_code=/cell/rule_engine_sha/"
                "prompt_template_hash) -- a decision-input leak vector, not observational text",
            )
        )
    if _EXPEDITE_WORDING.search(text):
        violations.append(
            Violation(
                "GCC-EDGE-015",
                "artifact proposes expedite_sale -- never an autonomous action under this pack",
            )
        )
    if artifact_type == "logger_csv" and _TRUNCATED_CSV_TAIL.search(text.rstrip()):
        violations.append(
            Violation(
                "GCC-EDGE-002",
                "logger_csv artifact ends mid-timestamp; the final record is incomplete",
            )
        )
    return violations
