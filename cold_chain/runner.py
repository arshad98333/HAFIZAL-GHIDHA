"""Wave runner. One wave = one pass of the loop.

    plan -> synthesize -> label -> render -> screen -> guardrail check
         -> GATE A (agentic review board) -> train (managed SFT submit)
         -> GATE B (agentic gatekeeper) -> triage -> ledger

Gate A and Gate B can halt the pipeline; that is their entire purpose. A runner
that cannot stop itself is just a fast way to generate 5,304 rows of the first
wave's defects.

    python -m cold_chain.runner plan     --wave 1
    python -m cold_chain.runner generate --wave 1
    python -m cold_chain.runner gate-a   --wave 1
    python -m cold_chain.runner train    --wave 1
    python -m cold_chain.runner gate-b   --wave 1

Gate B defaults to the agentic path: the Azure judge model is the gatekeeper,
scoring the student's holdout predictions with self-consistency voting
(``agentic_eval.AutoGateB``), no human file required. Pass
``--results <path>`` to fall back to the original human-sealed-eval path
instead, for teams that still want a periodic human sign-off — see
``agentic_eval.py``'s module docstring for exactly what removing the human
trades away and how the voting/escalation/audit-trail machinery mitigates it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from . import agentic_eval, curriculum, gates, guardrails
from . import knowledge_base as kb
from . import logbook as lb
from . import simulate
from .clients import AzureClient, ContentSafetyClient, StudentClient
from .config import Settings, get_settings
from .rules_engine import engine_sha, label as rule_label
from .telemetry import attach_mongo_sink, configure_logging, get_logger, get_run_id, log_extra, set_wave

log = get_logger(__name__)

# Confirmed against the live endpoint: 64 (bounded further by AzureClient's own
# 32-slot semaphore) still sustained a 429 storm that lost 171/652 items (26%) of
# a real wave outright. This account's actual throughput is well below either
# number -- tune AZURE_MAX_CONCURRENCY in .env upward only after confirming the
# real TPM/RPM quota on the deployment, not by guessing.
LOCAL_CONCURRENCY = 8
HOLDOUT_FRACTION = 0.05  # kept records never counted toward the training set


class WaveHalted(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #

def _round_robin(counts: dict[str, int]) -> list[str]:
    """Expands {"AE": 45, "SA": 45, ...} into a 180-item list, interleaved
    rather than blocked, so a mid-wave crash still leaves a balanced partial."""
    remaining = dict(counts)
    order = list(counts)
    out: list[str] = []
    while any(remaining.values()):
        for k in order:
            if remaining[k] > 0:
                out.append(k)
                remaining[k] -= 1
    return out


def _prompt_template_hash(language: str, artifact_type: str) -> str:
    payload = simulate._LANG_INSTRUCTION[language] + simulate._ARTIFACT_INSTRUCTION[artifact_type]
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _expand_allocation(alloc: dict[str, Any], wave: int) -> list[simulate.GenerationRequest]:
    n = alloc["count"]
    cell = lb.cell_key(alloc["product"], alloc["fault_mode"])
    langs = _round_robin(alloc["language_split"])
    artifacts = _round_robin(alloc["artifact_split"])
    jurisdictions = _round_robin(alloc.get("jurisdiction_split") or {j: 1 for j in lb.JURISDICTIONS})
    if len(jurisdictions) < n:
        # Older plan.json without jurisdiction_split, or a split shorter than
        # n (shouldn't happen from curriculum.build_plan, but stay defensive
        # for hand-edited plans): round-robin repeat rather than index out of range.
        jurisdictions = [jurisdictions[i % len(jurisdictions)] for i in range(n)]
    rng = random.Random(f"{wave}:{cell}")

    idx = list(range(n))
    rng.shuffle(idx)
    adversarial_idx = set(idx[: alloc["adversarial"]])
    abstention_idx = set(idx[alloc["adversarial"]: alloc["adversarial"] + alloc["abstention"]])

    reqs = []
    for i in range(n):
        seed = int(hashlib.sha256(f"{wave}:{cell}:{i}".encode()).hexdigest()[:12], 16)
        reqs.append(simulate.GenerationRequest(
            product=alloc["product"],
            fault_mode=alloc["fault_mode"],
            language=langs[i],
            artifact_type=artifacts[i],
            jurisdiction=jurisdictions[i],
            is_adversarial=i in adversarial_idx,
            is_abstention=i in abstention_idx,
            rng_seed=seed,
        ))
    return reqs


READING_TOLERANCE_C = 1.5


def _round_trip_check(state, extracted: dict[str, Any] | None) -> tuple[bool, float]:
    """Range-coverage comparison, not positional. Confirmed against the live
    endpoint: a chat-message artifact summarizes a 96-point series as "between
    0.82 and 3.19", and an extractor that correctly recovers exactly that
    range still fails an index-by-index comparison against src[0], src[1] --
    those aren't the min/max, they're just the first two raw readings. Range
    coverage is the metric that is actually true for both a verbatim CSV dump
    (logger_csv) and a paraphrased summary (chat_message/voice_note/qc_form_ocr).

    Returns (passed, confidence). ``passed`` is the existing pass/fail tolerance
    check; ``confidence`` is a continuous 0-1 score for how close the match was
    -- a record can pass at 1.49C of error (just inside the 1.5C tolerance) and
    that is a real pass but a weak one. The confidence gate (settings.
    min_round_trip_confidence) catches those separately from the hard pass/fail."""
    if extracted is None:
        return False, 0.0
    if extracted.get("product") != state.product:
        return False, 0.0
    if "readings_c" in state.missing_fields:
        ok = not extracted.get("readings_c")
        return ok, (1.0 if ok else 0.0)
    src = state.readings_c
    got = extracted.get("readings_c") or []
    if not src or not got:
        ok = not src and not got
        return ok, (1.0 if ok else 0.0)
    min_err = abs(min(src) - min(got))
    max_err = abs(max(src) - max(got))
    passed = min_err < READING_TOLERANCE_C and max_err < READING_TOLERANCE_C
    confidence = max(0.0, 1.0 - (min_err + max_err) / (2 * READING_TOLERANCE_C))
    return passed, confidence


async def _generate_one(
    req: simulate.GenerationRequest, wave: int, azure: AzureClient, safety: ContentSafetyClient,
    book: lb.Logbook, engine_sha_val: str, settings: Settings,
) -> None:
    cell = lb.cell_key(req.product, req.fault_mode)
    envelope = lb.Envelope(
        state_id=str(uuid.uuid4()),
        wave=wave,
        cell=cell,
        language=req.language,
        artifact_type=req.artifact_type,
        jurisdiction=req.jurisdiction,
        is_adversarial=req.is_adversarial,
        is_abstention=req.is_abstention,
        rng_seed=req.rng_seed,
        rule_engine_sha=engine_sha_val,
        prompt_template_hash=_prompt_template_hash(req.language, req.artifact_type),
        generator_model="synthetic-physics-v1",
        renderer_model="gpt-5.4-mini",
    )
    try:
        state = simulate.synthesize(req)
        disposition = rule_label(state).disposition

        rendered = await azure.complete(
            simulate.render_prompt(state, req.language, req.artifact_type, req.jurisdiction),
            max_tokens=simulate.render_max_tokens(req.artifact_type),
        )

        if not await safety.is_safe(rendered):
            await book.write_generation(envelope, "dropped_safety",
                                         extra={"disposition": disposition, "rendered_text": rendered[:4000]})
            return

        # confirmed against the live endpoint: 10 tokens truncates mid-word ("CONS" instead
        # of "CONSISTENT") depending on how the tokenizer splits the verdict word -- not a
        # reasoning-budget issue this time, just not enough room for the longest verdict.
        verdict_raw = await azure.complete(simulate.screener_prompt(rendered), max_tokens=30, temperature=0.0)
        verdict = verdict_raw.strip().upper()
        envelope.screener_verdict = verdict if verdict in ("CONSISTENT", "INCONSISTENT", "LEAKS_LABEL") else "UNPARSEABLE"
        if envelope.screener_verdict != "CONSISTENT":
            await book.write_generation(envelope, "dropped_screener",
                                         extra={"disposition": disposition, "rendered_text": rendered[:4000],
                                                "screener_verdict": envelope.screener_verdict})
            return

        # guardrails.check_artifact_text: an independent, dependency-free regex net
        # (metadata leakage / expedite_sale wording / truncated logger_csv tail) run in
        # addition to the LLM screener above, not instead of it -- see guardrails.py's
        # module docstring and gates.GATE_A["guardrail_violation_rate"].
        guardrail_hits = guardrails.check_artifact_text(rendered, req.artifact_type)
        if guardrail_hits:
            await book.write_generation(
                envelope, "dropped_guardrail",
                extra={"disposition": disposition, "rendered_text": rendered[:4000],
                       "screener_verdict": envelope.screener_verdict,
                       "guardrail_violations": [{"rule_id": v.rule_id, "detail": v.detail} for v in guardrail_hits]},
            )
            return

        extracted_raw = await azure.complete(simulate.extraction_prompt(rendered),
                                              max_tokens=simulate.extraction_max_tokens(req.artifact_type),
                                              temperature=0.0)
        schema_valid, extracted = _validate_extraction(extracted_raw)
        if not schema_valid:
            await book.write_generation(envelope, "dropped_schema",
                                         extra={"disposition": disposition, "rendered_text": rendered[:4000],
                                                "screener_verdict": envelope.screener_verdict, "schema_valid": False})
            return

        round_trip, confidence = _round_trip_check(state, extracted)
        envelope.round_trip_ok = round_trip
        if not round_trip:
            await book.write_generation(envelope, "dropped_roundtrip",
                                         extra={"disposition": disposition, "rendered_text": rendered[:4000],
                                                "screener_verdict": envelope.screener_verdict, "schema_valid": True,
                                                "confidence": confidence})
            return

        if confidence < settings.min_round_trip_confidence:
            await book.write_generation(envelope, "dropped_low_confidence",
                                         extra={"disposition": disposition, "rendered_text": rendered[:4000],
                                                "screener_verdict": envelope.screener_verdict, "schema_valid": True,
                                                "confidence": confidence})
            return

        legal = kb.citation(req.jurisdiction)
        await book.write_generation(envelope, "kept",
                                     extra={"disposition": disposition, "rendered_text": rendered[:4000],
                                            "screener_verdict": envelope.screener_verdict, "schema_valid": True,
                                            "confidence": confidence,
                                            "legal_citation": {"jurisdiction": legal.jurisdiction,
                                                                "instrument": legal.instrument,
                                                                "authority": legal.authority}})
    except Exception as exc:  # noqa: BLE001 — one bad item must not sink the wave
        log_extra(log, 40, "generation item failed", cell=cell, error=str(exc))
        await book.write_generation(envelope, "dropped_error", note=str(exc)[:500])


def _validate_extraction(raw: str) -> tuple[bool, dict[str, Any] | None]:
    import jsonschema

    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        parsed = json.loads(raw[start:end])
        jsonschema.validate(parsed, simulate.EXTRACTION_SCHEMA)
        return True, parsed
    except Exception:
        return False, None


async def stage_generate(wave: int, plan: dict[str, Any], book: lb.Logbook,
                          azure: AzureClient, safety: ContentSafetyClient, settings: Settings,
                          rate_per_minute: int | None = None, max_records: int | None = None) -> None:
    """``rate_per_minute`` paces how often a new item is *dispatched*, not a
    concurrency cap -- confirmed against the live endpoint: even with
    LOCAL_CONCURRENCY down at 8, dispatching all items via one asyncio.gather
    still produced synchronized bursts (8 items all making their first Azure
    call within milliseconds of each other), which is what actually trips a
    per-second rate limit. Spacing out *starts* keeps in-flight calls low
    without needing to know the account's exact quota."""
    engine_sha_val = engine_sha()
    all_reqs = [req for alloc in plan["allocations"] for req in _expand_allocation(alloc, wave)]
    if max_records is not None:
        all_reqs = all_reqs[:max_records]
    log_extra(log, 20, "generation start", rule_engine_sha=engine_sha_val, total=len(all_reqs),
              rate_per_minute=rate_per_minute)

    sem = asyncio.Semaphore(LOCAL_CONCURRENCY)

    async def guarded(req: simulate.GenerationRequest) -> None:
        async with sem:
            await _generate_one(req, wave, azure, safety, book, engine_sha_val, settings)

    interval_s = 60.0 / rate_per_minute if rate_per_minute else 0.0
    tasks = []
    for i, req in enumerate(all_reqs):
        tasks.append(asyncio.create_task(guarded(req)))
        if interval_s and i < len(all_reqs) - 1:
            await asyncio.sleep(interval_s)
        if (i + 1) % 25 == 0:
            log_extra(log, 20, "generation progress", dispatched=i + 1, total=len(all_reqs))

    await asyncio.gather(*tasks)
    await book.flush_generation()
    await book.update_coverage(wave)
    log_extra(log, 20, "generation complete", n=len(all_reqs))


