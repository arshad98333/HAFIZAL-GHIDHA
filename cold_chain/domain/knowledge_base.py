"""Loader for the GCC food-law knowledge base (``gcc_food_law_json/``).

Six country profiles (UAE, Saudi Arabia, Qatar, Kuwait, Oman, Bahrain) plus a
shared JSON Schema, compiled from official regulatory sources. This module is
the only place that reads those files: everything else in the pipeline asks
this module for a citation, an authority name, or a temperature-band basis,
rather than opening the JSON itself.

This is reference data, not a live regulatory feed -- ``data_current_as_of``
in each file's ``meta`` block records what it was accurate against.
``CHANGELOG_AND_VERIFICATION.md`` in the same directory records what was
verified, what was corrected, and what is still an open gap. Nothing here is
legal advice; every citation carries the instrument name so a human can
verify at source before it drives an enforcement action.

Loading is eager and cached (``lru_cache``) -- six files of tens of KB each,
read once per process, never re-read per record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "gcc_food_law_json"

# ISO 3166-1 alpha-2 -> profile filename stem, in the pack's canonical order.
COUNTRY_FILES: dict[str, str] = {
    "AE": "01_uae_food_law.json",
    "SA": "02_saudi_arabia_food_law.json",
    "QA": "03_qatar_food_law.json",
    "KW": "04_kuwait_food_law.json",
    "OM": "05_oman_food_law.json",
    "BH": "06_bahrain_food_law.json",
}

JURISDICTIONS: tuple[str, ...] = tuple(COUNTRY_FILES)  # AE, SA, QA, KW, OM, BH


@dataclass(frozen=True)
class LegalCitation:
    jurisdiction: str
    country: str
    instrument: str
    authority: str
    authority_abbreviation: str


class KnowledgeBaseError(RuntimeError):
    """Raised when the knowledge base directory is missing or malformed --
    this is a startup-time configuration error, not a per-record failure."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KnowledgeBaseError(f"knowledge base file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise KnowledgeBaseError(f"knowledge base file is not valid JSON: {path} ({exc})") from exc


@lru_cache(maxsize=1)
def schema(kb_dir: Path = DEFAULT_DIR) -> dict[str, Any]:
    return _load_json(kb_dir / "00_schema.json")


@lru_cache(maxsize=8)
def profile(jurisdiction: str, kb_dir: Path = DEFAULT_DIR) -> dict[str, Any]:
    """The full country profile document for one GCC jurisdiction."""
    code = jurisdiction.upper()
    if code not in COUNTRY_FILES:
        raise KnowledgeBaseError(f"unknown jurisdiction {jurisdiction!r}; expected one of {sorted(COUNTRY_FILES)}")
    return _load_json(kb_dir / COUNTRY_FILES[code])


def all_profiles(kb_dir: Path = DEFAULT_DIR) -> dict[str, dict[str, Any]]:
    return {code: profile(code, kb_dir) for code in COUNTRY_FILES}


def _primary_authority(prof: dict[str, Any]) -> dict[str, Any]:
    ca = prof.get("competent_authorities", {})
    return ca.get("primary") or ca.get("primary_federal") or {}


def citation(jurisdiction: str, kb_dir: Path = DEFAULT_DIR) -> LegalCitation:
    """The headline statute + primary regulator for a jurisdiction -- used to
    populate provenance/legal_citations fields without ever quoting a penalty
    figure or clearance workflow from memory (those are exactly the fields
    ``CHANGELOG_AND_VERIFICATION.md`` flags as needing source verification)."""
    prof = profile(jurisdiction, kb_dir)
    authority = _primary_authority(prof)
    return LegalCitation(
        jurisdiction=jurisdiction.upper(),
        country=prof.get("meta", {}).get("country", jurisdiction.upper()),
        instrument=prof.get("legal_framework", {}).get("primary_law", {}).get("citation", "unspecified"),
        authority=authority.get("name", "unspecified"),
        authority_abbreviation=authority.get("abbreviation", ""),
    )


def validate_loaded(kb_dir: Path = DEFAULT_DIR) -> list[str]:
    """Best-effort structural check (required top-level keys per
    ``00_schema.json``), used by the smoke test and by CI -- not a full JSON
    Schema validator, just enough to catch a truncated or renamed file before
    a wave depends on it. Returns a list of problems; empty means clean."""
    required = set(schema(kb_dir).get("required", []))
    problems: list[str] = []
    for code in COUNTRY_FILES:
        try:
            prof = profile(code, kb_dir)
        except KnowledgeBaseError as exc:
            problems.append(str(exc))
            continue
        missing = required - prof.keys()
        if missing:
            problems.append(f"{code}: missing required top-level keys {sorted(missing)}")
    return problems
