"""Curriculum planner.

Loop engineering: the plan for wave N is a pure function of CURRICULUM.md plus the
logs from waves 1..N-1. Nothing else. Same logs in, same plan out.

The deterministic scorer below produces the allocation. The Azure judge model
(the same gpt-5.4-mini deployment used for rendering) is called only to write
the rationale and the escalations -- prose a human reads before approving. It
cannot change the numbers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cold_chain.config import Settings, get_settings
from cold_chain.domain import catalog as cat
from cold_chain.observability.telemetry import get_logger

if TYPE_CHECKING:
    from cold_chain.adapters.clients import AzureClient
    from cold_chain.adapters.logbook import Logbook

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
GUIDE = ROOT / "CURRICULUM.md"

# Production defaults per CURRICULUM.md (5,304 records, 8 waves of 663);
# overridable via WAVE_SIZE / CELL_TARGET in .env for a reduced-scale dry run
# without touching this file. MAX_PER_CELL_PER_WAVE tracks WAVE_SIZE at the
# same 20% ratio CURRICULUM.md specifies.
OVERSHOOT_TOLERANCE = 1.05
ADVERSARIAL_SHARE = 0.15
ABSTENTION_SHARE = 0.08

W_COUNT, W_F1, W_STALE = 0.45, 0.40, 0.15

# wave -> (allowed artifacts, allowed fault modes, overlay share overrides)
# mirrors section 3 of CURRICULUM.md; None means "all". The language axis is
# gone (corpus is English-only); jurisdiction is always balanced across all
# six GCC states regardless of wave, since it never affects the label.
WAVE_FOCUS: dict[int, dict[str, Any]] = {
    1: {"faults": ["in_spec", "door_open"], "artifacts": None},
    2: {"faults": ["compressor_fail", "setpoint_drift", "sensor_artifact"], "artifacts": None},
    3: {"faults": None, "artifacts": ["voice_note", "qc_form_ocr"]},
    4: {"faults": None, "artifacts": None},
    5: {"faults": None, "artifacts": None, "adversarial_share": 0.60},
    6: {"faults": None, "artifacts": None, "abstention_share": 0.55},
    7: {"faults": None, "artifacts": None},
    8: {"faults": None, "artifacts": None, "holdout": True},
}


async def _latest_cell_f1(book: Logbook) -> dict[str, float]:
    led = await book.read_ledger()
    return dict(led[-1].get("cell_f1", {})) if led else {}


def _staleness(cov: dict[str, Any], cell: str, wave: int) -> float:
    last = cov["cells"].get(cell, {}).get("last_wave", 0)
    return min(wave - last, 4) / 4.0 if last else 1.0


async def score_cells(wave: int, book: Logbook, settings: Settings | None = None) -> dict[str, float]:
    """Deficit score per cell. Section 4 of CURRICULUM.md. Exposed standalone
    for tests and for the escalation report; ``build_plan`` recomputes the
    same scores inline to avoid a second round trip to MongoDB."""
    settings = settings or get_settings()
    cov = await book.load_coverage()
    f1 = await _latest_cell_f1(book)
    focus = WAVE_FOCUS.get(wave, {})
    allowed_faults = focus.get("faults")

    scores: dict[str, float] = {}
    for cell in cat.all_cells():
        product, fault = cell.split("|")
        if allowed_faults and fault not in allowed_faults:
            continue
        kept = cov["cells"].get(cell, {}).get("kept", 0)
        if kept >= settings.cell_target * OVERSHOOT_TOLERANCE:
            continue
        count_gap = max(0.0, (settings.cell_target - kept) / settings.cell_target)
        cell_f1 = f1.get(cell, 0.5)
        scores[cell] = W_COUNT * count_gap + W_F1 * (1.0 - cell_f1) + W_STALE * _staleness(cov, cell, wave)
    return scores


def _balanced_split(total: int, keys: list[str]) -> dict[str, int]:
    base, rem = divmod(total, len(keys))
    return {k: base + (1 if i < rem else 0) for i, k in enumerate(keys)}


async def build_plan(wave: int, book: Logbook, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    wave_size = settings.wave_size
    cell_target = settings.cell_target
    max_per_cell = max(1, int(wave_size * 0.20))  # CURRICULUM.md's 20% per-cell cap

    cov = await book.load_coverage()
    f1 = await _latest_cell_f1(book)
    focus = WAVE_FOCUS.get(wave, {})
    allowed_faults = focus.get("faults")

    scores: dict[str, float] = {}
    for cell in cat.all_cells():
        product, fault = cell.split("|")
        if allowed_faults and fault not in allowed_faults:
            continue
        kept = cov["cells"].get(cell, {}).get("kept", 0)
        if kept >= cell_target * OVERSHOOT_TOLERANCE:
            continue
        count_gap = max(0.0, (cell_target - kept) / cell_target)
        cell_f1 = f1.get(cell, 0.5)
        scores[cell] = W_COUNT * count_gap + W_F1 * (1.0 - cell_f1) + W_STALE * _staleness(cov, cell, wave)

    if not scores:
        raise RuntimeError(f"wave {wave}: no eligible cells -- corpus may be complete")

    artifacts = focus.get("artifacts") or cat.ARTIFACTS
    adv_share = focus.get("adversarial_share", ADVERSARIAL_SHARE)
    abs_share = focus.get("abstention_share", ABSTENTION_SHARE)

    total_score = sum(scores.values())
    raw = {c: wave_size * s / total_score for c, s in scores.items()}
    alloc = {c: min(max_per_cell, int(round(v))) for c, v in raw.items()}

    spare = wave_size - sum(alloc.values())
    for cell in sorted(scores, key=scores.get, reverse=True):
        if spare <= 0:
            break
        room = max_per_cell - alloc[cell]
        take = min(room, spare)
        alloc[cell] += take
        spare -= take

    surv = await book.survival_rates(wave - 1) if wave > 1 else {}

    allocations = []
    for cell, n in sorted(alloc.items(), key=lambda kv: -kv[1]):
        if n <= 0:
            continue
        product, fault = cell.split("|")
        kept = cov["cells"].get(cell, {}).get("kept", 0)
        allocations.append(
            {
                "product": product,
                "fault_mode": fault,
                "count": n,
                "adversarial": int(round(n * adv_share)),
                "abstention": int(round(n * abs_share)),
                "language_split": _balanced_split(n, cat.LANGUAGES),
                "artifact_split": _balanced_split(n, artifacts),
                "jurisdiction_split": _balanced_split(n, cat.JURISDICTIONS),
                "reason": (
                    f"F1 {f1.get(cell, float('nan')):.2f}, "
                    f"{cell_target - kept} short of target, "
                    f"survival {surv.get(cell, float('nan')):.2f} last wave"
                ),
            }
        )

    escalations = [
        f"{c}: survival {r:.2f} -- rendering suspected, not a data-quantity gap" for c, r in surv.items() if r < 0.75
    ]

    return {
        "wave": wave,
        "total": sum(a["count"] for a in allocations),
        "holdout": bool(focus.get("holdout")),
        "allocations": allocations,
        "rationale": "",  # filled by the Azure judge model, prose only
        "escalations": escalations,
        "guide_sha": _guide_sha(),
    }


def _guide_sha() -> str:
    return hashlib.sha256(GUIDE.read_bytes()).hexdigest()[:12] if GUIDE.exists() else "missing"


RATIONALE_PROMPT = """You are the curriculum agent for a GCC cold-chain dataset.

