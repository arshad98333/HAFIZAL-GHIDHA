"""Port interfaces for external dependencies.

Every external system (MongoDB, Azure OpenAI, Content Safety, training) is
behind a protocol defined here. Production adapters live in ``adapters/``;
tests use ``adapters/fakes.py``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LogbookPort(Protocol):
    """Append-only logbook — MongoDB in production, in-memory in tests."""

    async def get_coverage(self) -> dict[str, Any]: ...

    async def put_coverage(self, coverage: dict[str, Any]) -> None: ...

    async def get_wave_artifact(self, wave: int, name: str) -> Any | None: ...

    async def put_wave_artifact(self, wave: int, name: str, data: Any) -> None: ...

    async def append_decision(self, wave: int, text: str) -> None: ...


@runtime_checkable
class LLMPort(Protocol):
    """Azure OpenAI render/screen/extract/judge surface."""

    async def complete(self, prompt: str, *, temperature: float = 0.0) -> str: ...

    async def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class ContentSafetyPort(Protocol):
    async def screen(self, text: str) -> dict[str, Any]: ...


@runtime_checkable
class TrainingSubmitterPort(Protocol):
    """Managed SFT job submission — Foundry in production, fake in tests."""

    async def submit(self, wave: int, *, export_path: str) -> str: ...
