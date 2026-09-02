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

from cold_chain.adapters import agentic_eval
from cold_chain.adapters import logbook as lb
from cold_chain.adapters.clients import AzureClient, ContentSafetyClient, StudentClient
from cold_chain.adapters.training import FoundryTrainingSubmitter
from cold_chain.config import Settings, get_settings
from cold_chain.domain import curriculum, gates, guardrails, simulate
from cold_chain.domain import knowledge_base as kb
from cold_chain.domain.rules_engine import engine_sha
from cold_chain.domain.rules_engine import label as rule_label
from cold_chain.observability.telemetry import (
    attach_mongo_sink,
    configure_logging,
    get_logger,
    get_run_id,
    log_extra,
    set_wave,
)

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


def _expand_allocation(alloc: dict[str, Any], wave: int, *, attempt_buffer: float = 1.0) -> list[simulate.GenerationRequest]:
    n = max(1, int(round(alloc["count"] * attempt_buffer)))
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
    abstention_idx = set(idx[alloc["adversarial"] : alloc["adversarial"] + alloc["abstention"]])

    reqs = []
    for i in range(n):
        seed = int(hashlib.sha256(f"{wave}:{cell}:{i}".encode()).hexdigest()[:12], 16)
        reqs.append(
            simulate.GenerationRequest(
                product=alloc["product"],
                fault_mode=alloc["fault_mode"],
                language=langs[i],
                artifact_type=artifacts[i],
                jurisdiction=jurisdictions[i],
                is_adversarial=i in adversarial_idx,
                is_abstention=i in abstention_idx,
                rng_seed=seed,
            )
        )
    return reqs


GENERATION_ATTEMPT_BUFFER = 1.30  # extra attempts on full waves to hit kept targets after drops
CELL_TOP_UP_ROUNDS = 3
CELL_TOP_UP_TARGET = 0.95  # top up until kept >= 95% of plan target


def _sample_requests_balanced(plan: dict[str, Any], wave: int, max_records: int) -> list[simulate.GenerationRequest]:
    """Proportional sampling across cells so smoke runs cover the full plan."""
    pools = [_expand_allocation(alloc, wave) for alloc in plan["allocations"]]
    flat = [req for pool in pools for req in pool]
    if max_records >= len(flat):
        return flat
    total = len(flat)
    quotas = [max(1, int(round(max_records * (len(pool) / total)))) for pool in pools]
    while sum(quotas) > max_records:
        quotas[quotas.index(max(quotas))] -= 1
    while sum(quotas) < max_records:
        quotas[quotas.index(min(quotas))] += 1
    sampled: list[simulate.GenerationRequest] = []
    for pool, quota in zip(pools, quotas):
        rng = random.Random(f"{wave}:sample:{quota}")
        idx = list(range(len(pool)))
        rng.shuffle(idx)
        sampled.extend(pool[i] for i in idx[:quota])
    random.Random(f"{wave}:sample-shuffle").shuffle(sampled)
    return sampled


def _build_generation_requests(
    plan: dict[str, Any], wave: int, max_records: int | None
) -> list[simulate.GenerationRequest]:
    if max_records is not None:
        return _sample_requests_balanced(plan, wave, max_records)
    buffer = GENERATION_ATTEMPT_BUFFER
    return [req for alloc in plan["allocations"] for req in _expand_allocation(alloc, wave, attempt_buffer=buffer)]


async def _dispatch_generation_batch(
    reqs: list[simulate.GenerationRequest],
    wave: int,
    azure: AzureClient,
    safety: ContentSafetyClient,
    book: lb.Logbook,
    engine_sha_val: str,
    settings: Settings,
    rate_per_minute: int | None,
) -> None:
    sem = asyncio.Semaphore(LOCAL_CONCURRENCY)

    async def guarded(req: simulate.GenerationRequest) -> None:
        async with sem:
            await _generate_one(req, wave, azure, safety, book, engine_sha_val, settings)

    interval_s = 60.0 / rate_per_minute if rate_per_minute else 0.0
    tasks = []
    for i, req in enumerate(reqs):
        tasks.append(asyncio.create_task(guarded(req)))
        if interval_s and i < len(reqs) - 1:
            await asyncio.sleep(interval_s)
    await asyncio.gather(*tasks)


