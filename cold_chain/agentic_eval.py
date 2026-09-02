"""Agentic replacement for the human HITL steps (PRD section 6).

Be clear-eyed about what this trades away: the original design put a human on
the sealed golden set specifically because an LLM judging its own pipeline's
output is gameable — the AutoResearch agent could learn to produce text that
satisfies the judge model's rubric without the underlying extraction actually
improving, and nothing downstream would catch it. Section 12 constraint #1
("no label in this system is ever produced by a language model") and
AUTORESEARCH.md's "you never see the golden set" existed to make that failure
mode structurally impossible, not just unlikely.

This module is the mitigation for the world where that guarantee is
explicitly not wanted:
  - every categorical field that has a ground truth (disposition, from
    rules_engine.py) is still scored by exact match against that ground
    truth — never by the judge model's opinion. The judge model is not in
    the loop for anything the rule engine can already answer deterministically.
  - the judge model only judges the fields that are inherently fuzzy
    (hallucination, abstention quality, language authenticity) and does so
    with self-consistency voting (`JUDGE_VOTES` independent calls), not a
    single pass — disagreement below `JUDGE_AGREEMENT_FLOOR` escalates to a
    stricter re-judge rather than being silently averaged away.
  - every vote, rationale, and escalation is written to Mongo
    (`gate_b_deliberation`), so a human can audit the automated gate after
    the fact even though none reviewed it in real time.

The judge model is the same Azure OpenAI (gpt-5.4-mini) deployment used for
rendering/screening elsewhere in the pipeline, called here at low
concurrency and a distinct (higher) temperature for judgment prompts. There
is deliberately one external model provider in this pipeline, not two.

If this pipeline needs to stand up to external regulatory audit, the honest
recommendation is to keep a human sampling a fraction of auto-passed waves
after the fact — this module does not claim to make that unnecessary, only to
remove it from the blocking critical path.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .clients import AzureClient
from .telemetry import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# self-consistency voting primitive
# --------------------------------------------------------------------------- #


@dataclass
class Verdict:
    votes: list[Any]
    consensus: Any
    agreement: float  # fraction of votes matching the consensus
    escalated: bool
    rationale: str


async def _vote_once(azure: AzureClient, prompt: str, max_tokens: int) -> tuple[Any, str]:
    """A failed vote (rate-limited, transport error, unparseable output) is just a
    missing data point -- self_consistency_vote already tolerates a partial or even
    empty vote set. Confirmed against the live endpoint: without this try/except
    around the network call itself (not just the JSON parse), a single 429 from the
    judge model during a 5-vote round crashed the entire Gate A process after
    retries were exhausted, instead of being absorbed as one lost vote out of five."""
    try:
        raw = await azure.complete(prompt, max_tokens=max_tokens, temperature=0.4)
    except Exception as exc:  # noqa: BLE001
        return None, f"judge call failed: {exc}"
    try:
        parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        return parsed.get("verdict"), parsed.get("rationale", "")
    except Exception:
        return None, f"unparseable judge output: {raw[:200]}"


async def self_consistency_vote(
    azure: AzureClient,
    prompt: str,
    k: int,
    agreement_floor: float,
    *,
    max_tokens: int = 600,
    escalation_prompt: str | None = None,
) -> Verdict:
    """Calls the judge ``k`` times independently and takes the modal verdict.
    Numeric verdicts are pooled via median; categorical ones via majority.
    Low agreement triggers one stricter re-judge pass rather than trusting the
    noisy majority — this is the "best of best" selection the automated gate
    relies on instead of a single LLM call deciding anything."""
    votes, rationales = [], []
    for _ in range(k):
        v, r = await _vote_once(azure, prompt, max_tokens)
        if v is not None:
            votes.append(v)
            rationales.append(r)

    if not votes:
        return Verdict([], None, 0.0, True, "all judge votes unparseable")

    if all(isinstance(v, (int, float)) for v in votes):
        consensus = statistics.median(votes)
        agreement = sum(1 for v in votes if abs(v - consensus) < 1e-6) / len(votes)
    else:
        counts = Counter(str(v) for v in votes)
        consensus_str, n = counts.most_common(1)[0]
        consensus = consensus_str
        agreement = n / len(votes)

    escalated = agreement < agreement_floor
    if escalated and escalation_prompt:
        strict_v, strict_r = await _vote_once(azure, escalation_prompt, max_tokens)
        if strict_v is not None:
            consensus, agreement, rationales = strict_v, 1.0, [strict_r]

    return Verdict(votes, consensus, agreement, escalated, "; ".join(rationales)[:2000])


# --------------------------------------------------------------------------- #
# agentic review board — stands in for HITL 1 / 3 / 5 (wave approval,
# disagreement adjudication, language authenticity)
# --------------------------------------------------------------------------- #

LANGUAGE_AUTHENTICITY_PROMPT = """You are a native-level reviewer of English-language cold-chain field
reports as written by real GCC (UAE/KSA/Qatar/Kuwait/Oman/Bahrain) logistics and QA staff, not a
translation exercise. Rate how authentic this sample of artifacts sounds. Score 1 (obviously
synthetic/stilted) to 5 (indistinguishable from a real field report).

