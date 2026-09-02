"""Pipeline stage trigger endpoints (background jobs)."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from cold_chain.api import pipeline
from cold_chain.api.jobs import job_manager
from cold_chain.api.schemas import GateBRequest, GenerateRequest, JobSubmitResponse, TrainRequest

router = APIRouter(prefix="/waves", tags=["pipeline"])


def _submit_response(job) -> JobSubmitResponse:
    return JobSubmitResponse(
        job_id=job.job_id,
        name=job.name,
        status=job.status,
        message=f"Job {job.job_id} submitted. Poll GET /jobs/{job.job_id} for status.",
    )


@router.post("/{wave}/plan", status_code=status.HTTP_202_ACCEPTED, response_model=JobSubmitResponse)
async def post_plan(
    wave: int,
    background: bool = Query(True, description="Run in background (recommended)"),
) -> JobSubmitResponse | dict:
    if not background:
        return await pipeline.run_plan(wave)
    job = await job_manager.submit("plan", lambda: pipeline.run_plan(wave), wave=wave)
    return _submit_response(job)


@router.post("/{wave}/generate", status_code=status.HTTP_202_ACCEPTED, response_model=JobSubmitResponse)
async def post_generate(
    wave: int,
    body: GenerateRequest | None = None,
    background: bool = Query(True),
) -> JobSubmitResponse | dict:
    body = body or GenerateRequest()
    if not background:
        return await pipeline.run_generate(
            wave,
            max_records=body.max_records,
            rate_per_minute=body.rate_per_minute,
        )
    job = await job_manager.submit(
        "generate",
        lambda: pipeline.run_generate(
            wave,
            max_records=body.max_records,
            rate_per_minute=body.rate_per_minute,
        ),
        wave=wave,
    )
    return _submit_response(job)


@router.post("/{wave}/gate-a", status_code=status.HTTP_202_ACCEPTED, response_model=JobSubmitResponse)
async def post_gate_a(
    wave: int,
    background: bool = Query(True),
) -> JobSubmitResponse | dict:
    if not background:
        return await pipeline.run_gate_a(wave)
    job = await job_manager.submit("gate-a", lambda: pipeline.run_gate_a(wave), wave=wave)
    return _submit_response(job)


@router.post("/{wave}/preflight", status_code=status.HTTP_202_ACCEPTED, response_model=JobSubmitResponse)
async def post_preflight(
    wave: int,
    background: bool = Query(False),
) -> JobSubmitResponse | dict:
    if not background:
        return await pipeline.run_preflight(wave)
    job = await job_manager.submit("preflight", lambda: pipeline.run_preflight(wave), wave=wave)
    return _submit_response(job)


@router.post("/{wave}/train", status_code=status.HTTP_202_ACCEPTED, response_model=JobSubmitResponse)
async def post_train(
    wave: int,
    body: TrainRequest | None = None,
    background: bool = Query(True),
) -> JobSubmitResponse | dict:
    body = body or TrainRequest()
    if not background:
        return await pipeline.run_train(wave, dry_run=body.dry_run)
    job = await job_manager.submit(
        "train",
        lambda: pipeline.run_train(wave, dry_run=body.dry_run),
        wave=wave,
    )
    return _submit_response(job)


@router.post("/{wave}/gate-b", status_code=status.HTTP_202_ACCEPTED, response_model=JobSubmitResponse)
async def post_gate_b(
    wave: int,
    body: GateBRequest | None = None,
    background: bool = Query(True),
) -> JobSubmitResponse | dict:
    body = body or GateBRequest()
    if not background:
        return await pipeline.run_gate_b(wave, results_path=body.results_path, notes=body.notes)
    job = await job_manager.submit(
        "gate-b",
        lambda: pipeline.run_gate_b(wave, results_path=body.results_path, notes=body.notes),
        wave=wave,
    )
    return _submit_response(job)
