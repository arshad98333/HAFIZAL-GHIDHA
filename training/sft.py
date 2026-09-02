"""Supervised fine-tuning entry point for Foundry/Azure ML jobs.

Invoked by the managed training adapter:

    python -m training.sft --wave 1 --base-model <checkpoint>

This module validates the export and prints the training configuration. The
actual GPU training loop is environment-specific (Foundry compute image);
this entry point is the contract the submitter calls and what local dry-runs
exercise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wave", type=int, required=True)
    ap.add_argument("--base-model", required=True)
    ap.add_argument("--export", type=Path, default=None, help="override export JSONL path")
    ap.add_argument("--dry-run", action="store_true", help="validate inputs only, do not train")
    args = ap.parse_args()

    export = args.export or (ROOT / "exports" / f"generation_log_wave{args.wave:02d}.jsonl")
    if not export.exists():
        print(f"error: export not found: {export}", file=sys.stderr)
        print("Run: python scripts/export_wave.py --wave", args.wave, file=sys.stderr)
        return 1

    records = [json.loads(line) for line in export.read_text(encoding="utf-8").splitlines() if line.strip()]
    holdout = [r for r in records if int(r.get("state_id", "0").encode().hex()[:8], 16) % 100 < 5]
    config = {
        "wave": args.wave,
        "base_model": args.base_model,
        "export_path": str(export),
        "n_records": len(records),
        "n_holdout_excluded": len(holdout),
        "n_train": len(records) - len(holdout),
        "dry_run": args.dry_run,
    }
    print(json.dumps(config, indent=2))
    if args.dry_run:
        print("dry-run: training inputs validated", file=sys.stderr)
        return 0
    print(
        "Training loop runs on Foundry compute (azureml:cold-chain-sft@latest). "
        "Submit via: python -m cold_chain.runner train --wave",
        args.wave,
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