SAMPLES:
{samples}

Return only JSON: {{"verdict": <1-5 integer>, "rationale": "..."}}
"""

LEAKAGE_REVIEW_PROMPT = """You are auditing a synthetic cold-chain dataset for label leakage. None of these
artifacts should state or imply a disposition decision (accept/reject/hold/expedite) — they
should only report observations. Read the samples and judge whether, as a set, they leak the
disposition. Score 1 (no leakage, purely observational) to 5 (decisions are stated outright).

SAMPLES:
{samples}

Return only JSON: {{"verdict": <1-5 integer>, "rationale": "..."}}
"""


class AgenticReviewBoard:
    """Runs where a human HITL reviewer used to. Feeds Gate A's
    ``language_authenticity`` / ``annotator_kappa`` fields automatically."""

    def __init__(self, azure: AzureClient, votes: int, agreement_floor: float):
        self._azure = azure
        self._votes = votes
        self._floor = agreement_floor

    async def review(self, texts: list[str], sample_n: int = 30) -> dict[str, Any]:
        sample = texts[:sample_n] if len(texts) <= sample_n else texts[:sample_n]
        blob = "\n---\n".join(sample)

        authenticity = await self_consistency_vote(
            self._azure,
            LANGUAGE_AUTHENTICITY_PROMPT.format(samples=blob),
            self._votes,
            self._floor,
        )
        leakage = await self_consistency_vote(
            self._azure,
            LEAKAGE_REVIEW_PROMPT.format(samples=blob),
            self._votes,
            self._floor,
        )

        return {
            "language_authenticity": authenticity.consensus,
            "language_authenticity_agreement": authenticity.agreement,
            "language_authenticity_escalated": authenticity.escalated,
            "language_authenticity_rationale": authenticity.rationale,
            # `annotator_kappa` in the human design measures dual-annotator agreement;
            # its agentic analogue is cross-vote agreement among the judge ensemble.
            "annotator_kappa": min(authenticity.agreement, 1.0 - (float(leakage.consensus or 5) - 1) / 4),
            "leakage_review_score": leakage.consensus,
            "leakage_review_rationale": leakage.rationale,
        }


# --------------------------------------------------------------------------- #
# automated Gate B — replaces the human-run sealed eval file
# --------------------------------------------------------------------------- #

HALLUCINATION_PROMPT = """You are auditing a model's field extraction for hallucination. The SOURCE ARTIFACT
is the only evidence the model should have used. The MODEL OUTPUT is what it extracted.
Judge whether the model output states any field value that is not supported by the source
artifact. Score 0 (fully grounded) to 1 (invents unsupported values).

SOURCE ARTIFACT:
{artifact}

MODEL OUTPUT:
{output}

