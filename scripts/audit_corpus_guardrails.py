"""Full-corpus guardrail quality audit.

Scans every *kept* record in a wave (or the whole corpus, `--all-waves`) and
checks it against the guardrail pack's mechanically-checkable rules:

  - `guardrails.check_artifact_text` -- metadata leakage (GCC-EDGE-018),
    expedite_sale wording (GCC-EDGE-015), a truncated logger_csv tail
    (GCC-EDGE-002)
  - GCC-EDGE-015 compliance as a corpus-wide invariant: no kept record's
    disposition is ever `expedite_sale` (the rule engine should never emit
    it -- see `rules_engine.py`; this re-checks it held for every record
    actually generated, not just in a unit test)
  - the pipeline's own stored quality flags (`schema_valid`, `round_trip_ok`,
    `screener_verdict`, `confidence`) so a quality issue that's concentrated
    in one product/fault-mode/country/artifact combination is visible, not
    averaged away in an aggregate rate

This is a read-only audit over records the pipeline already generated and
kept -- it makes no LLM calls, so it runs at the speed of the guardrail
regexes and can comfortably cover the full ~5,304-record corpus in seconds.

Usage:

    python scripts/audit_corpus_guardrails.py --wave 1
    python scripts/audit_corpus_guardrails.py --all-waves
    python scripts/audit_corpus_guardrails.py --export exports/generation_log.jsonl
    python scripts/audit_corpus_guardrails.py --all-waves \\
        --out CORPUS_GUARDRAIL_AUDIT.md --csv CORPUS_GUARDRAIL_AUDIT.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from cold_chain import guardrails as gr  # noqa: E402

# --------------------------------------------------------------------------- #
# loading records
# --------------------------------------------------------------------------- #


async def load_from_mongo(wave: int | None) -> list[dict[str, Any]]:
    from cold_chain.config import get_settings
    from cold_chain.logbook import Logbook

    settings = get_settings()
    async with Logbook(settings, run_id="corpus-audit") as book:
        if wave is not None:
            rows = await book.read_generation(wave)
        else:
            rows = await book.db.generation_log.find({}).to_list(length=None)
    return [r for r in rows if r.get("outcome") == "kept"]


def load_from_export(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("outcome") in (None, "kept"):  # export defaults to kept-only already
                rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# the audit itself
# --------------------------------------------------------------------------- #


def audit_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    violations: list[dict[str, Any]] = []
    rule_id_counts: Counter = Counter()
    by_cell: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "violations": 0})
    by_jurisdiction: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "violations": 0})
    by_artifact: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "violations": 0})
    disposition_counts: Counter = Counter()
    schema_valid_n = round_trip_ok_n = 0
    screener_counts: Counter = Counter()
    confidences: list[float] = []
    expedite_sale_hits: list[dict[str, Any]] = []

    for r in rows:
        cell = r.get("cell", "unknown")
        jurisdiction = r.get("jurisdiction", "unknown")
        artifact_type = r.get("artifact_type", "unknown")
        disposition = r.get("disposition", "unknown")
        text = r.get("rendered_text", "")

        by_cell[cell]["n"] += 1
        by_jurisdiction[jurisdiction]["n"] += 1
        by_artifact[artifact_type]["n"] += 1
        disposition_counts[disposition] += 1
        if r.get("schema_valid"):
            schema_valid_n += 1
        if r.get("round_trip_ok"):
            round_trip_ok_n += 1
        if r.get("screener_verdict"):
            screener_counts[r["screener_verdict"]] += 1
        if isinstance(r.get("confidence"), (int, float)):
            confidences.append(r["confidence"])

        if disposition == "expedite_sale":
            expedite_sale_hits.append(r)

        hits = gr.check_artifact_text(text, artifact_type)
        if hits:
            by_cell[cell]["violations"] += 1
            by_jurisdiction[jurisdiction]["violations"] += 1
            by_artifact[artifact_type]["violations"] += 1
            for h in hits:
                rule_id_counts[h.rule_id] += 1
            violations.append(
                {
                    "state_id": r.get("state_id"),
                    "cell": cell,
                    "jurisdiction": jurisdiction,
                    "artifact_type": artifact_type,
                    "disposition": disposition,
                    "rule_ids": [h.rule_id for h in hits],
                    "details": [h.detail for h in hits],
                }
            )

    return {
        "n": n,
        "violations": violations,
        "violation_rate": (len(violations) / n) if n else 0.0,
        "rule_id_counts": rule_id_counts,
        "by_cell": dict(by_cell),
        "by_jurisdiction": dict(by_jurisdiction),
        "by_artifact": dict(by_artifact),
        "disposition_counts": disposition_counts,
        "schema_valid_rate": (schema_valid_n / n) if n else 0.0,
        "round_trip_ok_rate": (round_trip_ok_n / n) if n else 0.0,
        "screener_counts": screener_counts,
        "mean_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        "expedite_sale_hits": expedite_sale_hits,
    }


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def _rate_table(breakdown: dict[str, dict[str, Any]]) -> str:
    lines = ["| Key | N | Violations | Rate |", "|---|---|---|---|"]
    for key, d in sorted(breakdown.items()):
        rate = (d["violations"] / d["n"]) if d["n"] else 0.0
        lines.append(f"| `{key}` | {d['n']} | {d['violations']} | {rate * 100:.1f}% |")
    return "\n".join(lines)


def render_report(audit: dict[str, Any], scope: str) -> str:
    lines: list[str] = []
    lines.append(f"# Corpus guardrail audit -- {scope}")
    lines.append("")
    lines.append(f"Kept records scanned: **{audit['n']}**")
    lines.append(
        f"Overall guardrail violation rate: **{audit['violation_rate'] * 100:.2f}%** "
        f"({len(audit['violations'])} record(s))"
    )
    lines.append(f"`schema_valid` rate: {audit['schema_valid_rate'] * 100:.2f}%")
    lines.append(f"`round_trip_ok` rate: {audit['round_trip_ok_rate'] * 100:.2f}%")
    if audit["mean_confidence"] is not None:
        lines.append(f"Mean round-trip confidence: {audit['mean_confidence']:.3f}")
    lines.append("")

    lines.append("## GCC-EDGE-015 invariant: expedite_sale never autonomously emitted")
    lines.append("")
    if audit["expedite_sale_hits"]:
        lines.append(
            f"**VIOLATED** -- {len(audit['expedite_sale_hits'])} kept record(s) carry "
            "disposition `expedite_sale`. This should be structurally impossible "
            "(`rules_engine.py` never emits it); if this is non-zero, either an older "
            "wave predates the fix or something regressed. State IDs:"
        )
        for r in audit["expedite_sale_hits"][:20]:
            lines.append(f"- `{r.get('state_id')}` ({r.get('cell')})")
    else:
        lines.append("Held: 0 kept records with `expedite_sale`.")
    lines.append("")

    lines.append("## Violations by rule")
    lines.append("")
    if audit["rule_id_counts"]:
        lines.append("| Rule | Count |")
        lines.append("|---|---|")
        for rule_id, count in audit["rule_id_counts"].most_common():
            rule = gr.rule_by_id(rule_id)
            title = rule["title"] if rule else "?"
            lines.append(f"| `{rule_id}` -- {title} | {count} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Breakdown by cell (product|fault_mode)")
    lines.append("")
    lines.append(_rate_table(audit["by_cell"]))
    lines.append("")
    lines.append("## Breakdown by jurisdiction")
    lines.append("")
    lines.append(_rate_table(audit["by_jurisdiction"]))
    lines.append("")
    lines.append("## Breakdown by artifact type")
    lines.append("")
    lines.append(_rate_table(audit["by_artifact"]))
    lines.append("")

    lines.append("## Disposition distribution")
    lines.append("")
    lines.append("| Disposition | Count | Share |")
    lines.append("|---|---|---|")
    total = sum(audit["disposition_counts"].values()) or 1
    for disp, count in audit["disposition_counts"].most_common():
        lines.append(f"| `{disp}` | {count} | {count / total * 100:.1f}% |")
    lines.append("")

    lines.append(
        "## Screener verdict distribution (kept records only -- non-CONSISTENT "
        "would already have been dropped, so this should be ~100% CONSISTENT)"
    )
    lines.append("")
    for verdict, count in audit["screener_counts"].most_common():
        lines.append(f"- `{verdict}`: {count}")
    lines.append("")

    if audit["violations"]:
        lines.append("## Sample flagged records (first 20)")
        lines.append("")
        lines.append("| State ID | Cell | Jurisdiction | Disposition | Rules |")
        lines.append("|---|---|---|---|---|")
        for v in audit["violations"][:20]:
            lines.append(
                f"| `{v['state_id']}` | `{v['cell']}` | {v['jurisdiction']} | "
                f"{v['disposition']} | {', '.join(v['rule_ids'])} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def write_csv(audit: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "state_id",
                "cell",
                "jurisdiction",
                "artifact_type",
                "disposition",
                "rule_ids",
                "details",
            ],
        )
        writer.writeheader()
        for v in audit["violations"]:
            writer.writerow({**v, "rule_ids": ";".join(v["rule_ids"]), "details": " | ".join(v["details"])})


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", type=int, help="audit only this wave (reads MongoDB)")
    ap.add_argument("--all-waves", action="store_true", help="audit every wave in the database")
    ap.add_argument("--export", type=Path, help="audit records from a local export/*.jsonl file instead")
    ap.add_argument("--out", type=Path, default=Path("CORPUS_GUARDRAIL_AUDIT.md"))
    ap.add_argument("--csv", type=Path, default=None, help="also write per-violation detail rows to this CSV")
    args = ap.parse_args()

    if not any([args.wave, args.all_waves, args.export]):
        ap.error("pass --wave N, --all-waves, or --export path/to/file.jsonl")

    if args.export:
        rows = load_from_export(args.export)
        scope = f"export file `{args.export}`"
    else:
        rows = await load_from_mongo(args.wave if not args.all_waves else None)
        scope = f"wave {args.wave}" if args.wave else "all waves"

    print(f"Loaded {len(rows)} kept record(s) ({scope}). Running guardrail checks...")
    audit = audit_records(rows)
    report = render_report(audit, scope)
    args.out.write_text(report, encoding="utf-8")
    print(f"Wrote {args.out}")

    if args.csv:
        write_csv(audit, args.csv)
        print(f"Wrote {args.csv} ({len(audit['violations'])} violation row(s))")

    print(
        f"\nOverall violation rate: {audit['violation_rate'] * 100:.2f}%  "
        f"(threshold in gates.GATE_A['guardrail_violation_rate'] is <=1.00%)"
    )
    return 0 if audit["violation_rate"] <= 0.01 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
