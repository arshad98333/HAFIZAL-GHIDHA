from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_get_settings_requires_mongodb_uri(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env file in cwd
    from cold_chain.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            azure_endpoint="https://x",
            foundry_project_endpoint="https://x",
            foundry_compute_cluster="c",
            foundry_base_model="m",
            training_region="r",
        )


def test_settings_no_longer_pins_training_region():
    from cold_chain.config import Settings

    # Any region string is accepted -- no validator forces a specific value,
    # unlike the earlier UAE-North-pinned design.
    s = Settings(
        mongodb_uri="mongodb://localhost",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="anywhere-at-all",
    )
    assert s.training_region == "anywhere-at-all"


def test_settings_has_no_hardcoded_model_size_default():
    import inspect

    from cold_chain import config

    src = inspect.getsource(config)
    assert "0.5B" not in src
    assert "Qwen" not in src


def test_settings_has_no_k2_fields():
    from cold_chain.config import Settings

    fields = Settings.model_fields
    assert not any("k2" in name.lower() for name in fields)


def test_default_wave_size_and_cell_target():
    from cold_chain.config import Settings

    s = Settings(
        mongodb_uri="mongodb://localhost",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="r",
    )
    assert s.wave_size == 663
    assert s.cell_target == 265
    assert s.wave_size * 8 == 5304


def test_settings_masks_secrets_in_repr():
    from cold_chain.config import Settings

    s = Settings(
        mongodb_uri="mongodb+srv://user:secretpass@cluster.example/db",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="r",
        student_inference_key="super-secret",
        content_safety_key="also-secret",
    )
    text = repr(s)
    assert "secretpass" not in text
    assert "super-secret" not in text
    assert "also-secret" not in text
    assert "***" in text


def test_missing_required_env_lists_all_fields(monkeypatch, tmp_path):
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
    from cold_chain.config import Settings, missing_required_env_message

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    msg = missing_required_env_message(exc_info.value)
    assert "MONGODB_URI" in msg
    assert "AZURE_OPENAI_ENDPOINT" in msg
    assert "TRAINING_REGION" in msg
