"""Twelve-dimension KPI scorecard (1–10) for pipeline health.

Each dimension maps measurable signals to a 1–10 score where 10 means comfortably
above the gate threshold. The dashboard uses these for at-a-glance readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cold_chain.domain import gates

KPI_TARGET = 7.0


@dataclass
class KpiScore:
    name: str
    score: float
    detail: str
    signals: dict[str, Any]


def _clamp(score: float) -> float:
    return max(1.0, min(10.0, round(score, 1)))


def _linear(value: float, *, good: float, bad: float, higher_is_better: bool) -> float:
    if higher_is_better:
        if value >= good:
            return 10.0
        if value <= bad:
            return 1.0
        return 1.0 + 9.0 * (value - bad) / (good - bad)
    if value <= good:
        return 10.0
    if value >= bad:
        return 1.0
    return 1.0 + 9.0 * (bad - value) / (bad - good)


def _band(value: float, low: float, high: float) -> float:
    """Score screener flag rate: best inside [low, high]."""
    if low <= value <= high:
        return 10.0
    if value < low:
        return _clamp(10.0 - (low - value) / low * 5.0)
    return _clamp(10.0 - (value - high) / (1.0 - high) * 5.0)


def score_gate_a_metrics(metrics: dict[str, float]) -> list[KpiScore]:
    """Score nine Gate A-derived dimensions (qualitative pair merged)."""
    return [
        KpiScore(
            "schema_validity",
            _clamp(_linear(metrics.get("schema_validity", 0.0), good=0.995, bad=0.90, higher_is_better=True)),
            "extraction schema pass rate across all attempts",
            {"value": metrics.get("schema_validity")},
        ),
        KpiScore(
            "round_trip_recovery",
            _clamp(_linear(metrics.get("round_trip_recovery", 0.0), good=0.95, bad=0.75, higher_is_better=True)),
            "kept records whose extractor recovers ground-truth ranges",
            {"value": metrics.get("round_trip_recovery")},
        ),
        KpiScore(
            "screener_calibration",
            _clamp(_band(metrics.get("screener_flag_rate", 0.0), 0.02, 0.08)),
            "screener/guardrail/safety drop rate (target 2–8%)",
            {"value": metrics.get("screener_flag_rate")},
        ),
        KpiScore(
            "corpus_uniqueness",
            _clamp(_linear(metrics.get("near_duplicate_rate", 1.0), good=0.03, bad=0.15, higher_is_better=False)),
            "stratified near-duplicate rate on kept text",
            {"value": metrics.get("near_duplicate_rate")},
        ),
        KpiScore(
            "cell_balance",
            _clamp(_linear(metrics.get("cell_fill_deviation", 1.0), good=0.10, bad=0.35, higher_is_better=False)),
            "survival-adjusted deviation from plan cell targets",
            {"value": metrics.get("cell_fill_deviation")},
        ),
        KpiScore(
            "class_balance",
            _clamp(_linear(metrics.get("max_class_share", 1.0), good=0.45, bad=0.70, higher_is_better=False)),
            "largest disposition share in kept records",
            {"value": metrics.get("max_class_share")},
        ),
        KpiScore(
            "leakage_resistance",
            _clamp(_linear(metrics.get("leakage_probe_acc", 1.0), good=0.70, bad=0.90, higher_is_better=False)),
            "bag-of-words probe accuracy on disposition (lower is better)",
            {"value": metrics.get("leakage_probe_acc")},
        ),
        KpiScore(
            "qualitative_review",
            _clamp(
                (
                    _linear(metrics.get("language_authenticity", 0.0), good=3.5, bad=2.0, higher_is_better=True)
                    + _linear(metrics.get("annotator_kappa", 0.0), good=0.75, bad=0.40, higher_is_better=True)
                )
                / 2.0
            ),
            "language authenticity + judge-ensemble agreement",
            {
                "language_authenticity": metrics.get("language_authenticity"),
                "annotator_kappa": metrics.get("annotator_kappa"),
            },
        ),
        KpiScore(
            "guardrail_integrity",
            _clamp(
                _linear(metrics.get("guardrail_violation_rate", 1.0), good=0.01, bad=0.08, higher_is_better=False)
            ),
            "regex guardrail hits on kept records",
            {"value": metrics.get("guardrail_violation_rate")},
        ),
    ]


def score_training_readiness(
    *,
    gate_a_passed: bool,
    kept_count: int,
    export_path: Path | None,
    preflight_ok: bool,
    min_kept: int = 50,
) -> KpiScore:
    parts = [
        gate_a_passed,
        kept_count >= min_kept,
        export_path is not None and export_path.exists(),
        preflight_ok,
    ]
    passed = sum(parts)
    score = _clamp(4.0 + passed * 1.5)
    return KpiScore(
        "training_readiness",
        score,
        "Gate A pass, export on disk, Foundry config, training module",
        {
            "gate_a_passed": gate_a_passed,
            "kept_count": kept_count,
            "export_exists": export_path is not None and export_path.exists(),
            "preflight_ok": preflight_ok,
        },
    )


def score_gate_b_readiness(
    *,
    student_endpoint: bool,
    holdout_count: int,
    gate_b_ran: bool,
    gate_b_passed: bool | None,
) -> KpiScore:
    if gate_b_ran and gate_b_passed:
        score = 10.0
    elif gate_b_ran:
        score = 7.5
    elif student_endpoint and holdout_count >= 10:
        score = 8.5
    elif student_endpoint:
        score = 7.0
    elif holdout_count >= 10:
        score = 7.5
    else:
        score = 4.0
    return KpiScore(
        "inference_gate_b_readiness",
        _clamp(score),
        "student endpoint or human sealed-eval path, holdout pool size",
        {
            "student_endpoint": student_endpoint,
            "holdout_count": holdout_count,
            "gate_b_ran": gate_b_ran,
            "gate_b_passed": gate_b_passed,
        },
    )


def score_operational_maturity(
    *,
    health_ok: bool,
    ready_ok: bool,
    local_run_exists: bool,
    runbook_exists: bool,
    makefile_targets: bool,
) -> KpiScore:
    parts = [health_ok, ready_ok, local_run_exists, runbook_exists, makefile_targets]
    score = _clamp(5.0 + sum(parts) * 1.0)
    return KpiScore(
        "operational_maturity",
        score,
        "one-command flow, health/ready, runbook, Makefile targets",
        {
            "health_ok": health_ok,
            "ready_ok": ready_ok,
            "local_run": local_run_exists,
            "runbook": runbook_exists,
            "makefile": makefile_targets,
        },
    )


def summarise(scores: list[KpiScore]) -> dict[str, Any]:
    below = [s for s in scores if s.score < KPI_TARGET]
    return {
        "scores": {s.name: {"score": s.score, "detail": s.detail, **s.signals} for s in scores},
        "mean": round(sum(s.score for s in scores) / len(scores), 1) if scores else 0.0,
        "min": min((s.score for s in scores), default=0.0),
        "all_above_target": len(below) == 0,
        "below_target": [s.name for s in below],
        "target": KPI_TARGET,
    }


def evaluate_gate_a_pass(metrics: dict[str, float]) -> bool:
    return gates.evaluate(metrics, gates.GATE_A)["passed"]
