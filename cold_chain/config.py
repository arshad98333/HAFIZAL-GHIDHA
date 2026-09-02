"""Runtime configuration. Every external dependency is an env var; nothing is
hardcoded so the same code runs in CI, a dev box, and the training job container.

Fails fast: a missing required var raises at process start, not three hours into
a wave.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

_REQUIRED_FIELD_TO_ALIAS = {
    "mongodb_uri": "MONGODB_URI",
    "azure_endpoint": "AZURE_OPENAI_ENDPOINT",
    "foundry_project_endpoint": "FOUNDRY_PROJECT_ENDPOINT",
    "foundry_compute_cluster": "FOUNDRY_COMPUTE_CLUSTER",
    "foundry_base_model": "FOUNDRY_BASE_MODEL",
    "training_region": "TRAINING_REGION",
}

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Lets callers construct Settings(training_region=...) by the Python
        # field name, not just the env-var alias -- mainly so tests can build
        # a Settings instance directly without an environment round trip.
        # Env vars still resolve through the alias exactly as before.
        populate_by_name=True,
    )

    # -- MongoDB Atlas (logbook of record) ------------------------------------
    # Use a database user scoped to `mongodb_db_name` only (Atlas custom role,
    # readWrite on that one database). The golden set lives in a separate
    # database with no role grant to this user at all -- that absent grant is
    # the actual enforcement of "golden set never mounted into an agent
    # environment," not application code.
    mongodb_uri: str = Field(..., alias="MONGODB_URI")
    mongodb_db_name: str = Field("cold_chain", alias="MONGODB_DB_NAME")

    # -- agentic gate B / review board (self-consistency voting) --------------
    # Self-consistency voting: each qualitative judgment (hallucination, abstention
    # quality, language authenticity) is asked JUDGE_VOTES times independently;
    # majority/median is taken and low-agreement items are escalated to a stricter
    # re-judge rather than silently averaged. This is the mitigation for LLM-judge
    # noise, not a substitute for it -- see agentic_eval.py module docstring for the
    # honest limitations versus a sealed human-run eval. The judge model is the
    # same Azure deployment used for rendering/screening (see AzureClient); there
    # is a single external model provider in this pipeline, not two.
    judge_votes: int = Field(5, alias="JUDGE_VOTES")
    judge_agreement_floor: float = Field(0.6, alias="JUDGE_AGREEMENT_FLOOR")

    # -- per-record confidence gate --------------------------------------------
    # A record can pass schema validation and the round-trip range check while
    # still being a weak, barely-inside-tolerance extraction. This is a second,
    # continuous filter on top of that pass/fail check -- below the floor, the
    # record is dropped (`dropped_low_confidence`) rather than kept as a shaky
    # example the student model would learn noise from.
    min_round_trip_confidence: float = Field(0.6, alias="MIN_ROUND_TRIP_CONFIDENCE")

    # -- student model inference (for Gate B auto-eval to have something to score) --
    student_inference_endpoint: str | None = Field(None, alias="STUDENT_INFERENCE_ENDPOINT")
    student_inference_key: str | None = Field(None, alias="STUDENT_INFERENCE_KEY")

    # -- Azure OpenAI (gpt-5.4-mini) -------------------------------------------
    azure_endpoint: str = Field(..., alias="AZURE_OPENAI_ENDPOINT")
    azure_deployment: str = Field("gpt-5.4-mini", alias="AZURE_OPENAI_DEPLOYMENT")
    azure_embedding_deployment: str = Field("text-embedding-3-small", alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    azure_api_version: str = Field("2024-10-01-preview", alias="AZURE_OPENAI_API_VERSION")
    # 32 was confirmed live to exceed this account's actual throughput -- a full
    # wave lost 26% of its items to sustained 429s at that setting. Raise only
    # after confirming the deployment's real TPM/RPM quota, not by guessing.
    azure_max_concurrency: int = Field(8, alias="AZURE_MAX_CONCURRENCY")
    azure_token_refresh_s: float = Field(2400.0, alias="AZURE_TOKEN_REFRESH_S")
    azure_timeout_s: float = Field(60.0, alias="AZURE_TIMEOUT_S")

    # -- Azure AI Content Safety ----------------------------------------------
    content_safety_endpoint: str | None = Field(None, alias="CONTENT_SAFETY_ENDPOINT")
    content_safety_key: str | None = Field(None, alias="CONTENT_SAFETY_KEY")

    # -- Managed training compute (student SFT) --------------------------------
    # Cloud-agnostic on purpose: no base-model size and no training region is
    # hardcoded here. Fill in whatever student checkpoint and region this
    # deployment actually targets.
    foundry_project_endpoint: str = Field(..., alias="FOUNDRY_PROJECT_ENDPOINT")
    foundry_compute_cluster: str = Field(..., alias="FOUNDRY_COMPUTE_CLUSTER")
    foundry_base_model: str = Field(..., alias="FOUNDRY_BASE_MODEL")
    training_region: str = Field(..., alias="TRAINING_REGION")

    # -- knowledge base + guardrails (GCC food-law corpus) ---------------------
    # Read-only reference data shipped with the repo. Paths are resolved
    # relative to the repo root by default; override only for a non-standard
    # checkout layout.
    knowledge_base_dir: Path = Field(ROOT / "gcc_food_law_json", alias="KNOWLEDGE_BASE_DIR")
    guardrails_dir: Path = Field(ROOT / "guardrails", alias="GUARDRAILS_DIR")

    # -- pipeline knobs --------------------------------------------------------
    # 5,304 records across 8 waves of 663. See CURRICULUM.md section 1.
    wave_size: int = Field(663, alias="WAVE_SIZE")
    cell_target: int = Field(265, alias="CELL_TARGET")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    environment: str = Field("production", alias="ENVIRONMENT")

    def model_dump_safe(self) -> dict[str, Any]:
        """Settings for logging — secrets masked."""
        data: dict[str, Any] = self.model_dump()
        if data.get("mongodb_uri"):
            data["mongodb_uri"] = _mask_mongodb_uri(data["mongodb_uri"])
        if data.get("student_inference_key"):
            data["student_inference_key"] = "***"
        if data.get("content_safety_key"):
            data["content_safety_key"] = "***"
        return data

    def __repr__(self) -> str:
        return f"Settings({self.model_dump_safe()!r})"


def _mask_mongodb_uri(uri: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", uri)


def missing_required_env_message(exc: ValidationError) -> str:
    """Human-readable list of missing required environment variables."""
    names: list[str] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        if loc:
            field = str(loc[0])
            names.append(_REQUIRED_FIELD_TO_ALIAS.get(field, field.upper()))
    unique = sorted(set(names))
    return "Missing required environment variables: " + ", ".join(unique)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