# --------------------------------------------------------------------------- #
# Gate A
# --------------------------------------------------------------------------- #

async def _gate_a_metrics(wave: int, plan: dict[str, Any], book: lb.Logbook, azure: AzureClient,
                           settings: Settings) -> dict[str, float]:
    rows = await book.read_generation(wave)
    kept = [r for r in rows if r["outcome"] == "kept"]
    attempted = len(rows) or 1

    kept_by_cell: dict[str, int] = Counter(r["cell"] for r in kept)
    texts = [r.get("rendered_text", "") for r in kept]
    labels = [r.get("disposition", "") for r in kept]
    artifact_types = [r.get("artifact_type") for r in kept]

    metrics: dict[str, float] = {
        "schema_validity": sum(1 for r in rows if r.get("schema_valid")) / attempted,
        "round_trip_recovery": (sum(1 for r in kept if r.get("round_trip_ok")) / len(kept)) if kept else 0.0,
        "screener_flag_rate": sum(1 for r in rows if r.get("screener_verdict") not in (None, "CONSISTENT")) / attempted,
        "cell_fill_deviation": gates.cell_fill_deviation(plan, kept_by_cell),
        "max_class_share": gates.max_class_share(labels),
        "guardrail_violation_rate": gates.guardrail_violation_rate(texts, artifact_types),
    }

    if texts:
        # near_duplicate_rate depends on the embeddings endpoint, which is a
        # separate deployment from chat/completions and can be down or
        # misconfigured independently of it (confirmed live: an embeddings
        # 400 previously crashed this entire command before any other Gate A
        # metric was even computed). One dependency failing here must degrade
        # to "not measured" for that one check -- gates.evaluate() already
        # treats a missing key as a failed check -- rather than taking down
        # every other metric in the same run.
        try:
            embeddings = await azure.embed(texts)
            metrics["near_duplicate_rate"] = await gates.near_duplicate_rate_async(texts, lambda _t: embeddings)
        except Exception as exc:  # noqa: BLE001
            log_extra(log, 40, "embeddings call failed; near_duplicate_rate not measured this run",
                      error=str(exc))
        metrics["leakage_probe_acc"] = await gates.leakage_probe_async(texts, labels)
    else:
        metrics["near_duplicate_rate"] = 1.0
        metrics["leakage_probe_acc"] = 1.0

    # language_authenticity / annotator_kappa: a human-supplied hitl.json still wins
    # if present (a team can choose to keep sampling this by hand); otherwise the
    # agentic review board judges it automatically — no blocking human step required.
    hitl = await book.read_json(wave, "hitl.json") or {}
    if "language_authenticity" in hitl and "annotator_kappa" in hitl:
        metrics["language_authenticity"] = hitl["language_authenticity"]
        metrics["annotator_kappa"] = hitl["annotator_kappa"]
        log_extra(log, 20, "Gate A qualitative review: human hitl.json", wave=wave)
    elif texts:
        board = agentic_eval.AgenticReviewBoard(azure, settings.judge_votes, settings.judge_agreement_floor)
        review = await board.review(texts)
        await book.write_json(wave, "agentic_review.json", review)
        # A consensus of None means every judge vote failed (rate-limited, transport
        # error, unparseable) -- that is "not measured", the same as a human never
        # having sampled it, not a 0/5/whatever score. gates.evaluate already treats a
        # missing key as a measured failure; passing None through would instead crash
        # the numeric comparison (`None >= 3.5`).
        if review["language_authenticity"] is not None:
            metrics["language_authenticity"] = review["language_authenticity"]
        if review["annotator_kappa"] is not None:
            metrics["annotator_kappa"] = review["annotator_kappa"]
        log_extra(log, 20, "Gate A qualitative review: agentic board", wave=wave,
                  language_authenticity=review["language_authenticity"],
                  agreement=review["language_authenticity_agreement"],
                  escalated=review["language_authenticity_escalated"])

    return metrics