async def _top_up_underfilled_cells(
    wave: int,
    plan: dict[str, Any],
    book: lb.Logbook,
    azure: AzureClient,
    safety: ContentSafetyClient,
    settings: Settings,
    engine_sha_val: str,
    rate_per_minute: int | None,
) -> None:
    """Generate extra attempts for cells below kept target (full waves only)."""
    for round_num in range(CELL_TOP_UP_ROUNDS):
        rows = await book.read_generation(wave)
        kept_by_cell: dict[str, int] = Counter(r["cell"] for r in rows if r["outcome"] == "kept")
        top_up: list[simulate.GenerationRequest] = []
        for alloc in plan["allocations"]:
            cell = lb.cell_key(alloc["product"], alloc["fault_mode"])
            target = alloc["count"]
            kept = kept_by_cell.get(cell, 0)
            if kept >= target * CELL_TOP_UP_TARGET:
                continue
            deficit = min(target - kept, max(3, int((target - kept) * 1.5)))
            extra_alloc = {**alloc, "count": deficit}
            top_up.extend(_expand_allocation(extra_alloc, wave)[:deficit])
        if not top_up:
            return
        log_extra(log, 20, "generation top-up", round=round_num + 1, n=len(top_up))
        await _dispatch_generation_batch(top_up, wave, azure, safety, book, engine_sha_val, settings, rate_per_minute)
        await book.flush_generation()


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
    req: simulate.GenerationRequest,
    wave: int,
    azure: AzureClient,
    safety: ContentSafetyClient,
    book: lb.Logbook,
    engine_sha_val: str,
    settings: Settings,
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
            simulate.render_prompt(
                state,
                req.language,
                req.artifact_type,
                req.jurisdiction,
                style_seed=req.rng_seed % 4,
            ),
            max_tokens=simulate.render_max_tokens(req.artifact_type),
        )

        if not await safety.is_safe(rendered):
            await book.write_generation(
                envelope,
                "dropped_safety",
                extra={"disposition": disposition, "rendered_text": rendered[:4000]},
            )
            return

        # confirmed against the live endpoint: 10 tokens truncates mid-word ("CONS" instead
        # of "CONSISTENT") depending on how the tokenizer splits the verdict word -- not a
        # reasoning-budget issue this time, just not enough room for the longest verdict.
        verdict_raw = await azure.complete(simulate.screener_prompt(rendered), max_tokens=30, temperature=0.0)
        verdict = verdict_raw.strip().upper()
        envelope.screener_verdict = (
            verdict if verdict in ("CONSISTENT", "INCONSISTENT", "LEAKS_LABEL") else "UNPARSEABLE"
        )
        if envelope.screener_verdict != "CONSISTENT":
            await book.write_generation(
                envelope,
                "dropped_screener",
                extra={
                    "disposition": disposition,
                    "rendered_text": rendered[:4000],
                    "screener_verdict": envelope.screener_verdict,
                },
            )
            return

        # guardrails.check_artifact_text: an independent, dependency-free regex net
        # (metadata leakage / expedite_sale wording / truncated logger_csv tail) run in
        # addition to the LLM screener above, not instead of it -- see guardrails.py's
        # module docstring and gates.GATE_A["guardrail_violation_rate"].
        guardrail_hits = guardrails.check_artifact_text(rendered, req.artifact_type)
        if guardrail_hits:
            await book.write_generation(
                envelope,
                "dropped_guardrail",
                extra={
                    "disposition": disposition,
                    "rendered_text": rendered[:4000],
                    "screener_verdict": envelope.screener_verdict,
                    "guardrail_violations": [{"rule_id": v.rule_id, "detail": v.detail} for v in guardrail_hits],
                },
            )
            return

        extracted_raw = await azure.complete(
            simulate.extraction_prompt(rendered),
            max_tokens=simulate.extraction_max_tokens(req.artifact_type),
            temperature=0.0,
        )
        schema_valid, extracted = _validate_extraction(extracted_raw)
        if not schema_valid:
            await book.write_generation(
                envelope,
                "dropped_schema",
                extra={
                    "disposition": disposition,
                    "rendered_text": rendered[:4000],
                    "screener_verdict": envelope.screener_verdict,
                    "schema_valid": False,
                },
            )
            return

        round_trip, confidence = _round_trip_check(state, extracted)
        envelope.round_trip_ok = round_trip
        if not round_trip:
            await book.write_generation(
                envelope,
                "dropped_roundtrip",
                extra={
                    "disposition": disposition,
                    "rendered_text": rendered[:4000],
                    "screener_verdict": envelope.screener_verdict,
                    "schema_valid": True,
                    "confidence": confidence,
                },
            )
            return

        if confidence < settings.min_round_trip_confidence:
            await book.write_generation(
                envelope,
                "dropped_low_confidence",
                extra={
                    "disposition": disposition,
                    "rendered_text": rendered[:4000],
                    "screener_verdict": envelope.screener_verdict,
                    "schema_valid": True,
                    "confidence": confidence,
                },
            )
            return

        legal = kb.citation(req.jurisdiction)
        await book.write_generation(
            envelope,
            "kept",
            extra={
                "disposition": disposition,
                "rendered_text": rendered[:4000],
                "screener_verdict": envelope.screener_verdict,
                "schema_valid": True,
                "confidence": confidence,
                "legal_citation": {
                    "jurisdiction": legal.jurisdiction,
                    "instrument": legal.instrument,
                    "authority": legal.authority,
                },
            },
        )
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


