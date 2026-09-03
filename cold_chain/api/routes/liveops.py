"""LiveOps -- ``POST /liveops/scenario`` and ``POST /liveops/narrate``.

A random "truck scenario" generator plus a 3-step grounded narration
(What Happened -> The Problem -> GSO-Aligned Solution), streamed the same
way as ``/compliance/ask``. See ``cold_chain/domain/liveops.py`` for why
scenario generation and disposition are deterministic (never LLM-decided)
and how a real-time feed (Azure IoT Hub) could later replace the synthetic
generator without touching narration.

This route is deliberately stateless: ``/liveops/scenario`` returns a full
scenario payload, and the client posts that same payload back to
``/liveops/narrate`` (plus an optional officer note) rather than the server
holding scenario state in memory or Mongo keyed by ``scenario_id``. That
mirrors how ``/simulate`` already works and avoids a second kind of
server-side session for what is, at this scale, one round trip.

Every narration is written to the ``qa_log`` collection (LiveOps entries are
tagged ``kind: "liveops"`` in that same collection so there is one audit
trail for every K2-touching feature, not two to keep in sync) once it
finishes.
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
from cold_chain.api.schemas import LiveOpsNarrateRequest, LiveOpsScenarioResponse
from cold_chain.domain import compliance_qa as qa
from cold_chain.domain import liveops as lo
from cold_chain.observability.telemetry import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/liveops", tags=["liveops"])


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _scenario_from_request(req: LiveOpsNarrateRequest) -> lo.TruckScenario:
    return lo.TruckScenario(
        scenario_id=req.scenario_id,
        source=req.source,
        truck_id=req.truck_id,
        product=req.product,
        jurisdiction=req.jurisdiction,
        fault_mode=req.fault_mode,
        artifact_type=req.artifact_type,
        seed=req.seed,
        readings_c=req.readings_c,
        interval_min=req.interval_min,
        ambient_c=req.ambient_c,
        days_since_production=req.days_since_production,
        sensor_fault=req.sensor_fault,
        peak_season=req.peak_season,
        disposition=req.disposition,
        rule_id=req.rule_id,
        excursion_minutes=req.excursion_minutes,
        peak_temp_c=req.peak_temp_c,
        remaining_shelf_days=req.remaining_shelf_days,
        temp_band_min_c=req.temp_band_min_c,
        temp_band_max_c=req.temp_band_max_c,
        spec_regime=req.spec_regime,
        spec_clause=req.spec_clause,
        narrative_opening=req.narrative_opening,
        generated_at=req.generated_at,
    )


@router.post("/scenario", response_model=LiveOpsScenarioResponse)
def scenario() -> LiveOpsScenarioResponse:
    """A brand-new random truck scenario -- deterministic physics + rules
    engine, same pipeline the Simulation page uses, just randomized."""
    s = lo.generate_random_scenario()
    return LiveOpsScenarioResponse(**s.to_dict())


async def _run_narration(
    req: LiveOpsNarrateRequest,
    client: k2.K2Client,
    book: lb.Logbook,
) -> AsyncIterator[str]:
    scenario_obj = _scenario_from_request(req)
    question_text = lo.scenario_question_text(scenario_obj, req.officer_note)
    ctx = qa.retrieve(question_text, jurisdiction=scenario_obj.jurisdiction, product=scenario_obj.product)
    context_block = qa.format_context_block(ctx)

    yield _sse(
        "context",
        {
            "scenario_id": scenario_obj.scenario_id,
            "jurisdiction": ctx.jurisdiction,
            "product": ctx.product,
            "matched_rule_ids": [r["rule_id"] for r in ctx.rules],
            "has_citation": ctx.citation is not None,
        },
    )

    step_records: list[dict[str, Any]] = []
    prior_outputs: dict[str, str] = {}
    overall_status = "succeeded"
    error_message: str | None = None
    total_retries = 0

    for step_id, title in lo.LIVEOPS_STEPS:
        yield _sse("step_start", {"id": step_id, "title": title})
        messages = lo.build_narration_messages(
            step_id,
            scenario=scenario_obj,
            context_block=context_block,
            officer_note=req.officer_note,
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

    final_answer = prior_outputs.get(lo.STEP_GSO_SOLUTION, "")
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
            question=question_text,
            jurisdiction=ctx.jurisdiction,
            product=ctx.product,
            context_block=context_block,
            steps=step_records,
            status=overall_status,
            error=error_message,
            citation_eval=citation_eval.to_dict() if citation_eval is not None else None,
            retry_count=total_retries,
            kind="liveops",
            scenario=scenario_obj.to_dict(),
        )
    except Exception as exc:  # audit-log failure must never break the response already sent
        log.warning("failed to write liveops qa_log", extra={"extra_fields": {"error": str(exc)}})

    yield _sse("done", {})


@router.post("/narrate")
async def narrate(
    req: LiveOpsNarrateRequest,
    client: Annotated[k2.K2Client, Depends(k2_dep)],
    book: Annotated[lb.Logbook, Depends(logbook_dep)],
) -> StreamingResponse:
    if not client.enabled:
        raise HTTPException(
            status_code=503,
            detail="K2 is not configured on this deployment (K2_API_KEY unset).",
        )
    return StreamingResponse(
        _run_narration(req, client, book),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
