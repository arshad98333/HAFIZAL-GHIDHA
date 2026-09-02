"""Builds a Markdown report on how the pipeline is performing as a system --
data generation, guardrail enforcement, and a second-pass review -- for a
given wave.

This must be run somewhere with real network access to MongoDB Atlas and the
Azure OpenAI deployment. It pulls together:

  - Gate A results (data quality) for the wave, if `gate-a` has been run
  - Gate B results (model quality), if available
  - Coverage stats: per-cell fill, artifact-type and jurisdiction balance
  - Drop-reason breakdown (schema/screener/guardrail/roundtrip/etc.)
  - A review of a sample of kept records via `scripts/azure_review.py`
    (Azure OpenAI's Responses API, same deployment as the pipeline itself --
    see that script's module docstring for exactly what this does and does
    not tell you; it is not a cross-provider check)

Usage:

    python scripts/generate_system_report.py --wave 1 --review-limit 20 \\
        --out SYSTEM_EVALUATION_REPORT.md

Omit --review-limit (or pass 0) to skip the review section and produce a
report from pipeline-internal data only.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so `import azure_review` resolves as a sibling module

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import azure_review  # noqa: E402 -- sibling script, same scripts/ directory

from cold_chain.config import get_settings  # noqa: E402
from cold_chain.logbook import Logbook  # noqa: E402


async def gather_pipeline_data(wave: int) -> dict[str, Any]:
    settings = get_settings()
    async with Logbook(settings, run_id="system-report") as book:
        plan = await book.read_json(wave, "plan.json")
        gate_a = await book.read_json(wave, "gate_a.json")
        gate_b = await book.read_json(wave, "gate_b.json")
        coverage = await book.load_coverage()
        rows = await book.read_generation(wave)
        decisions = await book.read_decisions(wave)
    return {
        "wave": wave,
        "plan": plan,
        "gate_a": gate_a,
        "gate_b": gate_b,
        "coverage": coverage,
        "rows": rows,
        "decisions": decisions,
    }


def _drop_reasons(rows: list[dict[str, Any]]) -> Counter:
    return Counter(r["outcome"] for r in rows if r.get("outcome") != "kept")


def _fmt_metric_table(metrics: dict[str, Any], checks: dict[str, Any] | None) -> str:
    if not checks:
        return "\n".join(f"- `{k}`: {v}" for k, v in metrics.items())
    lines = ["| Metric | Value | Bound | Result |", "|---|---|---|---|"]
    for name, c in checks.items():
        lines.append(
            f"| `{name}` | {c['value']} | {c.get('op', '')} {c['bound']} | {'PASS' if c['passed'] else 'FAIL'} |"
        )
    return "\n".join(lines)


async def build_report(wave: int, review_limit: int) -> str:
    data = await gather_pipeline_data(wave)
    rows, plan, gate_a, gate_b = data["rows"], data["plan"], data["gate_a"], data["gate_b"]
    kept = [r for r in rows if r.get("outcome") == "kept"]
    drops = _drop_reasons(rows)
    cov = data["coverage"]

    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append(f"# System Evaluation Report -- Wave {wave}")
    lines.append("")
    lines.append(
        f"Generated {now}. Covers data generation, guardrail enforcement, and (if requested) "
        "a second-pass review, for this wave only. Not a replacement for the sealed golden-set "
        'evaluation (README "Standing constraints" #2).'
    )
    lines.append("")

    # -- architecture recap -------------------------------------------------
    lines.append("## 1. System under evaluation")
    lines.append("")
    lines.append(
        "A student model is trained to read messy GCC cold-chain field artifacts and emit a strict-JSON "
        "disposition. Every ground-truth label in this wave came from `cold_chain/rules_engine.py`, a pure "
        "Python function -- never a language model. Its thresholds and the guardrail checks applied to "
        "every rendered artifact both trace to `gcc_food_law_json/` (six GCC country food-law profiles) "
        'and `guardrails/` (the 85-rule pack derived from it). See README "The knowledge base and '
        'guardrail pack" for the full wiring.'
    )
    lines.append("")

    # -- volume / coverage ---------------------------------------------------
    lines.append("## 2. Volume and coverage")
    lines.append("")
    total = len(rows)
    lines.append(f"- Requested: {plan['total'] if plan else 'unknown (no plan.json for this wave)'}")
    lines.append(f"- Attempted: {total}")
    lines.append(f"- Kept: {len(kept)} ({(len(kept) / total * 100 if total else 0):.1f}% survival)")
    if drops:
        lines.append("- Dropped, by reason:")
        for reason, n in drops.most_common():
            lines.append(f"  - `{reason}`: {n}")
    lines.append("")
    lines.append("Per-cell fill (kept records):")
    lines.append("")
    lines.append("| Cell | Kept | Requested (cumulative) | Last wave touched |")
    lines.append("|---|---|---|---|")
    for cell, c in sorted(cov.get("cells", {}).items()):
        lines.append(f"| `{cell}` | {c.get('kept', 0)} | {c.get('requested', 0)} | {c.get('last_wave', 0)} |")
    lines.append("")
    lines.append(f"Jurisdiction balance (cumulative, kept): {cov.get('jurisdictions', {})}")
    lines.append("")
    lines.append(f"Artifact-type balance (cumulative, kept): {cov.get('artifacts', {})}")
    lines.append("")

    # -- Gate A ---------------------------------------------------------------
    lines.append("## 3. Gate A -- data quality")
    lines.append("")
    if gate_a:
        lines.append(f"Result: **{'PASS' if gate_a.get('passed') else 'FAIL'}**")
        lines.append("")
        lines.append(_fmt_metric_table(gate_a.get("metrics", {}), gate_a.get("checks")))
        if gate_a.get("failures"):
            lines.append("")
            lines.append("Failures:")
            for f in gate_a["failures"]:
                lines.append(f"- {f}")
    else:
        lines.append(
            f"No `gate_a.json` found for this wave -- run `python -m cold_chain.runner gate-a --wave {wave}` first."
        )
    lines.append("")

    # -- Gate B ---------------------------------------------------------------
    lines.append("## 4. Gate B -- model quality")
    lines.append("")
    if gate_b:
        lines.append(f"Gatekeeper: `{gate_b.get('gatekeeper', 'human-sealed-eval')}`")
        lines.append(
            f"Result: **{'PASS' if gate_b.get('passed') else 'FAIL'}**  (ratchet: {gate_b.get('ratchet_note', 'n/a')})"
        )
        lines.append("")
        lines.append(_fmt_metric_table(gate_b.get("metrics", {}), gate_b.get("checks")))
        lines.append("")
        lines.append(
            f"Worst cell: `{gate_b.get('worst_cell', 'n/a')}` @ "
            f"{gate_b.get('worst_cell_f1', 'n/a')}, "
            f"{gate_b.get('cells_passing', 'n/a')} cells passing 0.80."
        )
    else:
        lines.append(
            "No `gate_b.json` found for this wave -- Gate B has not run yet (needs a trained "
            "checkpoint deployed, or a human-sealed-eval results file)."
        )
    lines.append("")

    # -- second-pass review ---------------------------------------------------
    lines.append("## 5. Second-pass review (Azure OpenAI Responses API)")
    lines.append("")
    lines.append(
        "**Note:** this reviewer calls the same Azure OpenAI deployment the pipeline itself uses "
        "for rendering, screening, and its own Gate A/B judging, just through a different API "
        "surface. It is a structurally separate second pass, not an independently-trained "
        "second opinion -- a systematic blind spot in this deployment's judgment will not be "
        "caught here. See `scripts/azure_review.py`'s module docstring."
    )
    lines.append("")
    if review_limit <= 0:
        lines.append(
            "Skipped (`--review-limit 0` or omitted). Run again with `--review-limit N` to "
            "include a review of a sample of kept records."
        )
    elif not kept:
        lines.append("Skipped -- no kept records to sample from this wave.")
    else:
        try:
            reviewer_settings = azure_review.get_reviewer_settings()
        except SystemExit as exc:
            lines.append(f"Skipped -- {exc}")
            reviewer_settings = None
        if reviewer_settings is not None:
            sample = kept[:review_limit]
            lines.append(
                f"Sampled {len(sample)}/{len(kept)} kept records, reviewed by "
                f"`{reviewer_settings.deployment}` via the Responses API, no output token cap. "
                "Only the rendered artifact and the assigned disposition were shown to it -- "
                "see `scripts/azure_review.py`'s prompt for exactly what it was asked."
            )
            lines.append("")
            results = await azure_review.gather_reviews(sample)
            summary = azure_review.summarize_reviews(results)
            lines.append(
                f"- Agreement rate: {summary['agreement_rate'] * 100:.1f}% ({summary['agree']}/{summary['n']})"
            )
            lines.append(f"- Disagreements: {summary['disagree']}")
            lines.append(f"- Errored calls: {summary['errored']}")
            lines.append(f"- Flagged a concern: {len(summary['flagged'])}")
            lines.append("")
            if summary["disagree"] or summary["flagged"]:
                lines.append("Items the reviewer disagreed with or flagged:")
                lines.append("")
                lines.append("| Cell | Jurisdiction | Pipeline | Reviewer | Concerns |")
                lines.append("|---|---|---|---|---|")
                for r in results:
                    rv = r["review"]
                    if "error" in rv:
                        continue
                    if rv.get("agrees") is False or rv.get("concerns") not in ([], ["none"], None):
                        lines.append(
                            f"| `{r['cell']}` | {r['jurisdiction']} | {r['pipeline_disposition']} | "
                            f"{rv.get('your_disposition', '?')} | {rv.get('concerns', [])} |"
                        )
                lines.append("")
                lines.append(
                    "Every disagreement/flag here is either a real pipeline defect (worth filing "
                    "against `rules_engine.py`, `simulate.py`, or `guardrails.py`) or a case where "
                    "the reviewer's own judgment is wrong -- both are worth reading the artifact "
                    "text for before concluding which."
                )

    lines.append("")
    lines.append("## 6. Recommendation")
    lines.append("")
    gate_a_ok = bool(gate_a and gate_a.get("passed"))
    gate_b_ok = gate_b is None or bool(gate_b.get("passed"))
    if gate_a_ok and gate_b_ok:
        lines.append(
            "Gate A passed (and Gate B passed or has not run yet). No blocking data-quality issue "
            "found by the pipeline's own gates. If the review above surfaced disagreements, read "
            "them before treating this wave as trustworthy -- remember it is a same-deployment "
            "second pass, not independent corroboration."
        )
    else:
        lines.append(
            "At least one gate failed for this wave. Do not proceed to `train` (or trust this "
            "wave's data) until the failures listed in section 3/4 above are resolved and the "
            "gate is re-run."
        )

    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", type=int, required=True)
    ap.add_argument(
        "--review-limit",
        type=int,
        default=20,
        help="how many kept records to run through the second-pass review; 0 to skip",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output path (default: SYSTEM_EVALUATION_REPORT_wave<N>.md)",
    )
    args = ap.parse_args()

    out = args.out or Path(f"SYSTEM_EVALUATION_REPORT_wave{args.wave:02d}.md")
    report = await build_report(args.wave, args.review_limit)
    out.write_text(report, encoding="utf-8")
    print(f"Wrote {out} ({len(report)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
