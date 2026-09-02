"""Tests for port fakes and offline fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cold_chain.adapters.fakes import FakeLLM, FakeLogbook, FakeTrainingSubmitter


@pytest.mark.asyncio
async def test_fake_logbook_round_trip():
    book = FakeLogbook()
    await book.put_coverage({"total_kept": 0})
    await book.put_wave_artifact(1, "plan.json", {"wave": 1})
    assert (await book.get_coverage())["total_kept"] == 0
    assert (await book.get_wave_artifact(1, "plan.json"))["wave"] == 1


@pytest.mark.asyncio
async def test_fake_llm_returns_fixture_response():
    fixtures = json.loads((Path(__file__).parent.parent / "fixtures" / "azure_responses.json").read_text())
    llm = FakeLLM(default=fixtures["completion"]["output_text"])
    result = await llm.complete("extract temperature")
    assert "temperature_c" in result


@pytest.mark.asyncio
async def test_fake_llm_failure_path():
    llm = FakeLLM(fail_on="rate_limit")
    with pytest.raises(RuntimeError, match="rate_limit"):
        await llm.complete("trigger rate_limit test")


@pytest.mark.asyncio
async def test_fake_training_submitter():
    submitter = FakeTrainingSubmitter()
    job_id = await submitter.submit(1, export_path="/tmp/export.jsonl")
    assert job_id == "job-fake-wave-1"
    assert submitter.submissions == [(1, "/tmp/export.jsonl")]
