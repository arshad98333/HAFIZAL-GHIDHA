"""Score all 12 pipeline KPIs (1–10) for a wave.

    python scripts/kpi_dashboard.py --wave 1
    python scripts/kpi_dashboard.py --wave 1 --json

Reads Gate A metrics from MongoDB, checks training/Gate B readiness, and scores
operational maturity from repo artifacts. Target: every KPI >= 7/10.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from cold_chain.adapters.training import preflight_check  # noqa: E402
from cold_chain.config import get_settings  # noqa: E402
from cold_chain.domain import kpi  # noqa: E402
from cold_chain.logbook import Logbook  # noqa: E402


def _holdout_count(rows: list[dict]) -> int:
    import hashlib

    kept = [r for r in rows if r.get("outcome") == "kept"]
    return sum(
        1
        for r in kept
        if int(hashlib.sha256(r["state_id"].encode()).hexdigest()[:8], 16) % 100 < 5
    )


def _cmd_ok(cmd: list[str]) -> bool:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode == 0


async def score_wave(wave: int) -> dict:
    settings = get_settings()
    py = sys.executable
    export_path = ROOT / "exports" / f"generation_log_wave{wave:02d}.jsonl"

    async with Logbook(settings, "kpi-dashboard") as book:
        gate_a = await book.read_json(wave, "gate_a.json")
        gate_b = await book.read_json(wave, "gate_b.json")
        rows = await book.read_generation(wave)

    kept = [r for r in rows if r.get("outcome") == "kept"]
    metrics = (gate_a or {}).get("metrics") or {}
    gate_a_scores = kpi.score_gate_a_metrics(metrics) if metrics else [
        kpi.KpiScore(name, 5.0, "run gate-a first", {}) for name in [
            "schema_validity", "round_trip_recovery", "screener_calibration",
            "corpus_uniqueness", "cell_balance", "class_balance",
            "leakage_resistance", "qualitative_review", "guardrail_integrity",
        ]
    ]

    train_preflight = preflight_check(settings, wave, export_path=export_path)
    training_score = kpi.score_training_readiness(
        gate_a_passed=bool(gate_a and gate_a.get("passed")),
        kept_count=len(kept),
        export_path=export_path,
        preflight_ok=train_preflight["ready"],
    )

    student_ok = bool(settings.student_inference_endpoint)
    gate_b_score = kpi.score_gate_b_readiness(
        student_endpoint=student_ok,
        holdout_count=_holdout_count(rows),
        gate_b_ran=gate_b is not None,
        gate_b_passed=gate_b.get("passed") if gate_b else None,
    )

    makefile = ROOT / "Makefile"
    makefile_targets = makefile.exists() and "smoke-run" in makefile.read_text(encoding="utf-8")
    ops_score = kpi.score_operational_maturity(
        health_ok=_cmd_ok([py, "-m", "cold_chain.runner", "health"]),
        ready_ok=_cmd_ok([py, "-m", "cold_chain.runner", "ready"]),
        local_run_exists=(ROOT / "scripts" / "local_run.py").exists(),
        runbook_exists=(ROOT / "docs" / "LOCAL_RUNBOOK.md").exists(),
        makefile_targets=makefile_targets,
    )

    all_scores = gate_a_scores + [training_score, gate_b_score, ops_score]
    summary = kpi.summarise(all_scores)
    return {
        "wave": wave,
        "gate_a_passed": bool(gate_a and gate_a.get("passed")),
        "training_preflight": train_preflight,
        **summary,
    }


def _print_table(result: dict) -> None:
    print(f"\nKPI Dashboard — Wave {result['wave']}")
    print("=" * 60)
    print(f"Mean score: {result['mean']}/10   Target: {result['target']}/10")
    if result["all_above_target"]:
        print("Status: ALL KPIs at or above target")
    else:
        print(f"Below target: {', '.join(result['below_target'])}")
    print()
    print(f"{'KPI':<30} {'Score':>6}  Detail")
    print("-" * 60)
    for name, info in result["scores"].items():
        print(f"{name:<30} {info['score']:>5.1f}  {info['detail']}")
    print()


async def main_async(wave: int, as_json: bool) -> int:
    result = await score_wave(wave)
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        _print_table(result)
    return 0 if result["all_above_target"] else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", type=int, required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    return asyncio.run(main_async(args.wave, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
