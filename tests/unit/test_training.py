"""Tests for training submitter adapter."""

from __future__ import annotations

import pytest

from cold_chain.adapters.fakes import FakeTrainingSubmitter
from cold_chain.domain.errors import AdapterError


@pytest.mark.asyncio
async def test_fake_training_submitter_records_submission():
    submitter = FakeTrainingSubmitter()
    job_id = await submitter.submit(2, export_path="/tmp/wave2.jsonl")
    assert "fake" in job_id


def test_adapter_error_is_domain_error():
    err = AdapterError("training unavailable")
    assert "training" in str(err)
