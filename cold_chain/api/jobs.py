"""In-memory background job tracker for long-running pipeline stages."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cold_chain.api.schemas import JobStatus


@dataclass
class Job:
    job_id: str
    name: str
    wave: int | None
    status: JobStatus = JobStatus.pending
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    _task: asyncio.Task[None] | None = field(default=None, repr=False)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        name: str,
        coro_factory: Callable[[], Awaitable[dict[str, Any]]],
        *,
        wave: int | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id, name=name, wave=wave)
        async with self._lock:
            self._jobs[job_id] = job

        async def _runner() -> None:
            job.status = JobStatus.running
            job.started_at = datetime.now(UTC)
            try:
                job.result = await coro_factory()
                job.status = JobStatus.succeeded
            except Exception as exc:
                job.status = JobStatus.failed
                job.error = str(exc)
            finally:
                job.finished_at = datetime.now(UTC)

        job._task = asyncio.create_task(_runner(), name=f"job:{name}:{job_id[:8]}")
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self, *, wave: int | None = None, limit: int = 50) -> list[Job]:
        jobs = list(self._jobs.values())
        if wave is not None:
            jobs = [j for j in jobs if j.wave == wave]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]


job_manager = JobManager()