async def stage_gate_a(wave: int, plan: dict[str, Any], book: lb.Logbook, azure: AzureClient,
                        settings: Settings) -> dict[str, Any]:
    metrics = await _gate_a_metrics(wave, plan, book, azure, settings)
    result = gates.evaluate(metrics, gates.GATE_A)
    await book.write_json(wave, "gate_a.json", {"metrics": metrics, **result})
    await book.append_decisions(wave, _gate_markdown("Gate A -- data", result))
    if not result["passed"]:
        raise WaveHalted("Gate A failed:\n  " + "\n  ".join(result["failures"]))
    log_extra(log, 20, "Gate A passed")
    return result


# --------------------------------------------------------------------------- #
# training submission (managed compute)
# --------------------------------------------------------------------------- #

async def stage_train(wave: int, settings: Settings, book: lb.Logbook, dataset_hash: str) -> dict[str, Any]:
    """Submits the SFT job. The actual training script and the AutoResearch
    ratchet loop (AUTORESEARCH.md) run inside the training job container, not
    in this process — this stage's job is to submit and tag it.

    ``settings.training_region`` and ``settings.foundry_base_model`` are
    whatever this deployment configures them to be; neither is pinned or
    validated here -- fill in the region and base checkpoint this run
    actually targets in ``.env``.

    NOTE: verify the current azure-ai-ml job submission surface against the
    live SDK docs before wiring this against a real workspace; the API has
    moved repeatedly (see PRD section 7.4).
    """

    def _submit() -> dict[str, Any]:
        from azure.ai.ml import MLClient, command
        from azure.identity import DefaultAzureCredential

        # `config.json` (subscription/resource group/workspace) is expected next to the
        # process cwd in the Foundry job container. Swap for an explicit MLClient(...)
        # constructor if running this outside that container.
        ml_client = MLClient.from_config(credential=DefaultAzureCredential())
        job = command(
            code=".",
            command="python -m training.sft --wave ${{inputs.wave}} --base-model ${{inputs.base_model}}",
            inputs={"wave": wave, "base_model": settings.foundry_base_model},
            compute=settings.foundry_compute_cluster,
            environment="azureml:cold-chain-sft@latest",
            tags={
                "rules_engine_sha": engine_sha(),
                "dataset_hash": dataset_hash,
                "wave": str(wave),
                "region": settings.training_region,
            },
            display_name=f"cold-chain-sft-wave-{wave:02d}",
        )
        submitted = ml_client.jobs.create_or_update(job)
        return {"job_name": submitted.name, "status": submitted.status}

    result = await asyncio.to_thread(_submit)
    await book.write_json(wave, "train_submission.json", result)
    log_extra(log, 20, "training job submitted", **result)
    return result


