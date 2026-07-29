"""Real-time processing simulation: feeds pipeline output through the
guardrail + rule-engine layer one record at a time, as if it were a live
agent consuming a stream of incoming artifacts, instead of a batch job.

No LLM calls are made here -- this exercises exactly the deterministic layer
a deployed agent would gate on before ever handing an artifact to the
student model (`guardrails.check_artifact_text`), so it can run at real
interactive speed over the full corpus and still show meaningful per-record
latency instead of dominating it with network time.

Prints a running, single-line-updating status (records/sec, violation rate,
disposition mix) plus a full line for every record that gets flagged, and a
final summary block. `--shuffle` reorders records randomly first so the
"stream" isn't just replaying generation order; `--delay` adds an artificial
per-record pause to mimic a slower real-world arrival rate instead of
processing as fast as the CPU allows.

Usage:

    python scripts/live_stream_demo.py --wave 1
    python scripts/live_stream_demo.py --wave 1 --shuffle --delay 0.05
    python scripts/live_stream_demo.py --export exports/generation_log.jsonl --limit 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from cold_chain import guardrails as gr  # noqa: E402


# --------------------------------------------------------------------------- #
# loading records (same contract as audit_corpus_guardrails.py)
# --------------------------------------------------------------------------- #

async def load_from_mongo(wave: int | None) -> list[dict[str, Any]]:
    from cold_chain.config import get_settings
    from cold_chain.logbook import Logbook

    settings = get_settings()
    async with Logbook(settings, run_id="live-stream-demo") as book:
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
            if row.get("outcome") in (None, "kept"):
                rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# the simulation
# --------------------------------------------------------------------------- #

def _status_line(i: int, n: int, elapsed: float, violations: int, dispositions: Counter) -> str:
    rate = i / elapsed if elapsed > 0 else 0.0
    top = ", ".join(f"{k}={v}" for k, v in dispositions.most_common(3))
    return (f"\r[{i:>6}/{n}] {rate:6.1f} rec/s  violations={violations:>4} "
            f"({violations/i*100:5.1f}%)  {top}").ljust(110)


async def run_stream(rows: list[dict[str, Any]], delay: float, verbose_flags: bool) -> dict[str, Any]:
    n = len(rows)
    dispositions: Counter = Counter()
    rule_id_counts: Counter = Counter()
    violations = 0
    per_record_latencies: list[float] = []

    print(f"Streaming {n} record(s) as if arriving live "
          f"({'no artificial delay' if delay <= 0 else f'{delay}s between records'})...\n")

    start = time.perf_counter()
    for i, r in enumerate(rows, start=1):
        t0 = time.perf_counter()
        hits = gr.check_artifact_text(r.get("rendered_text", ""), r.get("artifact_type"))
        latency = time.perf_counter() - t0
        per_record_latencies.append(latency)

        dispositions[r.get("disposition", "unknown")] += 1
        if hits:
            violations += 1
            for h in hits:
                rule_id_counts[h.rule_id] += 1
            if verbose_flags:
                print()  # move off the status line before printing a flagged record
                print(f"  FLAGGED  state_id={r.get('state_id')}  cell={r.get('cell')}  "
                      f"jurisdiction={r.get('jurisdiction')}  rules={[h.rule_id for h in hits]}")

        elapsed = time.perf_counter() - start
        sys.stdout.write(_status_line(i, n, elapsed, violations, dispositions))
        sys.stdout.flush()

        if delay > 0:
            await asyncio.sleep(delay)

    print()  # newline after the final status line
    total_elapsed = time.perf_counter() - start
    return {
        "n": n, "violations": violations, "rule_id_counts": rule_id_counts,
        "dispositions": dispositions, "total_elapsed_s": total_elapsed,
        "throughput_per_s": (n / total_elapsed) if total_elapsed > 0 else float("inf"),
        "mean_latency_ms": (sum(per_record_latencies) / len(per_record_latencies) * 1000) if per_record_latencies else 0.0,
        "p99_latency_ms": (sorted(per_record_latencies)[int(len(per_record_latencies) * 0.99) - 1] * 1000
                           if per_record_latencies else 0.0),
    }


def print_summary(result: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("Stream complete")
    print("=" * 60)
    print(f"Records processed:     {result['n']}")
    print(f"Wall-clock time:       {result['total_elapsed_s']:.2f}s")
    print(f"Throughput:            {result['throughput_per_s']:.1f} records/s "
          f"(guardrail-check layer only -- excludes any LLM round trip)")
    print(f"Mean per-record guardrail-check latency: {result['mean_latency_ms']:.3f}ms")
    print(f"p99 per-record guardrail-check latency:  {result['p99_latency_ms']:.3f}ms")
    print(f"Guardrail violations:  {result['violations']}/{result['n']} "
          f"({result['violations']/result['n']*100 if result['n'] else 0:.2f}%)")
    if result["rule_id_counts"]:
        print("By rule:")
        for rule_id, count in result["rule_id_counts"].most_common():
            print(f"  {rule_id}: {count}")
    print("Disposition mix seen in the stream:")
    for disp, count in result["dispositions"].most_common():
        print(f"  {disp}: {count}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", type=int, help="stream this wave's kept records (reads MongoDB)")
    ap.add_argument("--all-waves", action="store_true", help="stream every wave in the database")
    ap.add_argument("--export", type=Path, help="stream records from a local export/*.jsonl file instead")
    ap.add_argument("--limit", type=int, default=None, help="stop after this many records")
    ap.add_argument("--shuffle", action="store_true", help="randomize order first, to simulate arrival "
                                                             "not matching generation order")
    ap.add_argument("--delay", type=float, default=0.0, help="artificial per-record delay in seconds, "
                                                              "to simulate a slower real-world arrival rate "
                                                              "(default 0 -- process as fast as possible)")
    ap.add_argument("--quiet", action="store_true", help="suppress the per-flagged-record lines, "
                                                          "only show the live status line and final summary")
    args = ap.parse_args()

    if not any([args.wave, args.all_waves, args.export]):
        ap.error("pass --wave N, --all-waves, or --export path/to/file.jsonl")

    rows = (
        load_from_export(args.export)
        if args.export
        else await load_from_mongo(args.wave if not args.all_waves else None)
    )
    if args.shuffle:
        random.shuffle(rows)
    if args.limit:
        rows = rows[:args.limit]

    if not rows:
        print("No kept records to stream.")
        return 1

    result = await run_stream(rows, args.delay, verbose_flags=not args.quiet)
    print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