async def stage_generate(
    wave: int,
    plan: dict[str, Any],
    book: lb.Logbook,
    azure: AzureClient,
    safety: ContentSafetyClient,
    settings: Settings,
    rate_per_minute: int | None = None,
    max_records: int | None = None,
) -> None:
    """``rate_per_minute`` paces how often a new item is *dispatched*, not a
    concurrency cap -- confirmed against the live endpoint: even with
    LOCAL_CONCURRENCY down at 8, dispatching all items via one asyncio.gather
    still produced synchronized bursts (8 items all making their first Azure
    call within milliseconds of each other), which is what actually trips a
    per-second rate limit. Spacing out *starts* keeps in-flight calls low
    without needing to know the account's exact quota."""
    engine_sha_val = engine_sha()
    all_reqs = _build_generation_requests(plan, wave, max_records)
    log_extra(
        log,
        20,
        "generation start",
        rule_engine_sha=engine_sha_val,
        total=len(all_reqs),
        rate_per_minute=rate_per_minute,
    )

    await _dispatch_generation_batch(
        all_reqs, wave, azure, safety, book, engine_sha_val, settings, rate_per_minute
    )
    await book.flush_generation()

    if max_records is None:
        await _top_up_underfilled_cells(
            wave, plan, book, azure, safety, settings, engine_sha_val, rate_per_minute
        )

    await book.update_coverage(wave)
    log_extra(log, 20, "generation complete", n=len(all_reqs))


# --------------------------------------------------------------------------- #
# Gate A
# --------------------------------------------------------------------------- #


