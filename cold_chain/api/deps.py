"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException

from cold_chain.adapters import logbook as lb
from cold_chain.adapters import k2_client as k2
from cold_chain.api.jobs import Job, job_manager
from cold_chain.config import Settings, get_settings


def settings_dep() -> Settings:
    try:
        return get_settings()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def logbook_dep(
    settings: Annotated[Settings, Depends(settings_dep)],
) -> AsyncIterator[lb.Logbook]:
    book = lb.Logbook(settings, "api")
    await book.__aenter__()
    try:
        yield book
    finally:
        await book.__aexit__(None, None, None)


async def k2_dep(
    settings: Annotated[Settings, Depends(settings_dep)],
) -> k2.K2Client:
    # Process-wide singleton -- see k2_client.py module docstring ("Singleton,
    # not per-request") for why a fresh K2Client per request would silently
    # defeat the RPM-throttling semaphore across concurrent users.
    return await k2.get_k2_client(settings)


def job_dep(job_id: str) -> Job:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return job
