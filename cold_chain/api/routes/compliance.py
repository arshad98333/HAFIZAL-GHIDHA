"""Compliance Q&A chat -- ``POST /compliance/ask``.

Streams a 4-step reasoning chain (Intent Extraction & Law Anchoring →
Constraint & Variable Mapping → Strategic Counterfactual Analysis → Final
Recommendation Synthesis) over Server-Sent Events, each step a real,
independently-run K2-Think-v2 call grounded against this repo's own
guardrail pack and law citations -- see
``cold_chain/domain/compliance_qa.py`` for why the grounding step exists and
what it refuses to let the model do.

Every exchange is written to the ``qa_log`` Mongo collection
(``Logbook.write_qa_log``) once it finishes (success or failure) -- this is
audit trail, not a cache; nothing here reads it back for a later question.

Two extra SSE event types beyond the 4 reasoning steps:

- ``rate_limited`` -- K2's account tier has a low RPM ceiling (confirmed by
  request); a 429/backoff mid-chain is routine there, not a failure, so it's
  surfaced to the UI as "waiting", not silence or an error.
- ``eval`` -- after the final synthesis step, every rule ID the model cited
  is cross-checked against what was actually retrieved
  (``compliance_qa.evaluate_citations``) and reported before ``final``, so
  the UI can flag an answer that cites something outside the loaded
  guardrail pack.

SSE framing is hand-rolled (``event: <name>\\ndata: <json>\\n\\n``) rather than
via a dependency -- FastAPI's ``StreamingResponse`` with
``media_type="text/event-stream"`` is sufficient for this wire format and the
project already avoids adding dependencies where the standard library plus
what's already installed (httpx, FastAPI) covers it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from cold_chain.adapters import k2_client as k2
from cold_chain.adapters import logbook as lb
from cold_chain.api.deps import k2_dep, logbook_dep
from cold_chain.api.schemas import AskRequest
from cold_chain.domain import compliance_qa as qa
from cold_chain.observability.telemetry import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/compliance", tags=["compliance"])


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_chain(
    req: AskRequest,
    client: k2.K2Client,
    book: lb.Logbook,
) -> AsyncIterator[str]:
    ctx = qa.retrieve(req.question, jurisdiction=req.jurisdiction, product=req.product)
    context_block = qa.format_context_block(ctx)

    yield _sse(
        "context",
        {
            "jurisdiction": ctx.jurisdiction,
            "product": ctx.product,
            "requested_product": ctx.requested_product,
            "product_mismatch": ctx.product_mismatch,
            "matched_rule_ids": [r["rule_id"] for r in ctx.rules],
            "has_citation": ctx.citation is not None,
        },
    )

    step_records: list[dict[str, Any]] = []
    prior_outputs: dict[str, str] = {}
    overall_status = "succeeded"
    error_message: str | None = None
    total_retries = 0

    for step_id, title in qa.STEPS:
        yield _sse("step_start", {"id": step_id, "title": title})
        messages = qa.build_step_messages(
            step_id,
            question=req.question,
            context_block=context_block,
            prior_outputs=prior_outputs,
        )
        parts: list[str] = []
        try:
            async for event in client.stream_chat(messages):
                if event["type"] == "rate_limited":
                    total_retries += 1
                    yield _sse(
                        "rate_limited",
                        {
                            "id": step_id,
                            "attempt": event["attempt"],
                            "wait_s": event["wait_s"],
                            "reason": event["reason"],
                        },
                    )
                else:
                    parts.append(event["text"])
                    yield _sse("step_delta", {"id": step_id, "delta": event["text"]})
        except k2.K2Error as exc:
            error_message = str(exc)
            overall_status = "failed"
            yield _sse("step_error", {"id": step_id, "title": title, "error": error_message})
            step_records.append({"id": step_id, "title": title, "output": "".join(parts), "error": error_message})
            break

        output = "".join(parts)
        prior_outputs[step_id] = output
        step_records.append({"id": step_id, "title": title, "output": output, "error": None})
        yield _sse("step_done", {"id": step_id, "title": title, "output": output})

    final_answer = prior_outputs.get(qa.STEP_SYNTHESIS, "")
    citation_eval = qa.evaluate_citations(final_answer, ctx) if final_answer else None
    if citation_eval is not None:
        yield _sse("eval", citation_eval.to_dict())

    yield _sse(
        "final",
        {
            "status": overall_status,
            "answer": final_answer,
            "error": error_message,
        },
    )

    try:
        await book.write_qa_log(
            question=req.question,
            jurisdiction=ctx.jurisdiction,
            product=ctx.product,
            context_block=context_block,
            steps=step_records,
            status=overall_status,
            error=error_message,
            citation_eval=citation_eval.to_dict() if citation_eval is not None else None,
            retry_count=total_retries,
        )
    except Exception as exc:  # audit-log failure must never break the response the user already received
        log.warning("failed to write qa_log", extra={"extra_fields": {"error": str(exc)}})

    yield _sse("done", {})


@router.post("/ask")
async def ask(
    req: AskRequest,
    client: Annotated[k2.K2Client, Depends(k2_dep)],
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> StreamingResponse:
    if not client.enabled:
        raise HTTPException(
            status_code=503,
            detail="K2 is not configured on this deployment (K2_API_KEY unset).",
        )
    return StreamingResponse(
        _run_chain(req, client, book),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
