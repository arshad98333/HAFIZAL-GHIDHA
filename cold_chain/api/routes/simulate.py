"""Deterministic pipeline simulation — no MongoDB or LLM required."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cold_chain.api.schemas import SimulateRequest, SimulateResponse
from cold_chain.api.simulation import run_simulation

router = APIRouter(prefix="/simulate", tags=["simulate"])


@router.post("", response_model=SimulateResponse)
def simulate(req: SimulateRequest) -> SimulateResponse:
    """Synthesize world state from inputs, label with rules engine, preview artifact."""
    try:
        return run_simulation(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
