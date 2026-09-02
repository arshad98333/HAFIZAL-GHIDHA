"""Request and response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    environment: str | None = None
    checks: list[str] = Field(default_factory=list)
    error: str | None = None


class ReadyResponse(BaseModel):
    status: str
    mongodb_db: str | None = None
    error: str | None = None


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobResponse(BaseModel):
    job_id: str
    name: str
    status: JobStatus
    wave: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class JobSubmitResponse(BaseModel):
    job_id: str
    name: str
    status: JobStatus
    message: str


class GenerateRequest(BaseModel):
    max_records: int | None = None
    rate_per_minute: int | None = None


class TrainRequest(BaseModel):
    dry_run: bool = False


class GateBRequest(BaseModel):
    results_path: str | None = None
    notes: str | None = None


class WaveAuditResponse(BaseModel):
    wave: int
    generation_log_rows: int
    kept_records: int
    gate_a_passed: bool | None = None
    gate_a_metrics: dict[str, Any] | None = None
    gate_a_failures: list[str] = Field(default_factory=list)
    export_path: str | None = None
    export_lines: int | None = None


class RecordsPage(BaseModel):
    wave: int
    total: int
    offset: int
    limit: int
    records: list[dict[str, Any]]


class RecordsCount(BaseModel):
    wave: int
    total: int
    kept: int
    by_outcome: dict[str, int]
