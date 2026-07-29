"""Clear pipeline-owned MongoDB collections so a fresh `plan` / `generate` run
isn't reading state shaped for an older schema.

Why this exists: `coverage_state`, `wave_artifacts.plan.json`, etc. are
schema-coupled to whatever version of cold_chain wrote them (cell targets,
the language/jurisdiction covariates, wave definitions). If you've run this
pipeline against the same MONGODB_DB_NAME before a schema change -- e.g. the
5,304-record / 8-wave / jurisdiction-covariate redesign -- `curriculum.
build_plan` will see old coverage as "already at target" (`no eligible
cells`) and `generate` will explode on a covariate value the current code no
longer knows about (e.g. `code_switched`). Mixing schema versions in one
database is not safe to patch around; clear it and start the wave sequence
over.

This does NOT touch `access_audit` (compliance trail, kept forever) or the
golden set (which was never in this database to begin with -- see README
"Standing constraints" #2).

Usage:

    python scripts/reset_pipeline_state.py --dry-run          # see what would be dropped
    python scripts/reset_pipeline_state.py --yes              # actually drop it
    python scripts/reset_pipeline_state.py --yes --wave 1      # only wave-scoped docs for wave 1
                                                                 # (coverage_state is a running
                                                                 # aggregate across waves and is
                                                                 # NOT touched by --wave; see the
                                                                 # warning this prints)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from cold_chain.config import get_settings  # noqa: E402
from cold_chain.logbook import Logbook  # noqa: E402

# access_audit is deliberately excluded -- compliance trail, never cleared by this tool.
FULL_RESET_COLLECTIONS = [
    "ledger", "coverage_state", "generation_log", "wave_artifacts",
    "decisions", "autoresearch_log", "gate_b_deliberation", "live_logs",
]
WAVE_SCOPED_COLLECTIONS = ["generation_log", "wave_artifacts", "decisions", "gate_b_deliberation"]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", type=int, help="only clear this wave's documents (coverage_state and "
                                              "ledger are NOT touched -- see warning)")
    ap.add_argument("--dry-run", action="store_true", help="print counts, delete nothing")
    ap.add_argument("--yes", action="store_true", help="required to actually delete anything")
    args = ap.parse_args()

    if not args.dry_run and not args.yes:
        print("Refusing to delete anything without --yes (or pass --dry-run to just see counts).")
        return 1

    settings = get_settings()
    async with Logbook(settings, run_id="reset-tool") as book:
        db = book.db
        if args.wave is not None:
            print(f"Wave-scoped reset: wave {args.wave} only.")
            print("NOTE: coverage_state is a running aggregate across all waves and is NOT reset "
                  "by --wave. If the schema changed (cell targets, covariates, wave definitions), "
                  "run a full reset instead (omit --wave) -- a partial reset will leave stale "
                  "aggregate counts behind.")
            query = {"wave": args.wave}
            for name in WAVE_SCOPED_COLLECTIONS:
                n = await db[name].count_documents(query)
                print(f"  {name}: {n} document(s) match wave={args.wave}")
                if args.yes:
                    result = await db[name].delete_many(query)
                    print(f"    deleted {result.deleted_count}")
        else:
            print("Full reset: ledger, coverage_state, generation_log, wave_artifacts, decisions, "
                  "autoresearch_log, gate_b_deliberation, live_logs. access_audit is kept.")
            for name in FULL_RESET_COLLECTIONS:
                n = await db[name].count_documents({})
                print(f"  {name}: {n} document(s)")
                if args.yes:
                    result = await db[name].delete_many({})
                    print(f"    deleted {result.deleted_count}")

    if args.dry_run:
        print("\n--dry-run: nothing was deleted. Re-run with --yes to actually clear this.")
    else:
        print("\nDone. `plan --wave 1` will start the wave sequence over on the current schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
