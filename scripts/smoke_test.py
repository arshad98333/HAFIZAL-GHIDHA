"""One-shot connectivity check for every external dependency in .env, plus a
structural check of the bundled knowledge base and guardrail pack.
Does not generate data, does not spend GPU money, does not touch managed
training. Safe to run as often as you like.

    python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from cold_chain.config import get_settings  # noqa: E402


async def check_mongo(settings) -> tuple[bool, str]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
    try:
        info = await client.admin.command("ping")
        db = client[settings.mongodb_db_name]
        await db.wave_artifacts.insert_one({"_smoke_test": True})
        await db.wave_artifacts.delete_many({"_smoke_test": True})
        return True, f"ping={info} db={settings.mongodb_db_name} write/delete round-trip ok"
    finally:
        client.close()


async def check_azure_chat(settings) -> tuple[bool, str]:
    from cold_chain.clients import AzureClient

    async with AzureClient(settings) as azure:
        out = await azure.complete("Reply with exactly the word: PONG", max_tokens=10)
        return "PONG" in out.upper(), f"reply={out!r}"


async def check_azure_embed(settings) -> tuple[bool, str]:
    from cold_chain.clients import AzureClient

    async with AzureClient(settings) as azure:
        vecs = await azure.embed(["reefer temperature log"])
        return len(vecs) == 1 and len(vecs[0]) > 0, f"dims={len(vecs[0])}"


async def check_content_safety(settings) -> tuple[bool, str]:
    if not (settings.content_safety_endpoint and settings.content_safety_key):
        return True, "not configured (optional) -- skipped"
    from cold_chain.clients import ContentSafetyClient

    async with ContentSafetyClient(settings) as cs:
        ok = await cs.is_safe("The reefer held 3.2C for the full transit.")
        return ok, f"is_safe={ok}"


async def check_foundry(settings) -> tuple[bool, str]:
    if not settings.foundry_compute_cluster or settings.foundry_compute_cluster == "<gpu-cluster-name>":
        return False, "FOUNDRY_COMPUTE_CLUSTER not filled in -- not tested (submitting a real " \
                      "training job is a separate, explicit action, not part of this smoke test)"
    return False, "connectivity check not implemented -- MLClient.from_config() needs a " \
                  "config.json (subscription/resource group/workspace) that isn't part of .env; " \
                  "verify manually with `az ml workspace show` or MLClient before running `train`"


async def check_student(settings) -> tuple[bool, str]:
    if not (settings.student_inference_endpoint and settings.student_inference_key):
        return True, "not configured (optional -- no fine-tuned checkpoint deployed yet) -- skipped"
    from cold_chain.clients import StudentClient

    async with StudentClient(settings) as student:
        parsed, raw = await student.predict("Reefer held 2.1C, no excursions, 24h log.")
        return parsed is not None, f"raw={raw[:200]!r}"


async def check_knowledge_base(settings) -> tuple[bool, str]:
    from cold_chain import knowledge_base as kb

    problems = kb.validate_loaded(settings.knowledge_base_dir)
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(kb.JURISDICTIONS)} country profiles loaded from {settings.knowledge_base_dir}"


async def check_guardrails(settings) -> tuple[bool, str]:
    from cold_chain import guardrails as gr

    problems = gr.validate_loaded(settings.guardrails_dir)
    if problems:
        return False, "; ".join(problems)
    n_rules = len(gr.base_pack(settings.guardrails_dir)["rules"]) + sum(
        len(gr.country_pack(c, settings.guardrails_dir)["rules"]) for c in gr.COUNTRY_FILES
    )
    return True, f"{n_rules} rules loaded from {settings.guardrails_dir}"


CHECKS = [
    ("MongoDB Atlas", check_mongo),
    ("Azure OpenAI chat (gpt-5.4-mini)", check_azure_chat),
    ("Azure OpenAI embeddings", check_azure_embed),
    ("Azure AI Content Safety", check_content_safety),
    ("Managed training compute", check_foundry),
    ("Student inference endpoint", check_student),
    ("Knowledge base (gcc_food_law_json)", check_knowledge_base),
    ("Guardrail pack (guardrails/)", check_guardrails),
]


async def main() -> int:
    settings = get_settings()
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = await fn(settings)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
            if "--verbose" in sys.argv:
                traceback.print_exc()
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL':4}  {name:35}  {detail}")

    n_fail = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - n_fail}/{len(results)} checks passed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