The allocation below was computed deterministically from the coverage matrix and the
previous wave's metrics. You cannot change it. Write two things:

1. `rationale` -- 3-5 sentences for the human approving this wave. What is this wave
   targeting, and what should they watch for in the results.
2. `escalations` -- append any concern the numbers imply that is not already listed.
   Low survival rates mean the renderer is failing, not that more data is needed.

Optimise commentary toward the worst cell, never the mean.

PLAN:
{plan}

PREVIOUS WAVE CONFUSIONS:
{confusions}

Return only JSON: {{"rationale": "...", "escalations": ["..."]}}
"""


async def annotate_with_azure(plan: dict[str, Any], azure: AzureClient, confusions: list[list[str]]) -> dict[str, Any]:
    """Ask the Azure judge model for prose. Numbers are never touched. Failure is non-fatal."""
    prompt = RATIONALE_PROMPT.format(
        plan=json.dumps(plan["allocations"][:8], indent=2, ensure_ascii=False),
        confusions=json.dumps(confusions, ensure_ascii=False),
    )
    try:
        text = await azure.complete(prompt, max_tokens=1200, temperature=0.3)
        parsed = json.loads(text[text.index("{") : text.rindex("}") + 1])
        plan["rationale"] = parsed.get("rationale", "")
        plan["escalations"] = list(dict.fromkeys(plan["escalations"] + parsed.get("escalations", [])))
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "rationale annotation unavailable, allocation unaffected",
            extra={"extra_fields": {"error": str(exc)}},
        )
        plan["rationale"] = f"[rationale annotation unavailable: {exc}] Allocation stands on the scorer."
    return plan


async def plan_wave(
    wave: int, book: Logbook, azure: AzureClient | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    plan = await build_plan(wave, book, settings)
    if azure is not None:
        led = await book.read_ledger()
        confusions = led[-1].get("top_confusions", []) if led else []
        plan = await annotate_with_azure(plan, azure, confusions)
    await book.write_json(wave, "plan.json", plan)
    await book.append_decisions(wave, _plan_markdown(plan))
    return plan


def _plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        f"## Wave {plan['wave']} plan",
        "",
        plan.get("rationale", ""),
        "",
        "| Cell | N | Adv | Abst | Reason |",
        "|---|---|---|---|---|",
    ]
    for a in plan["allocations"]:
        lines.append(
            f"| {a['product']} / {a['fault_mode']} | {a['count']} | "
            f"{a['adversarial']} | {a['abstention']} | {a['reason']} |"
        )
    if plan["escalations"]:
        lines += ["", "**Escalations**", ""] + [f"- {e}" for e in plan["escalations"]]
    return "\n".join(lines)
