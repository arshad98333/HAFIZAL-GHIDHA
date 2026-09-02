"""Vertical slice: plan stage writes coverage via fake logbook (no network)."""

from __future__ import annotations

import pytest

from cold_chain.adapters.fakes import FakeLogbook
from cold_chain.domain import curriculum


@pytest.mark.asyncio
async def test_plan_vertical_slice_writes_artifact():
    book = FakeLogbook()
    plan = await curriculum.build_plan(1, book)  # type: ignore[arg-type]
    assert plan["wave"] == 1
    assert plan["total"] > 0
    assert "allocations" in plan