async def _gate_a_metrics(
    wave: int, plan: dict[str, Any], book: lb.Logbook, azure: AzureClient, settings: Settings
) -> dict[str, float]:
    rows = await book.read_generation(wave)
    kept = [r for r in rows if r["outcome"] == "kept"]
    attempted = len(rows) or 1

    kept_by_cell: dict[str, int] = Counter(r["cell"] for r in kept)
    attempted_by_cell: dict[str, int] = Counter(r["cell"] for r in rows)
    texts = [r.get("rendered_text", "") for r in kept]
    labels = [r.get("disposition", "") for r in kept]
    artifact_types = [r.get("artifact_type") for r in kept]

    metrics: dict[str, float] = {
        "schema_validity": sum(1 for r in rows if r.get("schema_valid")) / attempted,
        "round_trip_recovery": (sum(1 for r in kept if r.get("round_trip_ok")) / len(kept)) if kept else 0.0,
        "screener_flag_rate": gates.screener_flag_rate(rows),
        "cell_fill_deviation": gates.cell_fill_deviation_survival_adjusted(plan, kept_by_cell, attempted_by_cell),
        "max_class_share": gates.max_class_share(labels),
        "guardrail_violation_rate": gates.guardrail_violation_rate(texts, artifact_types),
    }

    if texts:
        try:
            embeddings = await azure.embed(texts)
            metrics["near_duplicate_rate"] = await gates.near_duplicate_rate_stratified_async(
                texts, artifact_types, lambda _t: embeddings
            )
        except Exception as exc:  # noqa: BLE001
            log_extra(
                log,
                40,
                "embeddings call failed; near_duplicate_rate not measured this run",
                error=str(exc),
            )
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
        log_extra(
            log,
            20,
            "Gate A qualitative review: agentic board",
            wave=wave,
            language_authenticity=review["language_authenticity"],
            agreement=review["language_authenticity_agreement"],
            escalated=review["language_authenticity_escalated"],
        )

    return metrics


async def stage_gate_a(
    wave: int, plan: dict[str, Any], book: lb.Logbook, azure: AzureClient, settings: Settings
) -> dict[str, Any]:
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


