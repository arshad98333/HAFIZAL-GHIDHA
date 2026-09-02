"""Export generation_log (or any collection) out of MongoDB into a local file,
for eyeballing or feeding to a training script. Mongo stays the source of
truth; this is a view, never the thing you edit.

    python scripts/export_wave.py                      # ALL waves, kept-only, JSONL
    python scripts/export_wave.py --wave 1              # just wave 1, kept-only
    python scripts/export_wave.py --all                 # every outcome, not just kept
    python scripts/export_wave.py --format csv
    python scripts/export_wave.py --collection ledger    # any collection, not just generation_log
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from cold_chain.config import get_settings  # noqa: E402
from cold_chain.logbook import Logbook  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", type=int, help="omit to export every wave")
    ap.add_argument(
        "--collection",
        default="generation_log",
        help="any Mongo collection name (generation_log, ledger, decisions, "
        "wave_artifacts, autoresearch_log, gate_b_deliberation, live_logs)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="generation_log only: include dropped records, not just kept",
    )
    ap.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    ap.add_argument("--out", help="output path (default: exports/<collection>[_wave<N>].<ext>)")
    args = ap.parse_args()

    settings = get_settings()
    suffix = f"_wave{args.wave:02d}" if args.wave is not None else ""
    out = Path(args.out) if args.out else Path("exports") / f"{args.collection}{suffix}.{args.format}"
    out.parent.mkdir(parents=True, exist_ok=True)

    async with Logbook(settings, run_id="export") as book:
        query = {"wave": args.wave} if args.wave is not None else {}
        rows = await book.db[args.collection].find(query).to_list(length=None)

    if args.collection == "generation_log" and not args.all:
        rows = [r for r in rows if r["outcome"] == "kept"]
    for r in rows:
        r.pop("_id", None)

    if args.format == "jsonl":
        with out.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    else:
        if rows:
            fieldnames = sorted({k for r in rows for k in r})
            with out.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    print(f"wrote {len(rows)} records from {settings.mongodb_db_name}.{args.collection} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
