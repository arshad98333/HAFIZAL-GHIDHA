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


def test_settings_k2_fields_are_optional_and_off_by_default(monkeypatch):
    """K2 was previously removed from the training pipeline's render/screen/
    judge path entirely (TESTING_REPORT_azure_review_migration.md) and this
    test used to assert Settings had no K2 fields at all. K2 has since been
    reintroduced for a deliberately separate concern: the compliance Q&A
    chat (/compliance/ask), not the training pipeline. The field must exist,
    but must default to disabled (no API key) so an API without K2
    configured still starts and runs the rest of the pipeline unaffected."""
    from cold_chain.config import Settings

    fields = Settings.model_fields
    assert "k2_api_key" in fields
    assert "k2_base_url" in fields
    assert "k2_model" in fields

    # _env_file=None only stops pydantic-settings reading .env itself; it
    # does NOT protect against K2_API_KEY already sitting in the real
    # process environment -- which happens in a full test-suite run because
    # some scripts/ modules call python-dotenv's load_dotenv() at import
    # time (collected before this test runs), and this repo's own .env
    # defines K2_API_KEY for real use of the feature. monkeypatch.delenv
    # guarantees the "nothing configured" default this test actually
    # asserts, regardless of what else has run first in the same session.
    monkeypatch.delenv("K2_API_KEY", raising=False)
    s = Settings(
        _env_file=None,
        mongodb_uri="mongodb://localhost",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="r",
    )
    assert s.k2_api_key is None
    assert s.k2_model == "MBZUAI-IFM/K2-Think-v2"


def test_settings_masks_k2_api_key_in_safe_dump():
    from cold_chain.config import Settings

    s = Settings(
        _env_file=None,
        mongodb_uri="mongodb://localhost",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="r",
        k2_api_key="super-secret-value",
    )
    dumped = s.model_dump_safe()
    assert dumped["k2_api_key"] == "***"
    assert "super-secret-value" not in repr(s)


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
