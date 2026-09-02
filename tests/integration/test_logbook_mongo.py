"""Integration tests — require docker-compose MongoDB."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_logbook_connects_to_local_mongo():
    uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    if "localhost" not in uri and "127.0.0.1" not in uri:
        pytest.skip("integration test expects local MongoDB")

    from cold_chain.adapters.logbook import Logbook
    from cold_chain.config import Settings

    settings = Settings(
        mongodb_uri=uri,
        mongodb_db_name="cold_chain_test",
        azure_endpoint="https://example-test.services.ai.azure.com",
        foundry_project_endpoint="https://example-test.services.ai.azure.com/api/projects/test",
        foundry_compute_cluster="test-cluster",
        foundry_base_model="test-org/test-base-model",
        training_region="test-region",
        _env_file=None,
    )
    async with Logbook(settings, "test-run") as book:
        cov = await book.load_coverage()
        assert "cells" in cov