# --------------------------------------------------------------------------- #
# Gate B (human-supplied results — agents never execute the sealed eval)
# --------------------------------------------------------------------------- #

async def stage_gate_b(wave: int, results_path: Path, book: lb.Logbook) -> tuple[dict[str, Any], gates.SliceResult]:
    payload_in = json.loads(results_path.read_text(encoding="utf-8"))
    metrics: dict[str, float] = payload_in["metrics"]
    cell_f1: dict[str, float] = payload_in["cell_f1"]
    confusions = Counter({tuple(k): v for k, v in payload_in.get("confusions", [])})

    slices = gates.summarise_slices(cell_f1, confusions)
    led = await book.read_ledger()
    prev = gates.summarise_slices(led[-1]["cell_f1"], Counter()) if led and led[-1].get("cell_f1") else None
    ok, why = gates.ratchet_ok(slices, prev)

    result = gates.evaluate(metrics, gates.GATE_B)
    payload = {
        "metrics": metrics,
        "worst_cell": slices.worst_cell,
        "worst_cell_f1": slices.worst_cell_f1,
        "cells_passing": slices.cells_passing,
        "mean_f1": slices.mean_f1,
        "cell_f1": slices.cell_f1,
        "top_confusions": slices.top_confusions,
        "ratchet_ok": ok,
        "ratchet_note": why,
        **result,
    }
    await book.write_json(wave, "gate_b.json", payload)
    await book.append_decisions(
        wave,
        _gate_markdown("Gate B -- model", result)
        + f"\nRatchet: {why}\nWorst cell: {slices.worst_cell} @ {slices.worst_cell_f1:.3f}\n",
    )
    if not result["passed"] or not ok:
        raise WaveHalted(f"Gate B failed: {'; '.join(result['failures']) or why}")
    log_extra(log, 20, "Gate B passed", note=why)
    return payload, slices


