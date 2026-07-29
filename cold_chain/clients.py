"""Async clients for the Azure OpenAI endpoint plus content safety and the
deployed student model.

Concurrency is bounded per-client with a semaphore — the renderer/screener/
round-trip calls fan out per record, and an unbounded ``asyncio.gather`` over
a wave's worth of items is how you get rate-limited mid-wave and don't find
out why.

There is a single external LLM provider in this pipeline (Azure OpenAI). The
same ``AzureClient`` is reused both for the per-record render/screen/extract
loop and, at low concurrency, for the agentic judge calls in
``agentic_eval.py`` (self-consistency voting for language authenticity,
hallucination, and abstention quality). Keeping one provider instead of two
means one credential, one rate limit to reason about, and one thing to mock
in tests.
"""

from __future__ import annotations

import asyncio
from types import TracebackType

import httpx
import openai
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .config import Settings
from .telemetry import get_logger

log = get_logger(__name__)

# This project's Azure resource is a "New Foundry" project (see the Foundry
# portal's project settings), which serves models over the unified,
# OpenAI-SDK-compatible /openai/v1 surface rather than the older
# /openai/deployments/{name}/{op}?api-version=... REST route. Confirmed live:
# the old route's chat/completions call succeeded against this resource, but
# its embeddings call returned a bare 400 with every retry -- this project
# type does not serve embeddings on the legacy route at all. The v1 surface
# below is what the Foundry portal's own "Playground" code sample uses for
# this project, and is the only variant confirmed to work end-to-end here.
#
# Scope is "https://ai.azure.com/.default" for this surface, not
# "https://cognitiveservices.azure.com/.default" (the old route's scope) --
# they are not interchangeable for a Foundry project resource.
_AAD_SCOPE = "https://ai.azure.com/.default"

# Only genuinely transient failures are worth retrying. The previous version
# retried *any* HTTPStatusError, including a 400 -- which meant a real
# configuration defect (wrong deployment name, wrong route) silently burned
# five retries and 20+ seconds before failing, instead of failing fast on the
# first attempt with a clear error. A 400/401/403 is never fixed by retrying.
_RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    asyncio.TimeoutError,
)


def _extract_text(resp: object) -> str:
    """The Responses API's most direct accessor is ``output_text``; fall back
    to walking ``output`` for SDK/model combinations that don't populate it."""
    text = getattr(resp, "output_text", None)
    if text:
        return text
    for item in getattr(resp, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "text", None):
                return content.text
    return ""


