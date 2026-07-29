from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_get_settings_requires_mongodb_uri(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env file in cwd
    from cold_chain.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, azure_endpoint="https://x", foundry_project_endpoint="https://x",
                 foundry_compute_cluster="c", foundry_base_model="m", training_region="r")


def test_settings_no_longer_pins_training_region():
    from cold_chain.config import Settings

    # Any region string is accepted -- no validator forces a specific value,
    # unlike the earlier UAE-North-pinned design.
    s = Settings(
        mongodb_uri="mongodb://localhost", azure_endpoint="https://x",
        foundry_project_endpoint="https://x", foundry_compute_cluster="c",
        foundry_base_model="m", training_region="anywhere-at-all",
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
        mongodb_uri="mongodb://localhost", azure_endpoint="https://x",
        foundry_project_endpoint="https://x", foundry_compute_cluster="c",
        foundry_base_model="m", training_region="r",
    )
    assert s.wave_size == 663
    assert s.cell_target == 265
    assert s.wave_size * 8 == 5304
