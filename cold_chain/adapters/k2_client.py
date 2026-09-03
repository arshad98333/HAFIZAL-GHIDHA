"""K2-Think-v2 client (MBZUAI, ``api.k2think.ai``) -- a plain bearer-token,
OpenAI-compatible ``chat/completions`` endpoint. Structurally the same shape
as ``StudentClient`` in ``clients.py`` (optional, off if unconfigured), not
the AAD-token ``AzureClient`` -- K2 is a separate, simpler external provider
used only by the compliance Q&A chat (``cold_chain/domain/compliance_qa.py``,
``/compliance/ask``). It is not part of the training pipeline's rendering,
screening, or judging path -- see ``TESTING_REPORT_azure_review_migration.md``
for why K2 was removed from that path previously; this is a new, separate
use of the same provider.

Streaming is SSE (``data: {...}\\n\\n`` frames, terminated by
``data: [DONE]``), parsed by hand via httpx's ``aiter_lines()`` rather than a
new dependency -- the wire format is exactly what OpenAI-compatible chat
endpoints emit.

**Singleton, not per-request.** K2's account tier has a low requests-per-
minute ceiling relative to Azure's. If a fresh ``K2Client`` (and therefore a
fresh ``asyncio.Semaphore`` and a fresh httpx connection pool) were built per
request -- which is what a naive FastAPI ``Depends`` generator does -- the
concurrency cap would only apply *within* one request's own 4 chained
step-calls, not *across* concurrent users. Two people asking questions at
once would each get their own semaphore and both could burst past the real
account-wide RPM ceiling simultaneously. ``get_k2_client`` returns one
process-wide instance instead, so the semaphore and the retry/backoff below
actually gate the traffic K2 sees.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Literal, TypedDict

import httpx

from cold_chain.config import Settings
from cold_chain.observability.telemetry import get_logger

log = get_logger(__name__)


class K2Delta(TypedDict):
    type: Literal["delta"]
    text: str


class K2RateLimited(TypedDict):
    type: Literal["rate_limited"]
    attempt: int
    wait_s: float
    reason: str


K2StreamEvent = K2Delta | K2RateLimited

# K2's account tier is low-RPM -- confirmed by request (see module docstring).
# A 429 here is an expected, routine condition, not an outage; retry with
# backoff before yielding any content rather than failing the whole step on
# the first rate-limit response. Once streaming has actually started (first
# byte received), a failure is NOT retried here -- resending would duplicate
# partial output the caller may already have shown the user; the caller
# surfaces that as a step_error instead.
_MAX_CONNECT_ATTEMPTS = 5
_BACKOFF_BASE_S = 2.0
_BACKOFF_MAX_S = 30.0


class K2Error(RuntimeError):
    """K2 endpoint unreachable, unauthorized, or returned a malformed stream."""


def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    header = resp.headers.get("retry-after")
    if header:
        try:
            return max(0.5, float(header))
        except ValueError:
            pass
    backoff = min(_BACKOFF_MAX_S, _BACKOFF_BASE_S * (2 ** (attempt - 1)))
    return backoff + random.uniform(0, backoff * 0.25)


class K2Client:
    """MBZUAI K2-Think-v2, called only by the compliance Q&A chat. Disabled
    (raises ``K2Error`` on first use) if ``K2_API_KEY`` is unset -- callers
    should check ``.enabled`` before starting a conversation rather than
    relying on the exception alone, so the API can report a clean 503
    instead of a mid-stream failure."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._enabled = bool(settings.k2_api_key)
        self._sem = asyncio.Semaphore(max(1, settings.k2_max_concurrency))
        self._client: httpx.AsyncClient | None = None
        if self._enabled:
            self._client = httpx.AsyncClient(
                base_url=settings.k2_base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {settings.k2_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(180.0, connect=15.0),
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def __aenter__(self) -> K2Client:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
    ) -> AsyncIterator[K2StreamEvent]:
        """Yields ``K2StreamEvent``s: ``{"type": "delta", "text": ...}`` for
        each incremental chunk of K2's answer, and ``{"type":
        "rate_limited", "attempt": ..., "wait_s": ..., "reason": ...}``
        whenever a 429/5xx/connection failure triggers a backoff-and-retry
        *before any content has been yielded* -- callers (the
        ``/compliance/ask`` route) turn the latter into a ``rate_limited``
        SSE event so the UI shows *why* it's waiting instead of going silent,
        which matters on K2's low-RPM tier where a multi-second wait is
        routine, not a failure.

        Raises ``K2Error`` if the client is disabled, every retry is
        exhausted, or the endpoint fails after streaming has already begun
        (not retried, to avoid duplicating partial output already shown).
        """
        if not self._enabled or self._client is None:
            raise K2Error("K2 is not configured (K2_API_KEY unset)")

        payload = {
            "model": self._settings.k2_model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }

        async with self._sem:
            attempt = 0
            while True:
                attempt += 1
                started_yielding = False
                try:
                    async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                        if resp.status_code == 429 or resp.status_code >= 500:
                            wait_s = _retry_after_seconds(resp, attempt)
                            body = await resp.aread()
                            reason = f"HTTP {resp.status_code}: {body.decode(errors='replace')[:200]}"
                            if attempt >= _MAX_CONNECT_ATTEMPTS:
                                raise K2Error(f"K2 rate-limited/unavailable after {attempt} attempts: {reason}")
                            log.warning(
                                "K2 rate-limited or unavailable, retrying",
                                extra={"extra_fields": {"attempt": attempt, "wait_s": wait_s, "reason": reason}},
                            )
                            yield K2RateLimited(type="rate_limited", attempt=attempt, wait_s=wait_s, reason=reason)
                            await asyncio.sleep(wait_s)
                            continue
                        if resp.status_code >= 400:
                            body = await resp.aread()
                            raise K2Error(
                                f"K2 request failed ({resp.status_code}): {body.decode(errors='replace')[:500]}"
                            )

                        async for line in resp.aiter_lines():
                            line = line.strip()
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[len("data:") :].strip()
                            if data == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                log.warning(
                                    "K2 stream: unparseable chunk",
                                    extra={"extra_fields": {"raw": data[:200]}},
                                )
                                continue
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}
                            text = delta.get("content")
                            if text:
                                started_yielding = True
                                yield K2Delta(type="delta", text=text)
                        return
                except httpx.HTTPError as exc:
                    if started_yielding or attempt >= _MAX_CONNECT_ATTEMPTS:
                        raise K2Error(f"K2 connection failed: {exc}") from exc
                    wait_s = _retry_after_seconds_from_exc(attempt)
                    log.warning(
                        "K2 connection error, retrying",
                        extra={"extra_fields": {"attempt": attempt, "wait_s": wait_s, "error": str(exc)}},
                    )
                    yield K2RateLimited(type="rate_limited", attempt=attempt, wait_s=wait_s, reason=str(exc))
                    await asyncio.sleep(wait_s)
                    continue

    async def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
        """Non-streaming convenience wrapper (collects the full stream,
        discarding rate_limited events). The live UI path uses
        ``stream_chat`` directly so it can surface those events; this exists
        for tests and any future non-streaming caller."""
        parts: list[str] = []
        async for event in self.stream_chat(messages, temperature=temperature):
            if event["type"] == "delta":
                parts.append(event["text"])
        return "".join(parts)


def _retry_after_seconds_from_exc(attempt: int) -> float:
    backoff = min(_BACKOFF_MAX_S, _BACKOFF_BASE_S * (2 ** (attempt - 1)))
    return backoff + random.uniform(0, backoff * 0.25)


_singleton: K2Client | None = None
_singleton_lock = asyncio.Lock()


async def get_k2_client(settings: Settings) -> K2Client:
    """Process-wide K2Client. See the module docstring's "Singleton, not
    per-request" note for why this must not be a fresh instance per request."""
    global _singleton
    if _singleton is not None:
        return _singleton
    async with _singleton_lock:
        if _singleton is None:
            _singleton = K2Client(settings)
        return _singleton