# --------------------------------------------------------------------------- #
# Gate B, agentic path — the Azure judge model as the automated gatekeeper. Default.
# --------------------------------------------------------------------------- #

def _is_holdout(state_id: str) -> bool:
    """Deterministic ~HOLDOUT_FRACTION split, never trained on. The training
    script is expected to exclude any record where this is true — that
    contract lives here and in AUTORESEARCH.md, not enforced by this process."""
    bucket = int(hashlib.sha256(state_id.encode()).hexdigest()[:8], 16) % 100
    return bucket < int(HOLDOUT_FRACTION * 100)


def _macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    from sklearn.metrics import f1_score

    if not y_true:
        return 0.0
    labels = sorted(set(y_true) | set(y_pred))
    return float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))


async def _build_holdout_items(waves: list[int], book: lb.Logbook, student: StudentClient,
                                sem: asyncio.Semaphore) -> list[agentic_eval.HoldoutItem]:
    items: list[agentic_eval.HoldoutItem] = []

    async def _one(row: dict[str, Any]) -> None:
        async with sem:
            parsed, raw = await student.predict(row.get("rendered_text", ""))
            items.append(agentic_eval.HoldoutItem(
                cell=row["cell"],
                wave=row["wave"],
                language=row["language"],
                jurisdiction=row.get("jurisdiction", ""),
                is_adversarial=row.get("is_adversarial", False),
                is_abstention=row.get("is_abstention", False),
                artifact_text=row.get("rendered_text", ""),
                ground_truth_disposition=row.get("disposition", ""),
                model_output=parsed,
                model_output_raw=raw,
            ))

    tasks = []
    for w in waves:
        rows = await book.read_generation(w)
        for r in rows:
            if r["outcome"] == "kept" and _is_holdout(r["state_id"]):
                tasks.append(_one(r))
    await asyncio.gather(*tasks)
    return items