async def stage_train(
    wave: int,
    settings: Settings,
    book: lb.Logbook,
    dataset_hash: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submits the SFT job via the training adapter (or dry-run preflight)."""
    submitter = FoundryTrainingSubmitter(settings)
    export_path = str(Path(__file__).resolve().parent.parent.parent / "exports" / f"generation_log_wave{wave:02d}.jsonl")
    result = await submitter.submit(wave, dataset_hash=dataset_hash, export_path=export_path, dry_run=dry_run)
    await book.write_json(wave, "train_submission.json", result)
    log_extra(log, 20, "training job submitted" if not dry_run else "training dry-run", **result)
    return result


async def stage_preflight(
    wave: int, settings: Settings, book: lb.Logbook
) -> dict[str, Any]:
    """Readiness check for train and Gate B without side effects."""
    from cold_chain.adapters.training import preflight_check

    gate_a = await book.read_json(wave, "gate_a.json")
    rows = await book.read_generation(wave)
    kept = [r for r in rows if r.get("outcome") == "kept"]
    export_path = Path(__file__).resolve().parent.parent.parent / "exports" / f"generation_log_wave{wave:02d}.jsonl"

    holdout_n = sum(
        1
        for r in kept
        if int(hashlib.sha256(r["state_id"].encode()).hexdigest()[:8], 16) % 100 < int(HOLDOUT_FRACTION * 100)
    )

    training = preflight_check(settings, wave, export_path=export_path)
    training["gate_a_passed"] = bool(gate_a and gate_a.get("passed"))
    training["kept_count"] = len(kept)

    gate_b = {
        "student_endpoint_configured": bool(settings.student_inference_endpoint),
        "holdout_items": holdout_n,
        "auto_path_ready": bool(settings.student_inference_endpoint) and holdout_n >= 10,
        "human_path_ready": holdout_n >= 10,
        "note": "Use gate-b --results <path> when no student endpoint is deployed",
    }
    payload = {"wave": wave, "training": training, "gate_b": gate_b}
    await book.write_json(wave, "preflight.json", payload)
    return payload


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


async def _build_holdout_items(
    waves: list[int], book: lb.Logbook, student: StudentClient, sem: asyncio.Semaphore
) -> list[agentic_eval.HoldoutItem]:
    items: list[agentic_eval.HoldoutItem] = []

    async def _one(row: dict[str, Any]) -> None:
        async with sem:
            parsed, raw = await student.predict(row.get("rendered_text", ""))
            items.append(
                agentic_eval.HoldoutItem(
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
                )
            )

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


async def stage_gate_b_auto(
    wave: int, book: lb.Logbook, azure: AzureClient, student: StudentClient, settings: Settings
) -> tuple[dict[str, Any], gates.SliceResult]:
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


async def stage_close(
    wave: int, plan: dict[str, Any], slices: gates.SliceResult, book: lb.Logbook, notes: str = ""
) -> None:
    rows = await book.read_generation(wave)
    kept = sum(1 for r in rows if r["outcome"] == "kept")
    survival = await book.survival_rates(wave)
    await book.append_ledger(
        lb.WaveRecord(
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
        )
    )
    log_extra(log, 20, "ledger appended", wave=wave, next_wave=wave + 1)


def _gate_markdown(title: str, result: dict[str, Any]) -> str:
    lines = [
        f"### {title}: {'PASS' if result['passed'] else 'FAIL'}",
        "",
        "| Check | Value | Bound | |",
        "|---|---|---|---|",
    ]
    for name, c in result["checks"].items():
        lines.append(f"| {name} | {c['value']} | {c.get('op', '')} {c['bound']} | {'ok' if c['passed'] else 'FAIL'} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


async def cmd_ready() -> int:
    """Readiness: config valid and MongoDB reachable."""
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        async with lb.Logbook(settings, "ready-check") as book:
            await book.load_coverage()
        print(json.dumps({"status": "ready", "mongodb_db": settings.mongodb_db_name}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "not_ready", "error": str(exc)}))
        return 1


def cmd_health() -> int:
    """Liveness: config loads and required env vars are present."""
    from pydantic import ValidationError

    from cold_chain.config import missing_required_env_message

    try:
        settings = get_settings()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "environment": settings.environment,
                    "checks": ["config"],
                }
            )
        )
        return 0
    except ValidationError as exc:
        print(json.dumps({"status": "error", "error": missing_required_env_message(exc)}))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1


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
                    await stage_generate(
                        args.wave,
                        plan,
                        book,
                        azure,
                        safety,
                        settings,
                        rate_per_minute=args.rate_per_minute,
                        max_records=args.max_records,
                    )

            elif args.cmd == "gate-a":
                plan = await book.read_json(args.wave, "plan.json")
                if plan is None:
                    raise WaveHalted(f"no plan.json for wave {args.wave}; run `plan` first")
                async with AzureClient(settings) as azure:
                    await stage_gate_a(args.wave, plan, book, azure, settings)

            elif args.cmd == "train":
                gate_a = await book.read_json(args.wave, "gate_a.json")
                if not args.dry_run and (not gate_a or not gate_a.get("passed")):
                    raise WaveHalted(f"Gate A has not passed for wave {args.wave}; refusing to submit training")
                dataset_hash = hashlib.sha256(
                    json.dumps((gate_a or {}).get("metrics", {}), sort_keys=True).encode()
                ).hexdigest()[:12]
                result = await stage_train(args.wave, settings, book, dataset_hash, dry_run=args.dry_run)
                print(json.dumps(result, indent=2))

            elif args.cmd == "preflight":
                result = await stage_preflight(args.wave, settings, book)
                print(json.dumps(result, indent=2))

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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="python -m cold_chain.runner")
    ap.add_argument(
        "cmd",
        choices=["health", "ready", "plan", "generate", "gate-a", "train", "preflight", "gate-b"],
    )
    ap.add_argument("--wave", type=int, default=None)
    ap.add_argument(
        "--results",
        help="path to human-produced sealed golden-set results JSON "
        "(gate-b only; omit to use the Azure judge agentic gatekeeper)",
    )
    ap.add_argument("--notes", help="note appended to the ledger row (gate-b only)")
    ap.add_argument(
        "--rate-per-minute",
        type=int,
        default=None,
        help="generate only: cap on new items dispatched per minute",
    )
    ap.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="generate only: stop after this many items from the plan",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="train only: validate preflight without submitting a job",
    )
    args = ap.parse_args()

    if args.cmd == "health":
        return cmd_health()
    if args.cmd == "ready":
        return asyncio.run(cmd_ready())

    if args.wave is None:
        ap.error(f"--wave is required for command '{args.cmd}'")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
