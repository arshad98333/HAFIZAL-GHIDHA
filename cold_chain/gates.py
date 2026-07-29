"""Wave gates. Either gate can halt the pipeline; that is their entire purpose.

Gate A runs on the new 1,000 before it enters training.
Gate B runs on the sealed golden set after training. A human runs Gate B.

Everything here is a pure function over in-memory data — no I/O, no async.
The runner is responsible for getting metrics computed off the event loop
(``asyncio.to_thread``) since ``leakage_probe`` and ``near_duplicate_rate``
train a classifier / do dense matrix math and would otherwise block it.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from . import logbook as lb

# --------------------------------------------------------------------------- #
# Gate A -- data quality
# --------------------------------------------------------------------------- #

GATE_A: dict[str, tuple[str, float]] = {
    "schema_validity":      (">=", 0.995),
    "round_trip_recovery":  (">=", 0.95),
    "screener_flag_rate":   ("between", (0.02, 0.08)),
    "near_duplicate_rate":  ("<=", 0.03),
    "cell_fill_deviation":  ("<=", 0.10),
    "max_class_share":      ("<=", 0.45),
    "leakage_probe_acc":    ("<=", 0.70),
    "language_authenticity": (">=", 3.5),
    "annotator_kappa":      (">=", 0.75),
    # independent, dependency-free regex net on rendered text -- see
    # guardrails.check_artifact_text. Any hit (metadata leakage, expedite_sale
    # wording, a truncated logger_csv tail) is a defect the LLM screener
    # should already have caught; this is defense in depth, so the bar is tight.
    "guardrail_violation_rate": ("<=", 0.01),
}

# --------------------------------------------------------------------------- #
# Gate B -- model quality
# --------------------------------------------------------------------------- #

GATE_B: dict[str, tuple[str, float]] = {
    "malformed_json_rate":  ("<=", 0.005),
    "hallucinated_field_rate": ("<=", 0.01),
    "abstention_precision": (">=", 0.85),
    "abstention_recall":    (">=", 0.75),
    # replaces the retired language-axis "cross_language_delta" (corpus is
    # English-only now, see CURRICULUM.md section 2) -- the equivalent
    # fairness check on the new jurisdiction covariate: max F1 gap between
    # any two of the six GCC states with enough holdout items to measure.
    "cross_jurisdiction_delta": ("<=", 0.05),
    "adversarial_gap":      ("<=", 0.10),
    "holdout_delta":        ("<=", 0.05),
}


def _check(op: str, value: float, bound) -> bool:
    if op == ">=":
        return value >= bound
    if op == "<=":
        return value <= bound
    if op == "between":
        return bound[0] <= value <= bound[1]
    raise ValueError(op)


def evaluate(metrics: dict[str, float], spec: dict[str, tuple[str, Any]]) -> dict[str, Any]:
    results, failures = {}, []
    for name, (op, bound) in spec.items():
        if name not in metrics:
            failures.append(f"{name}: not measured")
            results[name] = {"value": None, "bound": bound, "passed": False}
            continue
        ok = _check(op, metrics[name], bound)
        results[name] = {"value": metrics[name], "op": op, "bound": bound, "passed": ok}
        if not ok:
            failures.append(f"{name}: {metrics[name]} fails {op} {bound}")
    return {"passed": not failures, "failures": failures, "checks": results}


# --------------------------------------------------------------------------- #
# metric computation (sync, CPU-bound — call via asyncio.to_thread)
# --------------------------------------------------------------------------- #

def leakage_probe(texts: list[str], labels: list[str]) -> float:
    """Train a bag-of-words classifier on surface text alone. If it predicts the
    disposition well, the renderer is telegraphing the answer and the whole wave
    is contaminated. This is the check people skip and shouldn't."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score

    if len(set(labels)) < 2 or len(texts) < 50:
        return 0.0
    X = TfidfVectorizer(max_features=3000, ngram_range=(1, 2)).fit_transform(texts)
    scores = cross_val_score(LogisticRegression(max_iter=800), X, labels, cv=4, scoring="accuracy")
    return float(scores.mean())