def _slice_f1_gap(items: list[agentic_eval.HoldoutItem], in_group: Any) -> float:
    """abs(F1 of the group matching ``in_group`` minus F1 of the rest). Used
    for adversarial_gap: same shape of question, different partition."""
    a = [(i.ground_truth_disposition, (i.model_output or {}).get("disposition", "")) for i in items if in_group(i)]
    b = [(i.ground_truth_disposition, (i.model_output or {}).get("disposition", "")) for i in items if not in_group(i)]
    if not a or not b:
        return 0.0
    f1_a = _macro_f1([x[0] for x in a], [x[1] for x in a])
    f1_b = _macro_f1([x[0] for x in b], [x[1] for x in b])
    return abs(f1_a - f1_b)


_MIN_JURISDICTION_SLICE = 5  # too few holdout items in a state to trust its F1


def _cross_jurisdiction_delta(items: list[agentic_eval.HoldoutItem]) -> float:
    """Max F1 gap between any two GCC states with enough holdout items to
    measure. Replaces the retired language-axis cross_language_delta -- see
    gates.GATE_B."""
    by_jurisdiction: dict[str, list[tuple[str, str]]] = {}
    for i in items:
        by_jurisdiction.setdefault(i.jurisdiction, []).append(
            (i.ground_truth_disposition, (i.model_output or {}).get("disposition", ""))
        )
    f1s = [
        _macro_f1([p[0] for p in pairs], [p[1] for p in pairs])
        for pairs in by_jurisdiction.values()
        if len(pairs) >= _MIN_JURISDICTION_SLICE
    ]
    return (max(f1s) - min(f1s)) if len(f1s) >= 2 else 0.0


