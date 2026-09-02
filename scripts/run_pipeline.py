"""Single-command orchestrator: runs plan, generate, Gate A, export, guardrail
audit, and the tied-together system report for one wave, in order, printing
each stage's real output as it happens.

This does not reimplement any pipeline logic -- it calls the same, already
tested entry points (`cold_chain.runner`, `scripts/export_wave.py`,
`scripts/audit_corpus_guardrails.py`, `scripts/generate_system_report.py`) as
subprocesses, in the sequence a person would otherwise type by hand from
MANUAL_TESTING_GUIDE.md. The point is one command and full visibility into
every step, not a black box.

    python scripts/run_pipeline.py --wave 1 --max-records 10   # cheap smoke run
    python scripts/run_pipeline.py --wave 1                    # full 663-record wave

Gate A is a real blocking checkpoint. If it halts the wave (exit code 2, the
existing WaveHalted contract in cold_chain/runner.py), this script does not
treat that as a crash -- it still runs export and audit so you can see why,
then stops before generate_system_report reports on the halt. Any other
non-zero exit code from plan or generate is treated as a real failure and
stops the run immediately, since nothing after that stage would mean anything.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE_A_HALTED = 2


def _run(label: str, cmd: list[str]) -> int:
    print(f"\n{'=' * 70}\n[{label}]  {' '.join(cmd)}\n{'=' * 70}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    status = "ok" if result.returncode == 0 else f"exit code {result.returncode}"
    print(f"[{label}] finished: {status}", flush=True)
    return result.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", type=int, required=True)
    ap.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="cap generate at this many records, for a cheap end-to-end smoke run",
    )
    ap.add_argument("--rate-per-minute", type=int, default=None)
    ap.add_argument(
        "--review-limit",
        type=int,
        default=20,
        help="records sent through the second-pass Azure review in the final "
        "report; 0 skips that section (no extra API calls)",
    )
    args = ap.parse_args()

    py = sys.executable
    wave = args.wave
    stages_run: list[tuple[str, str]] = []

    rc = _run("1/5 plan", [py, "-m", "cold_chain.runner", "plan", "--wave", str(wave)])
    stages_run.append(("plan", "ok" if rc == 0 else f"FAILED ({rc})"))
    if rc != 0:
        print("\nplan failed -- stopping. Nothing downstream would be meaningful without a plan.")
        return rc

    generate_cmd = [py, "-m", "cold_chain.runner", "generate", "--wave", str(wave)]
    if args.max_records is not None:
        generate_cmd += ["--max-records", str(args.max_records)]
    if args.rate_per_minute is not None:
        generate_cmd += ["--rate-per-minute", str(args.rate_per_minute)]
    rc = _run("2/5 generate", generate_cmd)
    stages_run.append(("generate", "ok" if rc == 0 else f"FAILED ({rc})"))
    if rc != 0:
        print(
            "\ngenerate failed -- stopping. Check the log above for the real cause "
            "(most often: Azure auth, or a plan.json left over from an older schema -- "
            "see scripts/reset_pipeline_state.py)."
        )
        return rc

    rc = _run("3/5 gate-a", [py, "-m", "cold_chain.runner", "gate-a", "--wave", str(wave)])
    gate_a_halted = rc == GATE_A_HALTED
    stages_run.append(
        (
            "gate-a",
            "PASSED" if rc == 0 else ("HALTED (see decisions log)" if gate_a_halted else f"FAILED ({rc})"),
        )
    )
    if rc not in (0, GATE_A_HALTED):
        print(
            f"\ngate-a exited {rc}, which is not the expected halt code ({GATE_A_HALTED}) -- "
            "that means it crashed rather than made a decision. Stopping; this needs a look "
            "before anything downstream is trusted."
        )
        return rc

    _run("4/5 export", [py, str(ROOT / "scripts" / "export_wave.py"), "--wave", str(wave)])
    stages_run.append(("export", "done"))

    audit_out = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{wave:02d}.md"
    audit_csv = ROOT / f"CORPUS_GUARDRAIL_AUDIT_wave{wave:02d}.csv"
    _run(
        "5/5 guardrail audit",
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
    )
    stages_run.append(("guardrail audit", f"written to {audit_out.name}"))

    if not gate_a_halted:
        report_out = ROOT / f"SYSTEM_EVALUATION_REPORT_wave{wave:02d}.md"
        _run(
            "bonus: tied-together report",
            [
                py,
                str(ROOT / "scripts" / "generate_system_report.py"),
                "--wave",
                str(wave),
                "--review-limit",
                str(args.review_limit),
                "--out",
                str(report_out),
            ],
        )
        stages_run.append(("system report", f"written to {report_out.name}"))
    else:
        print(
            "\nSkipping the tied-together report: Gate A halted this wave, so there is "
            "no passing data quality result to report on yet. Read the audit output above "
            "and the wave's decisions log to see why, fix it, then rerun."
        )

    print(f"\n{'=' * 70}\nSummary, wave {wave}\n{'=' * 70}")
    for name, status in stages_run:
        print(f"  {name:<18} {status}")

    return 2 if gate_a_halted else 0


if __name__ == "__main__":
    raise SystemExit(main())
