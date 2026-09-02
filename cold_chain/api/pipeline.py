"""Pipeline stage runners callable from the HTTP API."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cold_chain.adapters import logbook as lb
from cold_chain.adapters.clients import AzureClient, ContentSafetyClient, StudentClient
from cold_chain.cli.runner import (
    WaveHalted,
    stage_close,
    stage_gate_a,
    stage_gate_b,
    stage_gate_b_auto,
    stage_generate,
    stage_preflight,
    stage_train,
)
from cold_chain.config import Settings, get_settings
from cold_chain.domain import curriculum
from cold_chain.observability.telemetry import (
    attach_mongo_sink,
    configure_logging,
    get_run_id,
    set_wave,
)


def health_payload() -> dict[str, Any]:
    from pydantic import ValidationError

    from cold_chain.config import missing_required_env_message

    try:
        settings = get_settings()
        return {
            "status": "ok",
            "environment": settings.environment,
            "checks": ["config"],
        }
    except ValidationError as exc:
        return {"status": "error", "error": missing_required_env_message(exc)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def ready_payload() -> dict[str, Any]:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        async with lb.Logbook(settings, "ready-check") as book:
            await book.load_coverage()
        return {"status": "ready", "mongodb_db": settings.mongodb_db_name}
    except Exception as exc:
        return {"status": "not_ready", "error": str(exc)}


async def _with_sink(settings: Settings, wave: int, fn) -> dict[str, Any]:
    configure_logging(settings.log_level)
    set_wave(wave)
    async with lb.Logbook(settings, get_run_id()) as book:
        sink_task = attach_mongo_sink(book.db, level=settings.log_level)
        try:
            return await fn(book)
        except WaveHalted as exc:
            await book.append_decisions(wave, f"### HALTED\n\n{exc}\n")
            return {"halted": True, "reason": str(exc)}
        finally:
            sink_task.cancel()
            try:
                await sink_task
            except Exception:
                pass


async def run_plan(wave: int) -> dict[str, Any]:
    settings = get_settings()

    async def _fn(book: lb.Logbook) -> dict[str, Any]:
        async with AzureClient(settings) as azure:
            plan = await curriculum.plan_wave(wave, book, azure, settings)
        return {"wave": wave, "plan": plan}

    return await _with_sink(settings, wave, _fn)


async def run_generate(
    wave: int,
    *,
    max_records: int | None = None,
    rate_per_minute: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()

    async def _fn(book: lb.Logbook) -> dict[str, Any]:
        plan = await book.read_json(wave, "plan.json")
        if plan is None:
            raise WaveHalted(f"no plan.json for wave {wave}; run plan first")
        async with AzureClient(settings) as azure, ContentSafetyClient(settings) as safety:
            await stage_generate(
                wave,
                plan,
                book,
                azure,
                safety,
                settings,
                rate_per_minute=rate_per_minute,
                max_records=max_records,
            )
        rows = await book.read_generation(wave)
        kept = sum(1 for r in rows if r.get("outcome") == "kept")
        return {"wave": wave, "attempted": len(rows), "kept": kept}

    return await _with_sink(settings, wave, _fn)


async def run_gate_a(wave: int) -> dict[str, Any]:
    settings = get_settings()

    async def _fn(book: lb.Logbook) -> dict[str, Any]:
        plan = await book.read_json(wave, "plan.json")
        if plan is None:
            raise WaveHalted(f"no plan.json for wave {wave}; run plan first")
        async with AzureClient(settings) as azure:
            result = await stage_gate_a(wave, plan, book, azure, settings)
        return {"wave": wave, **result}

    payload = await _with_sink(settings, wave, _fn)
    if payload.get("halted"):
        return payload
    return payload


async def run_preflight(wave: int) -> dict[str, Any]:
    settings = get_settings()

    async def _fn(book: lb.Logbook) -> dict[str, Any]:
        return await stage_preflight(wave, settings, book)

    return await _with_sink(settings, wave, _fn)


async def run_train(wave: int, *, dry_run: bool = False) -> dict[str, Any]:
    settings = get_settings()

    async def _fn(book: lb.Logbook) -> dict[str, Any]:
        gate_a = await book.read_json(wave, "gate_a.json")
        if not dry_run and (not gate_a or not gate_a.get("passed")):
            raise WaveHalted(f"Gate A has not passed for wave {wave}")
        dataset_hash = hashlib.sha256(
            json.dumps((gate_a or {}).get("metrics", {}), sort_keys=True).encode()
        ).hexdigest()[:12]
        result = await stage_train(wave, settings, book, dataset_hash, dry_run=dry_run)
        return {"wave": wave, **result}

    return await _with_sink(settings, wave, _fn)


async def run_gate_b(
    wave: int,
    *,
    results_path: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()

    async def _fn(book: lb.Logbook) -> dict[str, Any]:
        if results_path:
            _, slices = await stage_gate_b(wave, Path(results_path), book)
        else:
            async with AzureClient(settings) as azure, StudentClient(settings) as student:
                _, slices = await stage_gate_b_auto(wave, book, azure, student, settings)
        plan = await book.read_json(wave, "plan.json") or {"total": 0}
        await stage_close(wave, plan, slices, book, notes=notes or "")
        gate_b = await book.read_json(wave, "gate_b.json")
        return {"wave": wave, "gate_b": gate_b}

    return await _with_sink(settings, wave, _fn)


async def audit_wave(wave: int) -> dict[str, Any]:
    settings = get_settings()
    root = Path(__file__).resolve().parent.parent.parent
    async with lb.Logbook(settings, "api-audit") as book:
        gate = await book.read_json(wave, "gate_a.json")
        rows = await book.read_generation(wave)
    kept = [r for r in rows if r.get("outcome") == "kept"]
    export_path = root / "exports" / f"generation_log_wave{wave:02d}.jsonl"
    export_lines = None
    if export_path.exists():
        export_lines = sum(1 for _ in export_path.open(encoding="utf-8"))
    return {
        "wave": wave,
        "generation_log_rows": len(rows),
        "kept_records": len(kept),
        "gate_a_passed": gate.get("passed") if gate else None,
        "gate_a_metrics": gate.get("metrics") if gate else None,
        "gate_a_failures": gate.get("failures") or [] if gate else [],
        "export_path": str(export_path) if export_path.exists() else None,
        "export_lines": export_lines,
    }


async def score_kpi(wave: int) -> dict[str, Any]:
    import sys

    root = Path(__file__).resolve().parent.parent.parent
    scripts = str(root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from kpi_dashboard import score_wave

    return await score_wave(wave)