async def leakage_probe_async(texts: list[str], labels: list[str]) -> float:
    return await asyncio.to_thread(leakage_probe, texts, labels)


def near_duplicate_rate(texts: list[str], embed: Callable[[list[str]], Any], thresh: float = 0.95) -> float:
    import numpy as np
    if len(texts) < 2:
        return 0.0
    V = np.asarray(embed(texts), dtype="float32")
    V /= (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    sim = V @ V.T
    np.fill_diagonal(sim, 0.0)
    return float((sim.max(axis=1) > thresh).mean())


async def near_duplicate_rate_async(texts: list[str], embed: Callable[[list[str]], Any],
                                     thresh: float = 0.95) -> float:
    return await asyncio.to_thread(near_duplicate_rate, texts, embed, thresh)


def cell_fill_deviation(plan: dict[str, Any], kept_by_cell: dict[str, int]) -> float:
    devs = []
    for a in plan["allocations"]:
        cell = lb.cell_key(a["product"], a["fault_mode"])
        target = a["count"]
        devs.append(abs(kept_by_cell.get(cell, 0) - target) / max(target, 1))
    return float(sum(devs) / len(devs)) if devs else 0.0


def max_class_share(labels: list[str]) -> float:
    if not labels:
        return 1.0
    return max(Counter(labels).values()) / len(labels)


def guardrail_violation_rate(texts: list[str], artifact_types: list[str | None] | None = None) -> float:
    """Fraction of kept records where ``guardrails.check_artifact_text`` finds
    at least one hit -- metadata leakage, expedite_sale wording, or a
    truncated logger_csv tail. Import is local to keep the guardrail pack
    read lazy and out of every import of this module."""
    from . import guardrails as gr

    if not texts:
        return 0.0
    types = artifact_types or [None] * len(texts)
    hits = sum(1 for text, atype in zip(texts, types) if gr.check_artifact_text(text, atype))
    return hits / len(texts)


# --------------------------------------------------------------------------- #
# Gate B slice metrics
# --------------------------------------------------------------------------- #

@dataclass
class SliceResult:
    cell_f1: dict[str, float]
    worst_cell: str
    worst_cell_f1: float
    cells_passing: int
    mean_f1: float
    top_confusions: list[list[str]]


def summarise_slices(cell_f1: dict[str, float], confusions: Counter, pass_at: float = 0.80) -> SliceResult:
    if not cell_f1:
        return SliceResult({}, "", 0.0, 0, 0.0, [])
    worst = min(cell_f1, key=cell_f1.get)
    return SliceResult(
        cell_f1=cell_f1,
        worst_cell=worst,
        worst_cell_f1=cell_f1[worst],
        cells_passing=sum(1 for v in cell_f1.values() if v >= pass_at),
        mean_f1=sum(cell_f1.values()) / len(cell_f1),
        top_confusions=[list(pair) for pair, _ in confusions.most_common(5)],
    )


def ratchet_ok(current: SliceResult, previous: SliceResult | None) -> tuple[bool, str]:
    """AUTORESEARCH.md section 4: raising the floor by dropping a passing cell
    is a regression, not an improvement."""
    if previous is None:
        return True, "first measured wave"
    if current.worst_cell_f1 < previous.worst_cell_f1:
        return False, f"worst_cell_f1 fell {previous.worst_cell_f1:.3f} -> {current.worst_cell_f1:.3f}"
    dropped = [c for c, v in previous.cell_f1.items()
               if v >= 0.80 and current.cell_f1.get(c, 0.0) < 0.80]
    if dropped:
        return False, f"cells dropped below 0.80: {', '.join(dropped)}"
    return True, f"worst_cell_f1 {previous.worst_cell_f1:.3f} -> {current.worst_cell_f1:.3f}"
