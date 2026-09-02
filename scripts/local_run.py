"""Local development orchestrator — one command for everything.

THE single entry point (pick a profile):

    python scripts/local_run.py run --wave 1 --profile rescore   # re-evaluate existing data
    python scripts/local_run.py run --wave 1 --profile smoke    # first-time 10-record test
    python scripts/local_run.py run --wave 1 --profile wave     # full ~663-record generation

Makefile (Linux/macOS):

    make run              # same as --profile rescore
    make run-smoke        # smoke test
    make run-wave         # full wave

Windows PowerShell:

    .\\scripts\\run.ps1 -Wave 1
    .\\scripts\\run.ps1 -Wave 1 -Profile smoke

Every ``run`` appends a structured JSON entry to ``pipeline_logs.json`` in the repo root.

Legacy subcommands (``all``, ``step``, ``rescore``, etc.) still work.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent

PROFILES = ("smoke", "wave", "rescore", "full")


@dataclass
class StepSpec:
    name: str
    build_cmd: Callable[[], list[str]]
    stop_on_fail: bool = True
    capture_json: bool = False
    summary_key: str | None = None


def _py() -> str:
    return sys.executable


def _run_subprocess(label: str, cmd: list[str], *, stop_on_fail: bool = True) -> int:
    print(f"\n{'=' * 70}\n[{label}]  {' '.join(cmd)}\n{'=' * 70}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    status = "ok" if result.returncode == 0 else f"exit {result.returncode}"
    print(f"[{label}] finished: {status}", flush=True)
    if stop_on_fail and result.returncode != 0:
        print(f"\n[{label}] failed -- stopping.", flush=True)
    return result.returncode


def _import_pipeline_log():
    sys.path.insert(0, str(ROOT / "scripts"))
    from pipeline_log import append_step, capture_json_stdout, finish_run, start_run

    return append_step, capture_json_stdout, finish_run, start_run


def _setup_steps(skip_tests: bool) -> list[StepSpec]:
    py = _py()
    steps: list[StepSpec] = []
    if not skip_tests:
        steps.append(
            StepSpec(
                "tests",
                lambda: [py, "-m", "pytest", "-v", "-m", "not integration", "--ignore=tests/integration"],
            )
        )
    steps.extend(
        [
            StepSpec("health", lambda: [py, "-m", "cold_chain.runner", "health"]),
            StepSpec("ready", lambda: [py, "-m", "cold_chain.runner", "ready"]),
        ]
    )
    return steps


def _wave_steps(wave: int, max_records: int | None, rate_per_minute: int | None) -> list[StepSpec]:
    py = _py()

    def generate_cmd() -> list[str]:
        cmd = [py, "-m", "cold_chain.runner", "generate", "--wave", str(wave)]
        if max_records is not None:
            cmd += ["--max-records", str(max_records)]
        if rate_per_minute is not None:
            cmd += ["--rate-per-minute", str(rate_per_minute)]
        return cmd

    audit_out = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{wave:02d}.md"
    audit_csv = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{wave:02d}.csv"

    return [
        StepSpec("plan", lambda: [py, "-m", "cold_chain.runner", "plan", "--wave", str(wave)]),
        StepSpec("generate", generate_cmd),
        StepSpec(
            "gate-a",
            lambda: [py, "-m", "cold_chain.runner", "gate-a", "--wave", str(wave)],
            stop_on_fail=False,
        ),
        StepSpec("export", lambda: [py, str(ROOT / "scripts" / "export_wave.py"), "--wave", str(wave)]),
        StepSpec(
            "audit",
            lambda: [
                py,
                str(ROOT / "scripts" / "audit_corpus_guardrails.py"),
                "--wave",
                str(wave),
                "--out",
                str(audit_out),
                "--csv",
                str(audit_csv),
            ],
            stop_on_fail=False,
        ),
        StepSpec(
            "kpi",
            lambda: [py, str(ROOT / "scripts" / "kpi_dashboard.py"), "--wave", str(wave), "--json"],
            stop_on_fail=False,
            capture_json=True,
            summary_key="kpi",
        ),
        StepSpec(
            "preflight",
            lambda: [py, "-m", "cold_chain.runner", "preflight", "--wave", str(wave)],
            stop_on_fail=False,
            capture_json=True,
            summary_key="preflight",
        ),
        StepSpec(
            "train-dry-run",
            lambda: [py, "-m", "cold_chain.runner", "train", "--wave", str(wave), "--dry-run"],
            stop_on_fail=False,
            capture_json=True,
            summary_key="train_dry_run",
        ),
    ]


def _rescore_steps(wave: int) -> list[StepSpec]:
    py = _py()
    return [
        StepSpec(
            "gate-a",
            lambda: [py, "-m", "cold_chain.runner", "gate-a", "--wave", str(wave)],
            stop_on_fail=False,
        ),
        StepSpec("export", lambda: [py, str(ROOT / "scripts" / "export_wave.py"), "--wave", str(wave)]),
        StepSpec(
            "kpi",
            lambda: [py, str(ROOT / "scripts" / "kpi_dashboard.py"), "--wave", str(wave), "--json"],
            stop_on_fail=False,
            capture_json=True,
            summary_key="kpi",
        ),
        StepSpec(
            "preflight",
            lambda: [py, "-m", "cold_chain.runner", "preflight", "--wave", str(wave)],
            stop_on_fail=False,
            capture_json=True,
            summary_key="preflight",
        ),
    ]


def _profile_steps(
    profile: str,
    wave: int,
    *,
    max_records: int | None,
    rate_per_minute: int | None,
    skip_tests: bool,
) -> list[StepSpec]:
    if profile == "rescore":
        return _rescore_steps(wave)
    if profile == "smoke":
        return _setup_steps(skip_tests) + _wave_steps(wave, max_records or 10, rate_per_minute)
    if profile == "wave":
        return _setup_steps(skip_tests=True) + _wave_steps(wave, max_records, rate_per_minute)
    if profile == "full":
        return _setup_steps(skip_tests) + _wave_steps(wave, max_records, rate_per_minute)
    raise ValueError(f"unknown profile: {profile}")


def _execute_profile(
    profile: str,
    wave: int,
    *,
    max_records: int | None,
    rate_per_minute: int | None,
    skip_tests: bool,
    log_label: str | None = None,
) -> int:
    append_step, capture_json_stdout, finish_run, start_run = _import_pipeline_log()
    run = start_run(wave, label=log_label or profile)
    summary: dict[str, Any] = {}
    exit_code = 0

    for spec in _profile_steps(profile, wave, max_records=max_records, rate_per_minute=rate_per_minute, skip_tests=skip_tests):
        cmd = spec.build_cmd()
        if spec.capture_json:
            rc, parsed, output = capture_json_stdout(cmd)
            print(output, end="" if output.endswith("\n") else "\n")
            append_step(run, spec.name, cmd, rc, extra={"result": parsed})
            if spec.summary_key and parsed:
                summary[spec.summary_key] = parsed
        else:
            rc = _run_subprocess(spec.name, cmd, stop_on_fail=spec.stop_on_fail)
            append_step(run, spec.name, cmd, rc)
        if rc != 0:
            exit_code = rc
            if spec.stop_on_fail:
                break

    finish_run(run, summary=summary)
    print(f"\n{'=' * 70}")
    print(f"Profile '{profile}' complete for wave {wave}")
    print(f"Log appended to {ROOT / 'pipeline_logs.json'} (run id: {run['id']})")
    if exit_code == 2:
        print("Exit 2 = gate halted or KPI below target (see output above). This is expected on smoke runs.")
    print(f"{'=' * 70}\n")
    return exit_code


def cmd_run(args: argparse.Namespace) -> int:
    profile = args.profile
    skip_tests = args.skip_tests
    max_records = args.max_records
    if profile == "smoke" and max_records is None:
        max_records = 10
    return _execute_profile(
        profile,
        args.wave,
        max_records=max_records,
        rate_per_minute=args.rate_per_minute,
        skip_tests=skip_tests,
        log_label=profile,
    )


def _pipeline_cmd(wave: int, max_records: int | None, rate_per_minute: int | None) -> list[str]:
    cmd = [_py(), str(ROOT / "scripts" / "run_pipeline.py"), "--wave", str(wave)]
    if max_records is not None:
        cmd += ["--max-records", str(max_records)]
    if rate_per_minute is not None:
        cmd += ["--rate-per-minute", str(rate_per_minute)]
    return cmd


def cmd_all(args: argparse.Namespace) -> int:
    return cmd_run(
        argparse.Namespace(
            wave=args.wave,
            profile="smoke" if args.max_records else "wave",
            max_records=args.max_records,
            rate_per_minute=args.rate_per_minute,
            skip_tests=args.skip_tests,
        )
    )


def cmd_steps(args: argparse.Namespace) -> int:
    profile = "smoke" if args.max_records else "wave"
    specs = _profile_steps(
        profile,
        args.wave,
        max_records=args.max_records or (10 if profile == "smoke" else None),
        rate_per_minute=args.rate_per_minute,
        skip_tests=False,
    )
    print(f"Steps for profile '{profile}' (wave {args.wave}):\n")
    for i, spec in enumerate(specs, 1):
        print(f"  # {i}. {spec.name}")
        print(f"  {' '.join(spec.build_cmd())}\n")
    print("Run them all at once:")
    print(f"  python scripts/local_run.py run --wave {args.wave} --profile {profile}")
    return 0


def cmd_step(args: argparse.Namespace) -> int:
    py = _py()
    name = args.step_name
    if name == "setup":
        for spec in _setup_steps(skip_tests=args.skip_tests):
            rc = _run_subprocess(spec.name, spec.build_cmd())
            if rc != 0:
                return rc
        return 0
    if args.wave is None:
        print("error: --wave is required for pipeline steps", file=sys.stderr)
        return 2

    one_off = {
        "plan": [py, "-m", "cold_chain.runner", "plan", "--wave", str(args.wave)],
        "gate-a": [py, "-m", "cold_chain.runner", "gate-a", "--wave", str(args.wave)],
        "export": [py, str(ROOT / "scripts" / "export_wave.py"), "--wave", str(args.wave)],
        "preflight": [py, "-m", "cold_chain.runner", "preflight", "--wave", str(args.wave)],
        "kpi": [py, str(ROOT / "scripts" / "kpi_dashboard.py"), "--wave", str(args.wave)],
    }
    if name == "generate":
        cmd = [py, "-m", "cold_chain.runner", "generate", "--wave", str(args.wave)]
        if args.max_records is not None:
            cmd += ["--max-records", str(args.max_records)]
        if args.rate_per_minute is not None:
            cmd += ["--rate-per-minute", str(args.rate_per_minute)]
        return _run_subprocess(name, cmd)
    if name in one_off:
        stop = name != "gate-a"
        return _run_subprocess(name, one_off[name], stop_on_fail=stop)
    if name == "audit":
        audit_out = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{args.wave:02d}.md"
        audit_csv = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{args.wave:02d}.csv"
        return _run_subprocess(
            name,
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
        return _run_subprocess(name, [py, "-m", "cold_chain.runner", name, "--wave", str(args.wave)], stop_on_fail=False)
    print(f"error: unknown step {name!r}", file=sys.stderr)
    return 2


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


def cmd_rescore(args: argparse.Namespace) -> int:
    return _execute_profile("rescore", args.wave, max_records=None, rate_per_minute=None, skip_tests=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    p_run = sub.add_parser("run", help="THE single command — runs a profile and logs to pipeline_logs.json")
    p_run.add_argument("--wave", type=int, required=True)
    p_run.add_argument(
        "--profile",
        choices=PROFILES,
        default="rescore",
        help="smoke=10-record test | wave=full generate | rescore=re-evaluate existing | full=tests+wave",
    )
    p_run.add_argument("--max-records", type=int, default=None, help="cap generate (smoke defaults to 10)")
    p_run.add_argument("--rate-per-minute", type=int, default=None)
    p_run.add_argument("--skip-tests", action="store_true", help="skip pytest in smoke/full setup")

    p_all = sub.add_parser("all", help="alias for run --profile smoke|wave")
    p_all.add_argument("--wave", type=int, required=True)
    p_all.add_argument("--max-records", type=int, default=None)
    p_all.add_argument("--rate-per-minute", type=int, default=None)
    p_all.add_argument("--skip-tests", action="store_true")
    p_all.add_argument("--skip-setup", action="store_true", help="deprecated; use run --profile wave --skip-tests")

    p_steps = sub.add_parser("steps", help="print step list for a profile")
    p_steps.add_argument("--wave", type=int, required=True)
    p_steps.add_argument("--max-records", type=int, default=None)

    p_step = sub.add_parser("step", help="run one named step")
    p_step.add_argument(
        "step_name",
        choices=["setup", "plan", "generate", "gate-a", "export", "audit", "preflight", "train", "gate-b", "kpi"],
    )
    p_step.add_argument("--wave", type=int, default=None)
    p_step.add_argument("--max-records", type=int, default=None)
    p_step.add_argument("--rate-per-minute", type=int, default=None)
    p_step.add_argument("--skip-tests", action="store_true")

    p_audit = sub.add_parser("audit", help="summarize Gate A + record counts")
    p_audit.add_argument("--wave", type=int, required=True)

    p_kpi = sub.add_parser("kpi", help="12-dimension KPI scorecard")
    p_kpi.add_argument("--wave", type=int, required=True)
    p_kpi.add_argument("--json", action="store_true")

    p_preflight = sub.add_parser("preflight", help="training + Gate B readiness")
    p_preflight.add_argument("--wave", type=int, required=True)

    p_rescore = sub.add_parser("rescore", help="alias for run --profile rescore")
    p_rescore.add_argument("--wave", type=int, required=True)

    args = ap.parse_args()
    if args.mode == "run":
        return cmd_run(args)
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
        return _run_subprocess("kpi", cmd, stop_on_fail=False)
    if args.mode == "preflight":
        return _run_subprocess("preflight", [_py(), "-m", "cold_chain.runner", "preflight", "--wave", str(args.wave)])
    if args.mode == "rescore":
        return cmd_rescore(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
