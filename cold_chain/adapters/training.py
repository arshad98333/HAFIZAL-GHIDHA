"""Managed SFT job submission via Azure ML / Foundry."""

from __future__ import annotations

import asyncio
from typing import Any

from cold_chain.config import Settings
from cold_chain.domain.errors import AdapterError
from cold_chain.domain.rules_engine import engine_sha
from cold_chain.observability.telemetry import get_logger

log = get_logger(__name__)


class FoundryTrainingSubmitter:
    """Submits SFT jobs to Foundry compute. Requires azure-ai-ml at runtime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def submit(self, wave: int, *, dataset_hash: str = "", export_path: str = "") -> dict[str, Any]:
        def _submit() -> dict[str, Any]:
            try:
                from azure.ai.ml import MLClient, command
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:
                raise AdapterError("azure-ai-ml not available for training submit") from exc

            ml_client = MLClient.from_config(credential=DefaultAzureCredential())
            job = command(
                code=".",
                command="python -m training.sft --wave ${{inputs.wave}} --base-model ${{inputs.base_model}}",
                inputs={"wave": wave, "base_model": self._settings.foundry_base_model},
                compute=self._settings.foundry_compute_cluster,
                environment="azureml:cold-chain-sft@latest",
                tags={
                    "rules_engine_sha": engine_sha(),
                    "dataset_hash": dataset_hash,
                    "wave": str(wave),
                    "region": self._settings.training_region,
                },
                display_name=f"cold-chain-sft-wave-{wave:02d}",
            )
            submitted = ml_client.jobs.create_or_update(job)
            return {"job_name": submitted.name, "status": submitted.status}

        try:
            result = await asyncio.to_thread(_submit)
        except Exception as exc:
            raise AdapterError(f"training submit failed for wave {wave}: {exc}") from exc
        log.info("training job submitted", extra={"wave": wave, **result})
        return result
