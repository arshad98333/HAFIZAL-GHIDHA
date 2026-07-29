"""Standalone review/evaluation tool for pipeline output -- Azure OpenAI
Responses API edition.

This replaces an earlier version of this script that called K2-Think-v2 as
an independently-trained second model. K2 has been removed per request. Be
clear-eyed about what that trades away: this now calls the *same* Azure
OpenAI deployment (`AZURE_OPENAI_DEPLOYMENT`, gpt-5.4-mini by default) the
pipeline itself uses for rendering/screening/extraction and for its own
Gate A/B judging (`cold_chain/clients.py`, `agentic_eval.py`) -- just through
a different API surface (the Responses API, `client.responses.create`,
instead of Chat Completions). It is no longer a cross-provider check: a
systematic blind spot in gpt-5.4-mini's judgment will not be caught by
asking gpt-5.4-mini to review its own output. Treat this as a structurally
separate second pass, not an independent second opinion the way K2 was --
see README "Manually running and evaluating a wave" for the honest framing.

No output token cap is applied anywhere in this script, by request -- calls
may take longer and cost more per record as a result.

Setup: reuses this repo's existing `.env` (`AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_DEPLOYMENT`), auth is AAD via `DefaultAzureCredential` (same as
the pipeline itself -- `az login`, or managed identity in a job container).
Requires the `openai` package (`pip install openai`, in requirements-dev.txt).

Usage:

    # confirm the endpoint/credential/deployment work at all
    python scripts/azure_review.py --ping

    # audit up to 20 kept records from wave 1, pulled live from MongoDB
    python scripts/azure_review.py --wave 1 --limit 20

    # audit records from a local export instead (see scripts/export_wave.py)
    python scripts/azure_review.py --export exports/generation_log_wave01.jsonl --limit 20

    # save the full per-record verdicts, not just the summary
    python scripts/azure_review.py --wave 1 --limit 20 --out azure_review_wave01.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class ReviewerSettings:
    endpoint: str
    deployment: str


def get_reviewer_settings() -> ReviewerSettings:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    if not endpoint:
        sys.exit("AZURE_OPENAI_ENDPOINT not set. This script reuses the pipeline's own .env.")
    return ReviewerSettings(endpoint=endpoint.rstrip("/"), deployment=deployment)


def _build_client():
    """Built once per process and reused -- the token provider caches and
    refreshes the AAD token internally, so there's no need to recreate the
    client per call. Deliberately mirrors the exact client construction
    pattern requested: the base OpenAI SDK pointed at Azure's OpenAI-
    compatible v1 surface, authenticated with an AAD bearer token provider,
    rather than the azure-identity.aio + raw HTTP approach
    `cold_chain/clients.py` uses for the pipeline's own Chat Completions
    calls."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import OpenAI

    settings = get_reviewer_settings()
    token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
    client = OpenAI(base_url=f"{settings.endpoint}/openai/v1", api_key=token_provider)
    return client, settings.deployment


def _extract_text(response: Any) -> str:
    """The Responses API's convenience `output_text` field concatenates all
    text content; fall back to walking `response.output` defensively in
    case a given SDK version doesn't expose it."""
    text = getattr(response, "output_text", None)
    if text:
        return text
    try:
        for item in response.output:
            content = getattr(item, "content", None) or []
            for c in content:
                t = getattr(c, "text", None)
                if t:
                    return t
    except Exception:  # noqa: BLE001
        pass
    return str(response)


# --------------------------------------------------------------------------- #
# --ping: smallest possible connectivity check
# --------------------------------------------------------------------------- #

def _ping_sync() -> tuple[bool, str]:
    client, deployment = _build_client()
    response = client.responses.create(model=deployment, input="Reply with exactly the word: PONG")
    text = _extract_text(response)
    return "PONG" in text.upper(), text


async def ping() -> int:
    settings = get_reviewer_settings()
    print(f"Responses API: {settings.endpoint}/openai/v1  model={settings.deployment}")
    try:
        ok, text = await asyncio.to_thread(_ping_sync)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  {type(exc).__name__}: {exc}")
        return 1
    print(f"reply={text!r}")
    print("PASS  endpoint, credential, and deployment are reachable" if ok else "FAIL  unexpected reply")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# loading records to review (identical contract to the earlier k2_review.py)
# --------------------------------------------------------------------------- #

async def load_from_mongo(wave: int, limit: int) -> list[dict[str, Any]]:
    from cold_chain.config import get_settings
    from cold_chain.logbook import Logbook

    settings = get_settings()
    async with Logbook(settings, run_id="azure-review") as book:
        rows = await book.read_generation(wave)
    kept = [r for r in rows if r.get("outcome") == "kept"]
    return kept[:limit]