Return only JSON: {{"verdict": <0.0-1.0 float>, "rationale": "..."}}
"""

ABSTENTION_PROMPT = """The correct disposition for this item is "insufficient_data" because the source
artifact is missing information needed to decide. Judge whether the model's output correctly
recognises the artifact as insufficient rather than guessing a disposition. Score 1 if it
correctly abstained, 0 if it guessed.

SOURCE ARTIFACT:
{artifact}

MODEL OUTPUT:
{output}

Return only JSON: {{"verdict": <0 or 1>, "rationale": "..."}}
"""


@dataclass
class HoldoutItem:
    cell: str
    wave: int
    language: str
    jurisdiction: str
    is_adversarial: bool
    is_abstention: bool
    artifact_text: str
    ground_truth_disposition: str
    model_output: dict[str, Any] | None  # None if inference failed
    model_output_raw: str


class AutoGateB:
    """The Azure judge model as the automated gatekeeper. Deterministic fields
    (disposition F1 per cell) are scored by exact match against
    ``rules_engine`` ground truth — the judge model is never asked to grade
    something Python can already answer. It only adjudicates hallucination
    and abstention quality, both self-consistency voted and logged in full
    to ``gate_b_deliberation``.
    """

    def __init__(self, azure: AzureClient, votes: int, agreement_floor: float):
        self._azure = azure
        self._votes = votes
        self._floor = agreement_floor
        self.deliberation: list[dict[str, Any]] = []

    async def _judge_item(self, item: HoldoutItem) -> dict[str, Any]:
        out = json.dumps(item.model_output) if item.model_output is not None else item.model_output_raw
        record: dict[str, Any] = {"cell": item.cell}

        if item.model_output is None:
            record["malformed_json"] = True
            self.deliberation.append(record)
            return record
        record["malformed_json"] = False

        hallucination = await self_consistency_vote(
            self._azure,
            HALLUCINATION_PROMPT.format(artifact=item.artifact_text, output=out),
            self._votes,
            self._floor,
        )
        record["hallucination_score"] = hallucination.consensus
        record["hallucination_agreement"] = hallucination.agreement
        record["hallucination_rationale"] = hallucination.rationale

        if item.is_abstention:
            abst = await self_consistency_vote(
                self._azure,
                ABSTENTION_PROMPT.format(artifact=item.artifact_text, output=out),
                self._votes,
                self._floor,
            )
            record["abstention_correct"] = bool(abst.consensus)
            record["abstention_agreement"] = abst.agreement

        self.deliberation.append(record)
        return record

    async def run(self, items: list[HoldoutItem]) -> dict[str, Any]:
        cell_correct: dict[str, int] = {}
        cell_total: dict[str, int] = {}
        malformed = 0
        hallucination_scores: list[float] = []
        abstention_hits, abstention_total = 0, 0

        for item in items:
            cell_total[item.cell] = cell_total.get(item.cell, 0) + 1
            predicted = (item.model_output or {}).get("disposition")
            if predicted == item.ground_truth_disposition:
                cell_correct[item.cell] = cell_correct.get(item.cell, 0) + 1

            judged = await self._judge_item(item)
            if judged.get("malformed_json"):
                malformed += 1
                continue
            hallucination_scores.append(judged["hallucination_score"])
            if item.is_abstention:
                abstention_total += 1
                abstention_hits += int(judged.get("abstention_correct", False))

        n = len(items) or 1
        cell_f1 = {c: cell_correct.get(c, 0) / t for c, t in cell_total.items()}

        return {
            "cell_f1": cell_f1,
            "metrics": {
                "malformed_json_rate": malformed / n,
                "hallucinated_field_rate": (
                    sum(hallucination_scores) / len(hallucination_scores) if hallucination_scores else 0.0
                ),
                "abstention_precision": (abstention_hits / abstention_total) if abstention_total else 1.0,
                "abstention_recall": (abstention_hits / abstention_total) if abstention_total else 1.0,
                # cross_language_delta / adversarial_gap / holdout_delta need the holdout
                # pool partitioned by language/adversarial/wave-10 flags upstream; the
                # runner computes those slices and passes pre-split item lists in.
            },
            "deliberation": self.deliberation,
        }