async def stage_gate_b_auto(wave: int, book: lb.Logbook, azure: AzureClient, student: StudentClient,
                             settings: Settings) -> tuple[dict[str, Any], gates.SliceResult]:
    if not student.enabled:
        raise WaveHalted(
            "no student inference endpoint configured (STUDENT_INFERENCE_ENDPOINT / "
            "STUDENT_INFERENCE_KEY) -- the agentic Gate B has nothing to score. Deploy "
            "the wave's fine-tuned checkpoint to a Foundry/Azure ML online endpoint first, "
            "or fall back to `gate-b --results <path>` for the human-sealed-eval path."
        )

    sem = asyncio.Semaphore(16)
    items = await _build_holdout_items(list(range(1, wave + 1)), book, student, sem)
    if not items:
        raise WaveHalted(f"no holdout items available across waves 1..{wave}; nothing to auto-gate")

    judge = agentic_eval.AutoGateB(azure, settings.judge_votes, settings.judge_agreement_floor)
    result_payload = await judge.run(items)
    await book.write_deliberation(wave, result_payload["deliberation"])

    metrics = result_payload["metrics"]
    metrics["cross_jurisdiction_delta"] = _cross_jurisdiction_delta(items)
    metrics["adversarial_gap"] = _slice_f1_gap(items, lambda i: not i.is_adversarial)
    # holdout_delta (final-wave shift set vs. everything else) is only meaningful
    # once the holdout wave (rendered by a different model, standing constraint #5,
    # CURRICULUM.md wave 8) has produced holdout items; before that there is
    # nothing to compare against, so 0.0 here is "not yet applicable", not a
    # passing score being manufactured.
    holdout_waves = [w for w, focus in curriculum.WAVE_FOCUS.items() if focus.get("holdout")]
    metrics["holdout_delta"] = (
        _slice_f1_gap(items, lambda i: i.wave in holdout_waves) if any(i.wave in holdout_waves for i in items) else 0.0
    )

    slices = gates.summarise_slices(result_payload["cell_f1"], Counter())
    led = await book.read_ledger()
    prev = gates.summarise_slices(led[-1]["cell_f1"], Counter()) if led and led[-1].get("cell_f1") else None
    ok, why = gates.ratchet_ok(slices, prev)

    result = gates.evaluate(metrics, gates.GATE_B)
    payload = {
        "gatekeeper": "azure-judge-agentic",
        "metrics": metrics,
        "worst_cell": slices.worst_cell,
        "worst_cell_f1": slices.worst_cell_f1,
        "cells_passing": slices.cells_passing,
        "mean_f1": slices.mean_f1,
        "cell_f1": slices.cell_f1,
        "top_confusions": slices.top_confusions,
        "ratchet_ok": ok,
        "ratchet_note": why,
        "n_holdout_items": len(items),
        **result,
    }
    await book.write_json(wave, "gate_b.json", payload)
    await book.append_decisions(
        wave,
        _gate_markdown("Gate B -- model (Azure judge agentic gatekeeper, no human review)", result)
        + f"\nRatchet: {why}\nWorst cell: {slices.worst_cell} @ {slices.worst_cell_f1:.3f}\n"
        f"Holdout pool: {len(items)} items across waves 1-{wave}\n",
    )
    if not result["passed"] or not ok:
        raise WaveHalted(f"Gate B (agentic) failed: {'; '.join(result['failures']) or why}")
    log_extra(log, 20, "Gate B passed (agentic gatekeeper)", note=why, n_items=len(items))
    return payload, slices


async def stage_close(wave: int, plan: dict[str, Any], slices: gates.SliceResult, book: lb.Logbook,
                       notes: str = "") -> None:
    rows = await book.read_generation(wave)
    kept = sum(1 for r in rows if r["outcome"] == "kept")
    survival = await book.survival_rates(wave)
    await book.append_ledger(lb.WaveRecord(
        wave=wave,
        requested=plan["total"],
        kept=kept,
        gate_a_passed=True,
        gate_b_passed=True,
        worst_cell_f1=slices.worst_cell_f1,
        worst_cell=slices.worst_cell,
        cells_passing=slices.cells_passing,
        mean_f1=slices.mean_f1,
        cell_f1=slices.cell_f1,
        survival=survival,
        top_confusions=slices.top_confusions,
        notes=notes,
    ))
    log_extra(log, 20, "ledger appended", wave=wave, next_wave=wave + 1)


