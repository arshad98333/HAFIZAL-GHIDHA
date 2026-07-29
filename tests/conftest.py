"""Shared test fixtures. No network, no MongoDB, no Azure credentials --
everything here exercises the deterministic core of the pipeline. The async
clients and Mongo-backed logbook are covered by scripts/smoke_test.py
against a real environment instead."""

from __future__ import annotations

import os

import pytest

# Required Settings fields need *something* present before any test imports
# cold_chain.config (module-level get_settings() calls are cached but a
# fresh import in a subprocess would still need these). Set harmless
# placeholders once, for the whole test session.
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example-test.services.ai.azure.com")
os.environ.setdefault("FOUNDRY_PROJECT_ENDPOINT", "https://example-test.services.ai.azure.com/api/projects/test")
os.environ.setdefault("FOUNDRY_COMPUTE_CLUSTER", "test-cluster")
os.environ.setdefault("FOUNDRY_BASE_MODEL", "test-org/test-base-model")
os.environ.setdefault("TRAINING_REGION", "test-region")


@pytest.fixture
def env_settings(monkeypatch):
    """Fresh required env vars for a single test, isolated from the session defaults."""
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example-test.services.ai.azure.com")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example-test.services.ai.azure.com/api/projects/test")
    monkeypatch.setenv("FOUNDRY_COMPUTE_CLUSTER", "test-cluster")
    monkeypatch.setenv("FOUNDRY_BASE_MODEL", "test-org/test-base-model")
    monkeypatch.setenv("TRAINING_REGION", "test-region")
    return monkeypatch
