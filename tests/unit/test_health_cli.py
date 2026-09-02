"""Tests for health and ready CLI commands."""

from __future__ import annotations

import json
import subprocess
import sys


def test_health_cli_exits_zero_with_test_env():
    result = subprocess.run(
        [sys.executable, "-m", "cold_chain.runner", "health"],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "MONGODB_URI": "mongodb://localhost:27017",
            "AZURE_OPENAI_ENDPOINT": "https://example-test.services.ai.azure.com",
            "FOUNDRY_PROJECT_ENDPOINT": "https://example-test.services.ai.azure.com/api/projects/test",
            "FOUNDRY_COMPUTE_CLUSTER": "test-cluster",
            "FOUNDRY_BASE_MODEL": "test-org/test-base-model",
            "TRAINING_REGION": "test-region",
        },
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"


def test_health_cli_fails_without_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in (
        "MONGODB_URI",
        "AZURE_OPENAI_ENDPOINT",
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_COMPUTE_CLUSTER",
        "FOUNDRY_BASE_MODEL",
        "TRAINING_REGION",
    ):
        monkeypatch.delenv(key, raising=False)
    from cold_chain.config import get_settings

    get_settings.cache_clear()
    result = subprocess.run(
        [sys.executable, "-m", "cold_chain.runner", "health"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            k: v
            for k, v in __import__("os").environ.items()
            if k
            not in (
                "MONGODB_URI",
                "AZURE_OPENAI_ENDPOINT",
                "FOUNDRY_PROJECT_ENDPOINT",
                "FOUNDRY_COMPUTE_CLUSTER",
                "FOUNDRY_BASE_MODEL",
                "TRAINING_REGION",
            )
        },
    )
    get_settings.cache_clear()
    assert result.returncode != 0
