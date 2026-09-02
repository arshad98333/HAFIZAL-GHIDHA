"""Health and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from cold_chain.api import pipeline
from cold_chain.api.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse | JSONResponse:
    payload = pipeline.health_payload()
    if payload.get("status") != "ok":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return HealthResponse(**payload)


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse | JSONResponse:
    payload = await pipeline.ready_payload()
    if payload.get("status") != "ready":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return ReadyResponse(**payload)