class AzureClient:
    """gpt-5.4-mini on the UAE North Foundry endpoint, via the OpenAI-SDK
    v1 surface (see the module-level comment on ``_AAD_SCOPE`` for why this
    project's resource needs that surface specifically). Rendering, screening,
    round-trip extraction, and embeddings all go through the same client.

    Token acquisition and refresh are handled by azure-identity's own bearer
    token provider (it caches internally and refreshes ahead of expiry) --
    this class no longer manages a token cache itself.

    ``AsyncOpenAI`` awaits the result of calling ``api_key`` when it's
    callable -- confirmed live: passing azure-identity's plain synchronous
    ``get_bearer_token_provider`` result directly crashed every single
    request with "'str' object can't be awaited", because the SDK did
    ``await api_key()`` and got a plain string back, not a coroutine. The
    async wrapper below is what makes that ``await`` valid.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        sync_token_provider = get_bearer_token_provider(DefaultAzureCredential(), _AAD_SCOPE)

        async def _token_provider() -> str:
            return sync_token_provider()

        self._client = openai.AsyncOpenAI(
            base_url=f"{settings.azure_endpoint.rstrip('/')}/openai/v1",
            api_key=_token_provider,
            timeout=settings.azure_timeout_s,
        )
        self._sem = asyncio.Semaphore(settings.azure_max_concurrency)

    async def __aenter__(self) -> "AzureClient":
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                         tb: TracebackType | None) -> None:
        await self._client.close()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(8),
        wait=wait_exponential_jitter(initial=1, max=45),
        reraise=True,
    )
    async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 800,
                        temperature: float = 0.2, _ceiling: int = 4096) -> str:
        """gpt-5.4-mini is on a reasoning-tuned tier: a tight output-token
        budget can truncate mid-word (confirmed live: a 10-token screener call
        returned "CONS" instead of "CONSISTENT") or, less often, get fully
        consumed by hidden reasoning with empty content. Both retry once with
        a doubled budget rather than silently returning garbage the caller has
        no way to distinguish from a real answer."""
        async with self._sem:
            resp = await self._client.responses.create(
                model=self._settings.azure_deployment,
                instructions=system,
                input=prompt,
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            content = _extract_text(resp)
            incomplete = getattr(resp, "status", None) == "incomplete"
            if not content and incomplete and max_tokens * 2 <= _ceiling:
                log.warning("Azure completion truncated with no usable content; retrying with more headroom",
                            extra={"extra_fields": {"max_tokens": max_tokens, "retry_max_tokens": max_tokens * 2}})
                return await self.complete(prompt, system=system, max_tokens=max_tokens * 2,
                                            temperature=temperature, _ceiling=_ceiling)
            return content or ""

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._sem:
            resp = await self._client.embeddings.create(
                model=self._settings.azure_embedding_deployment,
                input=texts,
            )
            data = sorted(resp.data, key=lambda d: d.index)
            return [d.embedding for d in data]


class ContentSafetyClient:
    """Azure AI Content Safety, applied to rendered artifacts before they enter
    the corpus. Optional: if unconfigured, the screening stage logs a warning
    and skips the check rather than failing closed on a missing sidecar.
    """

    def __init__(self, settings: Settings):
        self._enabled = bool(settings.content_safety_endpoint and settings.content_safety_key)
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=30.0) if self._enabled else None

    async def __aenter__(self) -> "ContentSafetyClient":
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def is_safe(self, text: str) -> bool:
        if not self._enabled or self._http is None:
            return True
        resp = await self._http.post(
            f"{self._settings.content_safety_endpoint}/contentsafety/text:analyze?api-version=2024-09-01",
            headers={"Ocp-Apim-Subscription-Key": self._settings.content_safety_key},
            json={"text": text, "categories": ["Hate", "SelfHarm", "Sexual", "Violence"]},
        )
        resp.raise_for_status()
        results = resp.json().get("categoriesAnalysis", [])
        return all(r.get("severity", 0) < 4 for r in results)


class StudentClient:
    """The fine-tuned student model (``Settings.foundry_base_model`` -- any
    size, whatever this deployment configures), deployed behind an Azure ML /
    managed online endpoint. Used only by the automated Gate B
    (``agentic_eval.AutoGateB``) to get something to score — without a real
    deployed checkpoint this client has nothing to call, and the auto-gate
    reports that honestly rather than fabricating a pass.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._enabled = bool(settings.student_inference_endpoint and settings.student_inference_key)
        self._http = httpx.AsyncClient(timeout=30.0) if self._enabled else None
        self._sem = asyncio.Semaphore(16)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def __aenter__(self) -> "StudentClient":
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http is not None:
            await self._http.aclose()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=15),
        reraise=True,
    )
    async def predict(self, artifact_text: str) -> tuple[dict | None, str]:
        """Returns (parsed_json_or_None, raw_text). The serving contract is
        ours to define since we deploy this endpoint ourselves: a single
        `text` field in, strict JSON with `disposition` and the extracted
        fields out (constrained decoding is a standing constraint —
        AUTORESEARCH.md section 3 — so malformed output here is a real
        finding, not a parsing bug on this side)."""
        if not self._enabled or self._http is None:
            raise RuntimeError("no student inference endpoint configured")
        async with self._sem:
            resp = await self._http.post(
                self._settings.student_inference_endpoint,
                headers={"Authorization": f"Bearer {self._settings.student_inference_key}",
                         "Content-Type": "application/json"},
                json={"text": artifact_text},
            )
            resp.raise_for_status()
            raw = resp.text
            try:
                import json as _json
                start, end = raw.index("{"), raw.rindex("}") + 1
                return _json.loads(raw[start:end]), raw
            except Exception:
                return None, raw
