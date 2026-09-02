"""In-memory fake adapters for offline tests."""

from __future__ import annotations

import copy
from typing import Any


class FakeLogbook:
    """In-memory logbook matching LogbookPort."""

    def __init__(self) -> None:
        self.coverage: dict[str, Any] = {}
        self.artifacts: dict[tuple[int, str], Any] = {}
        self.decisions: list[tuple[int, str]] = []

    async def get_coverage(self) -> dict[str, Any]:
        return copy.deepcopy(self.coverage)

    async def put_coverage(self, coverage: dict[str, Any]) -> None:
        self.coverage = copy.deepcopy(coverage)

    async def get_wave_artifact(self, wave: int, name: str) -> Any | None:
        return self.artifacts.get((wave, name))

    async def put_wave_artifact(self, wave: int, name: str, data: Any) -> None:
        self.artifacts[(wave, name)] = copy.deepcopy(data)

    async def append_decision(self, wave: int, text: str) -> None:
        self.decisions.append((wave, text))


class FakeLLM:
    """Returns canned responses from fixtures."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        *,
        default: str = '{"status": "ok"}',
        fail_on: str | None = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default
        self._fail_on = fail_on
        self.calls: list[str] = []

    async def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        self.calls.append(prompt)
        if self._fail_on and self._fail_on in prompt:
            raise RuntimeError("rate_limit_exceeded")
        for key, value in self._responses.items():
            if key in prompt:
                return value
        return self._default

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeContentSafety:
    async def screen(self, text: str) -> dict[str, Any]:
        return {"blocked": False, "categories": {}}


class FakeTrainingSubmitter:
    def __init__(self) -> None:
        self.submissions: list[tuple[int, str]] = []

    async def submit(self, wave: int, *, export_path: str) -> str:
        self.submissions.append((wave, export_path))
        return f"job-fake-wave-{wave}"