def load_from_export(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("outcome") in (None, "kept"):  # export --all keeps other outcomes too
                rows.append(row)
    return rows[:limit]


# --------------------------------------------------------------------------- #
# the actual review
# --------------------------------------------------------------------------- #

REVIEW_PROMPT = """You are an independent auditor reviewing output from a GCC cold-chain
data pipeline. Read the artifact and the pipeline's assigned disposition, then give your own
judgment -- do not simply defer to the pipeline's answer.

ARTIFACT (field report, telemetry dump, or transcript):
{artifact}

PIPELINE'S ASSIGNED DISPOSITION: {disposition}

Judge:
1. `your_disposition` -- what disposition would you assign, choosing only from:
   accept, hold_for_qa, reject, insufficient_data. Never propose expedite_sale --
   it is not a valid autonomous action regardless of what the artifact suggests.
2. `agrees` -- true if your_disposition matches the pipeline's, false otherwise.
3. `concerns` -- a list of any of: "label_leakage" (the text states a decision
   outright), "metadata_leakage" (the text exposes pipeline internals like a
   product_code field or a scenario name), "ungrounded" (the disposition doesn't
   follow from what's actually in the text), or "none".
4. `confidence` -- your confidence in your own judgment, 1 (low) to 5 (high).

Return only JSON: {{"your_disposition": "...", "agrees": true/false, "concerns": ["..."], "confidence": <1-5>}}
"""


def _review_one_sync(client: Any, deployment: str, row: dict[str, Any]) -> dict[str, Any]:
    artifact = row.get("rendered_text", "")[:3000]
    disposition = row.get("disposition", "unknown")
    prompt = REVIEW_PROMPT.format(artifact=artifact, disposition=disposition)
    raw = ""
    try:
        # No output token cap, by request -- omit max_output_tokens entirely.
        response = client.responses.create(model=deployment, input=prompt)
        raw = _extract_text(response)
        parsed = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception as exc:  # noqa: BLE001
        parsed = {"error": f"{type(exc).__name__}: {exc}", "raw": raw}
    return {
        "state_id": row.get("state_id"),
        "cell": row.get("cell"),
        "jurisdiction": row.get("jurisdiction"),
        "artifact_type": row.get("artifact_type"),
        "pipeline_disposition": disposition,
        "review": parsed,
    }


async def gather_reviews(rows: list[dict[str, Any]], concurrency: int = 4) -> list[dict[str, Any]]:
    """Runs the review over every row and returns the raw results list -- no
    printing, no exit code. Reused by generate_system_report.py. The
    blocking `openai` SDK call runs in a thread per item; concurrency is a
    thread-pool fan-out, not a network-level guarantee, so keep it modest."""
    client, deployment = _build_client()
    sem = asyncio.Semaphore(concurrency)
    results: list[dict[str, Any]] = []

    async def _one(row: dict[str, Any]) -> None:
        async with sem:
            results.append(await asyncio.to_thread(_review_one_sync, client, deployment, row))

    await asyncio.gather(*(_one(r) for r in rows))
    return results


def summarize_reviews(results: list[dict[str, Any]]) -> dict[str, Any]:
    agree = sum(1 for r in results if r["review"].get("agrees") is True)
    disagree = sum(1 for r in results if r["review"].get("agrees") is False)
    errored = sum(1 for r in results if "error" in r["review"])
    flagged = [r for r in results if "error" not in r["review"]
               and r["review"].get("concerns") not in ([], ["none"], None)]
    n = len(results) or 1
    return {
        "n": len(results), "agree": agree, "disagree": disagree, "errored": errored,
        "flagged": flagged, "agreement_rate": agree / n,
    }


async def run_review(rows: list[dict[str, Any]], out_path: Path | None) -> int:
    if not rows:
        print("No records to review (empty wave/export, or nothing outcome=='kept').")
        return 1

    settings = get_reviewer_settings()
    print(f"Reviewing {len(rows)} record(s) with {settings.deployment} via the Responses API "
          f"(no output token cap -- this may take a while)...\n")
    results = await gather_reviews(rows)
    summary = summarize_reviews(results)

    for r in results:
        rv = r["review"]
        if "error" in rv:
            print(f"[ERROR   ] {r['cell']:35} pipeline={r['pipeline_disposition']:16} {rv['error']}")
        else:
            tag = "AGREE" if rv.get("agrees") else "DISAGREE"
            print(f"[{tag:8}] {r['cell']:35} pipeline={r['pipeline_disposition']:16} "
                  f"reviewer={rv.get('your_disposition', '?'):16} concerns={rv.get('concerns', [])}")

    print(f"\n{summary['agree']}/{summary['n']} agree, {summary['disagree']}/{summary['n']} disagree, "
          f"{summary['errored']}/{summary['n']} errored, {len(summary['flagged'])}/{summary['n']} flagged a concern.")
    if summary["disagree"] or summary["flagged"]:
        print("\nDisagreements/flags are worth reading in full -- remember this reviewer is the same "
              "deployment as the pipeline itself (see this script's module docstring), so agreement "
              "here is weaker evidence than an independently-trained model agreeing would be.")

    if out_path:
        with out_path.open("w", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\nFull verdicts written to {out_path}")

    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ping", action="store_true", help="just confirm the endpoint/credential/deployment work")
    ap.add_argument("--wave", type=int, help="pull kept records for this wave live from MongoDB")
    ap.add_argument("--export", type=Path, help="pull records from a local export/*.jsonl file instead")
    ap.add_argument("--limit", type=int, default=20, help="max records to review")
    ap.add_argument("--out", type=Path, help="write full per-record verdicts to this jsonl path")
    args = ap.parse_args()

    if args.ping:
        return await ping()

    if not args.wave and not args.export:
        ap.error("pass --wave N (reads MongoDB) or --export path/to/file.jsonl, or --ping to just test the setup")

    rows = (
        load_from_export(args.export, args.limit)
        if args.export
        else await load_from_mongo(args.wave, args.limit)
    )
    return await run_review(rows, args.out)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
