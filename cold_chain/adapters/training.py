"""Managed SFT job submission via Azure ML / Foundry."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

from cold_chain.config import Settings
from cold_chain.domain.errors import AdapterError
from cold_chain.domain.rules_engine import engine_sha
from cold_chain.observability.telemetry import get_logger

log = get_logger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent


def training_module_available() -> bool:
    return importlib.util.find_spec("training.sft") is not None


def preflight_check(settings: Settings, wave: int, *, export_path: Path | None = None) -> dict[str, Any]:
    """Validate training prerequisites without submitting a job."""
    export = export_path or (ROOT / "exports" / f"generation_log_wave{wave:02d}.jsonl")
    checks: dict[str, dict[str, Any]] = {
        "foundry_project": {"ok": bool(settings.foundry_project_endpoint), "detail": "FOUNDRY_PROJECT_ENDPOINT"},
        "compute_cluster": {"ok": bool(settings.foundry_compute_cluster), "detail": "FOUNDRY_COMPUTE_CLUSTER"},
        "base_model": {"ok": bool(settings.foundry_base_model), "detail": "FOUNDRY_BASE_MODEL"},
        "training_region": {"ok": bool(settings.training_region), "detail": "TRAINING_REGION"},
        "export_file": {
            "ok": export.exists(),
            "detail": str(export),
            "lines": sum(1 for _ in export.open(encoding="utf-8")) if export.exists() else 0,
        },
        "training_module": {"ok": training_module_available(), "detail": "training.sft"},
    }
    ready = all(c["ok"] for c in checks.values())
    return {"ready": ready, "wave": wave, "export_path": str(export), "checks": checks}


class FoundryTrainingSubmitter:
    """Submits SFT jobs to Foundry compute. Requires azure-ai-ml at runtime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def submit(
        self,
        wave: int,
        *,
        dataset_hash: str = "",
        export_path: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        preflight = preflight_check(
            self._settings,
            wave,
            export_path=Path(export_path) if export_path else None,
        )
        if dry_run:
            log.info("training dry-run", extra={"wave": wave, **preflight})
            return {"status": "dry_run", "preflight": preflight}

        if not preflight["ready"]:
            failed = [k for k, v in preflight["checks"].items() if not v["ok"]]
            raise AdapterError(f"training preflight failed for wave {wave}: {', '.join(failed)}")

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