def _gate_markdown(title: str, result: dict[str, Any]) -> str:
    lines = [f"### {title}: {'PASS' if result['passed'] else 'FAIL'}", "",
             "| Check | Value | Bound | |", "|---|---|---|---|"]
    for name, c in result["checks"].items():
        lines.append(f"| {name} | {c['value']} | {c.get('op', '')} {c['bound']} | "
                     f"{'ok' if c['passed'] else 'FAIL'} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    set_wave(args.wave)

    async with lb.Logbook(settings, get_run_id()) as book:
        # Realtime sink: every log line, in console AND Mongo, within ~0.5s of being
        # emitted. Cancelled in the finally block below so the drain task flushes
        # its last batch before the process exits.
        sink_task = attach_mongo_sink(book.db, level=settings.log_level)
        try:
            if args.cmd == "plan":
                async with AzureClient(settings) as azure:
                    plan = await curriculum.plan_wave(args.wave, book, azure, settings)
                print(json.dumps(plan, indent=2, ensure_ascii=False)[:4000])

            elif args.cmd == "generate":
                plan = await book.read_json(args.wave, "plan.json")
                if plan is None:
                    raise WaveHalted(f"no plan.json for wave {args.wave}; run `plan` first")
                async with AzureClient(settings) as azure, ContentSafetyClient(settings) as safety:
                    await stage_generate(args.wave, plan, book, azure, safety, settings,
                                          rate_per_minute=args.rate_per_minute, max_records=args.max_records)

            elif args.cmd == "gate-a":
                plan = await book.read_json(args.wave, "plan.json")
                if plan is None:
                    raise WaveHalted(f"no plan.json for wave {args.wave}; run `plan` first")
                async with AzureClient(settings) as azure:
                    await stage_gate_a(args.wave, plan, book, azure, settings)

            elif args.cmd == "train":
                gate_a = await book.read_json(args.wave, "gate_a.json")
                if not gate_a or not gate_a.get("passed"):
                    raise WaveHalted(f"Gate A has not passed for wave {args.wave}; refusing to submit training")
                dataset_hash = hashlib.sha256(json.dumps(gate_a["metrics"], sort_keys=True).encode()).hexdigest()[:12]
                await stage_train(args.wave, settings, book, dataset_hash)

            elif args.cmd == "gate-b":
                if args.results:
                    # legacy path: a human still ran the sealed eval by hand
                    _, slices = await stage_gate_b(args.wave, Path(args.results), book)
                else:
                    # default: the Azure judge model is the gatekeeper, no human file required
                    async with AzureClient(settings) as azure, StudentClient(settings) as student:
                        _, slices = await stage_gate_b_auto(args.wave, book, azure, student, settings)
                plan = await book.read_json(args.wave, "plan.json") or {"total": 0}
                await stage_close(args.wave, plan, slices, book, notes=args.notes or "")

            else:
                raise ValueError(args.cmd)

        except WaveHalted as exc:
            log_extra(log, 40, "wave halted", reason=str(exc))
            await book.append_decisions(args.wave, f"### HALTED\n\n{exc}\n")
            return 2

        finally:
            sink_task.cancel()
            try:
                await sink_task
            except asyncio.CancelledError:
                pass

    return 0


def main() -> int:
    # The console's default codepage on Windows (cp1252) cannot encode most of
    # what gpt-5.4-mini legitimately emits (em/en dashes, curly quotes, the
    # occasional non-Latin character in a jurisdiction name) -- confirmed
    # against the live endpoint, which crashed a plain `print()` on U+2011.
    # Force UTF-8 rather than relying on the platform default.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="python -m cold_chain.runner")
    ap.add_argument("cmd", choices=["plan", "generate", "gate-a", "train", "gate-b"])
    ap.add_argument("--wave", type=int, required=True)
    ap.add_argument("--results", help="path to human-produced sealed golden-set results JSON "
                                       "(gate-b only; omit to use the Azure judge agentic gatekeeper)")
    ap.add_argument("--notes", help="note appended to the ledger row (gate-b only)")
    ap.add_argument("--rate-per-minute", type=int, default=None,
                     help="generate only: cap on new items dispatched per minute, to stay under "
                          "the account's real throughput instead of guessing a concurrency number")
    ap.add_argument("--max-records", type=int, default=None,
                     help="generate only: stop after this many items from the plan, regardless of "
                          "how many the plan allocated (e.g. cap a wave at 663 total)")
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
