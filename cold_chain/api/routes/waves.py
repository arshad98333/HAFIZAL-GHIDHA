"""Read-only wave and ledger endpoints."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from cold_chain.adapters import logbook as lb
from cold_chain.api import pipeline
from cold_chain.api.deps import logbook_dep
from cold_chain.api.schemas import RecordsCount, RecordsPage, WaveAuditResponse

router = APIRouter(prefix="/waves", tags=["waves"])


@router.get("/{wave}/audit", response_model=WaveAuditResponse)
async def wave_audit(wave: int) -> WaveAuditResponse:
    payload = await pipeline.audit_wave(wave)
    return WaveAuditResponse(**payload)


@router.get("/{wave}/plan")
async def wave_plan(
    wave: int,
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> dict[str, Any]:
    plan = await book.read_json(wave, "plan.json")
    if plan is None:
        raise HTTPException(status_code=404, detail=f"no plan.json for wave {wave}")
    return plan


@router.get("/{wave}/gate-a")
async def wave_gate_a(
    wave: int,
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> dict[str, Any]:
    gate = await book.read_json(wave, "gate_a.json")
    if gate is None:
        raise HTTPException(status_code=404, detail=f"no gate_a.json for wave {wave}")
    return gate


@router.get("/{wave}/gate-b")
async def wave_gate_b(
    wave: int,
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> dict[str, Any]:
    gate = await book.read_json(wave, "gate_b.json")
    if gate is None:
        raise HTTPException(status_code=404, detail=f"no gate_b.json for wave {wave}")
    return gate


@router.get("/{wave}/preflight")
async def wave_preflight(
    wave: int,
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> dict[str, Any]:
    payload = await book.read_json(wave, "preflight.json")
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no preflight.json for wave {wave}")
    return payload


@router.get("/{wave}/decisions")
async def wave_decisions(
    wave: int,
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> list[str]:
    return await book.read_decisions(wave)


@router.get("/{wave}/records", response_model=RecordsPage)
async def wave_records(
    wave: int,
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
    outcome: str | None = Query(None, description="Filter by outcome, e.g. kept"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> RecordsPage:
    rows = await book.read_generation(wave)
    if outcome:
        rows = [r for r in rows if r.get("outcome") == outcome]
    total = len(rows)
    page = rows[offset : offset + limit]
    return RecordsPage(wave=wave, total=total, offset=offset, limit=limit, records=page)


@router.get("/{wave}/records/count", response_model=RecordsCount)
async def wave_records_count(
    wave: int,
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> RecordsCount:
    rows = await book.read_generation(wave)
    by_outcome = Counter(r.get("outcome", "unknown") for r in rows)
    kept = by_outcome.get("kept", 0)
    return RecordsCount(wave=wave, total=len(rows), kept=kept, by_outcome=dict(by_outcome))


@router.get("/{wave}/kpi")
async def wave_kpi(wave: int) -> dict[str, Any]:
    return await pipeline.score_kpi(wave)
