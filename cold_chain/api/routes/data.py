"""Ledger and coverage read endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from cold_chain.adapters import logbook as lb
from cold_chain.api.deps import logbook_dep

router = APIRouter(tags=["data"])


@router.get("/ledger")
async def ledger(
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> list[dict[str, Any]]:
    return await book.read_ledger()


@router.get("/coverage")
async def coverage(
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> dict[str, Any]:
    return await book.load_coverage()
