"""Background job status endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cold_chain.api.deps import job_dep
from cold_chain.api.jobs import Job, job_manager
from cold_chain.api.schemas import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_response(job: Job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        name=job.name,
        status=job.status,
        wave=job.wave,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=job.result,
        error=job.error,
    )


@router.get("", response_model=list[JobResponse])
def list_jobs(
    wave: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[JobResponse]:
    return [_to_response(j) for j in job_manager.list_jobs(wave=wave, limit=limit)]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job: Annotated[Job, Depends(job_dep)]) -> JobResponse:
    return _to_response(job)
