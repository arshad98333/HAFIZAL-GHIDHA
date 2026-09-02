"""FastAPI HTTP API tests (no MongoDB or Azure calls)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cold_chain.api.app import create_app
from cold_chain.api.jobs import job_manager


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "gcc-cold-chain-pipeline"


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_not_ready_when_mongo_down(client):
    with patch("cold_chain.api.pipeline.ready_payload", new_callable=AsyncMock) as mock_ready:
        mock_ready.return_value = {"status": "not_ready", "error": "connection refused"}
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_wave_plan_not_found(client):
    mock_book = AsyncMock()
    mock_book.read_json = AsyncMock(return_value=None)
    mock_book.__aenter__ = AsyncMock(return_value=mock_book)
    mock_book.__aexit__ = AsyncMock(return_value=None)

    with patch("cold_chain.api.deps.lb.Logbook", return_value=mock_book):
        response = client.get("/waves/1/plan")
    assert response.status_code == 404


def test_wave_plan_found(client):
    mock_book = AsyncMock()
    mock_book.read_json = AsyncMock(return_value={"wave": 1, "total": 663})
    mock_book.__aenter__ = AsyncMock(return_value=mock_book)
    mock_book.__aexit__ = AsyncMock(return_value=None)

    with patch("cold_chain.api.deps.lb.Logbook", return_value=mock_book):
        response = client.get("/waves/1/plan")
    assert response.status_code == 200
    assert response.json()["total"] == 663


def test_wave_records_pagination(client):
    rows = [{"state_id": f"id-{i}", "outcome": "kept" if i % 2 == 0 else "dropped"} for i in range(5)]
    mock_book = AsyncMock()
    mock_book.read_generation = AsyncMock(return_value=rows)
    mock_book.__aenter__ = AsyncMock(return_value=mock_book)
    mock_book.__aexit__ = AsyncMock(return_value=None)

    with patch("cold_chain.api.deps.lb.Logbook", return_value=mock_book):
        response = client.get("/waves/1/records?limit=2&offset=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 5
    assert payload["offset"] == 1
    assert len(payload["records"]) == 2


def test_post_plan_background(client):
    with patch("cold_chain.api.pipeline.run_plan", new_callable=AsyncMock) as mock_plan:
        mock_plan.return_value = {"wave": 1, "plan": {"total": 10}}
        response = client.post("/waves/1/plan?background=true")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert job_id


def test_get_job_not_found(client):
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


def test_wave_audit(client):
    with patch("cold_chain.api.pipeline.audit_wave", new_callable=AsyncMock) as mock_audit:
        mock_audit.return_value = {
            "wave": 1,
            "generation_log_rows": 750,
            "kept_records": 750,
            "gate_a_passed": False,
            "gate_a_metrics": {"near_duplicate_rate": 0.43},
            "gate_a_failures": ["near_duplicate_rate"],
            "export_path": None,
            "export_lines": None,
        }
        response = client.get("/waves/1/audit")
    assert response.status_code == 200
    assert response.json()["kept_records"] == 750


def test_simulate_door_open(client):
    response = client.post(
        "/simulate",
        json={
            "product": "finfish_seafood",
            "fault_mode": "door_open",
            "jurisdiction": "AE",
            "artifact_type": "logger_csv",
            "seed": 42,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["product"] == "finfish_seafood"
    assert len(payload["readings_c"]) == 96
    assert payload["disposition"] in {"accept", "hold_for_qa", "reject", "insufficient_data"}
    assert payload["rule_id"].startswith("R")
    assert len(payload["steps"]) >= 4
