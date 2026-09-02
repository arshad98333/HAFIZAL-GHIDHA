"""Local development orchestrator: one command or step-by-step.

Option 1 -- run everything in order (setup + pipeline + export + audit):

    python scripts/local_run.py all --wave 1 --max-records 10   # smoke (10 records)
    python scripts/local_run.py all --wave 1                    # full wave (~663 records)

Option 2 -- print or run individual steps (same commands you would type by hand):

    python scripts/local_run.py steps --wave 1 --max-records 10
    python scripts/local_run.py step setup
    python scripts/local_run.py step plan --wave 1
    python scripts/local_run.py step generate --wave 1 --max-records 10
    python scripts/local_run.py step gate-a --wave 1
    python scripts/local_run.py step export --wave 1
    python scripts/local_run.py step audit --wave 1

Audit the last Gate A result for a wave (reads gate_a.json from MongoDB):

    python scripts/local_run.py audit --wave 1

KPI scorecard (all 12 dimensions, target >= 7/10):

    python scripts/local_run.py kpi --wave 1
    python scripts/local_run.py preflight --wave 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _py() -> str:
    return sys.executable


def _run(label: str, cmd: list[str], *, stop_on_fail: bool = True) -> int:
    print(f"\n{'=' * 70}\n[{label}]  {' '.join(cmd)}\n{'=' * 70}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    status = "ok" if result.returncode == 0 else f"exit {result.returncode}"
    print(f"[{label}] finished: {status}", flush=True)
    if stop_on_fail and result.returncode != 0:
        print(f"\n[{label}] failed -- stopping.", flush=True)
    return result.returncode


def _setup_cmds(*, skip_tests: bool) -> list[tuple[str, list[str]]]:
    py = _py()
    steps: list[tuple[str, list[str]]] = []
    if not skip_tests:
        steps.append(
            (
                "tests",
                [
                    py,
                    "-m",
                    "pytest",
                    "-v",
                    "-m",
                    "not integration",
                    "--ignore=tests/integration",
                ],
            )
        )
    steps.extend(
        [
            ("health", [py, "-m", "cold_chain.runner", "health"]),
            ("ready", [py, "-m", "cold_chain.runner", "ready"]),
        ]
    )
    return steps


def _pipeline_cmd(wave: int, max_records: int | None, rate_per_minute: int | None) -> list[str]:
    cmd = [ _py(), str(ROOT / "scripts" / "run_pipeline.py"), "--wave", str(wave)]
    if max_records is not None:
        cmd += ["--max-records", str(max_records)]
    if rate_per_minute is not None:
        cmd += ["--rate-per-minute", str(rate_per_minute)]
    return cmd


def _step_cmds(wave: int, max_records: int | None, rate_per_minute: int | None) -> list[tuple[str, list[str]]]:
    py = _py()
    generate = [py, "-m", "cold_chain.runner", "generate", "--wave", str(wave)]
    if max_records is not None:
        generate += ["--max-records", str(max_records)]
    if rate_per_minute is not None:
        generate += ["--rate-per-minute", str(rate_per_minute)]
    audit_out = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{wave:02d}.md"
    audit_csv = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{wave:02d}.csv"
    return [
        *_setup_cmds(skip_tests=False),
        ("plan", [py, "-m", "cold_chain.runner", "plan", "--wave", str(wave)]),
        ("generate", generate),
        ("gate-a", [py, "-m", "cold_chain.runner", "gate-a", "--wave", str(wave)]),
        ("export", [py, str(ROOT / "scripts" / "export_wave.py"), "--wave", str(wave)]),
        ("preflight", [py, "-m", "cold_chain.runner", "preflight", "--wave", str(wave)]),
        (
            "audit",
            [
                py,
                str(ROOT / "scripts" / "audit_corpus_guardrails.py"),
                "--wave",
                str(wave),
                "--out",
                str(audit_out),
                "--csv",
                str(audit_csv),
            ],
        ),
    ]


def cmd_steps(args: argparse.Namespace) -> int:
    print("Step-by-step commands (run each line separately):\n")
    for i, (name, cmd) in enumerate(_step_cmds(args.wave, args.max_records, args.rate_per_minute), 1):
        print(f"  # {i}. {name}")
        print(f"  {' '.join(cmd)}\n")
    print("Notes:")
    print("  - Run `az login` once before plan/generate if Azure auth is needed.")
    print("  - gate-a exit code 2 means the gate halted (expected on small smoke runs).")
    print("  - train/gate-b require Gate A pass and Foundry/student endpoint config.")
    return 0


def cmd_step(args: argparse.Namespace) -> int:
    py = _py()
    name = args.step_name
    if name == "setup":
        for label, cmd in _setup_cmds(skip_tests=args.skip_tests):
            rc = _run(label, cmd)
            if rc != 0:
                return rc
        return 0
    if args.wave is None:
        print("error: --wave is required for pipeline steps", file=sys.stderr)
        return 2

    if name == "plan":
        return _run("plan", [py, "-m", "cold_chain.runner", "plan", "--wave", str(args.wave)])
    if name == "generate":
        cmd = [py, "-m", "cold_chain.runner", "generate", "--wave", str(args.wave)]
        if args.max_records is not None:
            cmd += ["--max-records", str(args.max_records)]
        if args.rate_per_minute is not None:
            cmd += ["--rate-per-minute", str(args.rate_per_minute)]
        return _run("generate", cmd)
    if name == "gate-a":
        return _run("gate-a", [py, "-m", "cold_chain.runner", "gate-a", "--wave", str(args.wave)], stop_on_fail=False)
    if name == "export":
        return _run("export", [py, str(ROOT / "scripts" / "export_wave.py"), "--wave", str(args.wave)])
    if name == "audit":
        audit_out = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{args.wave:02d}.md"
        audit_csv = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{args.wave:02d}.csv"
        return _run(
            "audit",
            [
                py,
                str(ROOT / "scripts" / "audit_corpus_guardrails.py"),
                "--wave",
                str(args.wave),
                "--out",
                str(audit_out),
                "--csv",
                str(audit_csv),
            ],
        )
    if name in ("train", "gate-b"):
        cmd = [py, "-m", "cold_chain.runner", name, "--wave", str(args.wave)]
        return _run(name, cmd, stop_on_fail=False)
    if name == "preflight":
        return _run("preflight", [py, "-m", "cold_chain.runner", "preflight", "--wave", str(args.wave)])
    if name == "kpi":
        return _run("kpi", [py, str(ROOT / "scripts" / "kpi_dashboard.py"), "--wave", str(args.wave)], stop_on_fail=False)

    print(f"error: unknown step {name!r}", file=sys.stderr)
    return 2


def cmd_all(args: argparse.Namespace) -> int:
    if not args.skip_setup:
        for label, cmd in _setup_cmds(skip_tests=args.skip_tests):
            rc = _run(label, cmd)
            if rc != 0:
                return rc
    return _run(
        "pipeline",
        _pipeline_cmd(args.wave, args.max_records, args.rate_per_minute),
        stop_on_fail=False,
    )


async def _audit_wave(wave: int) -> int:
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from cold_chain.config import get_settings
    from cold_chain.logbook import Logbook

    settings = get_settings()
    async with Logbook(settings, "local-run-audit") as book:
        gate = await book.read_json(wave, "gate_a.json")
        rows = await book.read_generation(wave)
    kept = [r for r in rows if r.get("outcome") == "kept"]
    print(f"\nWave {wave} audit")
    print("=" * 50)
    print(f"  generation_log rows : {len(rows)}")
    print(f"  kept records        : {len(kept)}")
    if gate:
        print(f"  Gate A passed       : {gate.get('passed')}")
        metrics = gate.get("metrics") or {}
        if metrics:
            print("\n  Gate A metrics:")
            for key, value in sorted(metrics.items()):
                print(f"    {key}: {value}")
        failures = gate.get("failures") or []
        if failures:
            print("\n  Gate A failures:")
            for line in failures:
                print(f"    - {line}")
    else:
        print("  Gate A result       : (not found -- run gate-a first)")
    export_path = ROOT / "exports" / f"generation_log_wave{wave:02d}.jsonl"
    if export_path.exists():
        n_lines = sum(1 for _ in export_path.open(encoding="utf-8"))
        print(f"\n  export file         : {export_path} ({n_lines} lines)")
    print()
    return 0 if gate and gate.get("passed") else (2 if gate else 1)


def cmd_audit(args: argparse.Namespace) -> int:
    return asyncio.run(_audit_wave(args.wave))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    p_all = sub.add_parser("all", help="run setup + full pipeline in one command")
    p_all.add_argument("--wave", type=int, required=True)
    p_all.add_argument("--max-records", type=int, default=None, help="smoke cap for generate")
    p_all.add_argument("--rate-per-minute", type=int, default=None)
    p_all.add_argument("--skip-tests", action="store_true")
    p_all.add_argument("--skip-setup", action="store_true", help="skip tests/health/ready")

    p_steps = sub.add_parser("steps", help="print step-by-step commands (do not run them)")
    p_steps.add_argument("--wave", type=int, required=True)
    p_steps.add_argument("--max-records", type=int, default=None)
    p_steps.add_argument("--rate-per-minute", type=int, default=None)

    p_step = sub.add_parser("step", help="run one named step")
    p_step.add_argument(
        "step_name",
        choices=["setup", "plan", "generate", "gate-a", "export", "audit", "preflight", "train", "gate-b", "kpi"],
    )
    p_step.add_argument("--wave", type=int, default=None)
    p_step.add_argument("--max-records", type=int, default=None)
    p_step.add_argument("--rate-per-minute", type=int, default=None)
    p_step.add_argument("--skip-tests", action="store_true")

    p_audit = sub.add_parser("audit", help="summarize Gate A + record counts for a wave")
    p_audit.add_argument("--wave", type=int, required=True)

    p_kpi = sub.add_parser("kpi", help="12-dimension KPI scorecard (target >= 7/10)")
    p_kpi.add_argument("--wave", type=int, required=True)
    p_kpi.add_argument("--json", action="store_true")

    p_preflight = sub.add_parser("preflight", help="training + Gate B readiness check")
    p_preflight.add_argument("--wave", type=int, required=True)

    args = ap.parse_args()
    if args.mode == "all":
        return cmd_all(args)
    if args.mode == "steps":
        return cmd_steps(args)
    if args.mode == "step":
        return cmd_step(args)
    if args.mode == "audit":
        return cmd_audit(args)
    if args.mode == "kpi":
        cmd = [_py(), str(ROOT / "scripts" / "kpi_dashboard.py"), "--wave", str(args.wave)]
        if args.json:
            cmd.append("--json")
        return _run("kpi", cmd, stop_on_fail=False)
    if args.mode == "preflight":
        return _run("preflight", [_py(), "-m", "cold_chain.runner", "preflight", "--wave", str(args.wave)])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
