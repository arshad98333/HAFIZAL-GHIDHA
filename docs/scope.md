# Scope

## 1. What problem does this solve, and for whom

This project trains an AI model to review cold-chain food shipment records (temperature logs, chat, QC forms, voice notes) and decide whether a shipment should be **accepted, held, rejected, or needs more data**. The decisions used for training come from a deterministic rules engine grounded in GCC food-safety law — not from LLM guesses.

**Audience:** ML engineers and compliance teams building or auditing a GCC cold-chain compliance fine-tuning pipeline.

## 2. Inputs and where they come from

| Input | Source |
|---|---|
| Synthetic shipment scenarios | `cold_chain/simulate.py` (seeded RNG) |
| Food-law knowledge base | `gcc_food_law_json/` (shipped with repo) |
| Guardrail packs | `guardrails/` (shipped with repo) |
| Azure OpenAI | Render, screen, extract, judge (AAD auth) |
| MongoDB Atlas | Logbook of record (ledger, coverage, generation log) |
| Foundry / Azure ML | Managed SFT job submission (`train` stage) |
| Student inference endpoint | Gate B auto-eval (optional) |

## 3. Outputs and who consumes them

| Output | Consumer |
|---|---|
| Labeled training records | SFT export (`scripts/export_wave.py`) |
| Gate A / Gate B reports | Pipeline operator (halt or proceed) |
| Wave artifacts (`plan.json`, gate JSON) | Next pipeline stage, audit |
| Structured logs | Log Analytics / operator debugging |

## 4. Explicitly out of scope for version one

- LLM-produced labels (rules engine only)
- Golden-set access from any agent environment (Atlas RBAC enforced)
- Public HTTP API or web dashboard
- Multi-provider judge models
- Non-GCC jurisdiction packs

## 5. What a correct result looks like

For a synthetic record: `rules_engine.label(world_state)` returns one of `accept`, `hold`, `reject`, `insufficient_data` consistent with GSO temperature bands and the cited instrument in `gcc_food_law_json/`. Every kept record carries a provenance envelope (wave, cell, rules version, model hashes). Gate A passes only when data-quality thresholds in `gates.py` are met. Gate B passes only when holdout F1 and guardrail violation rate meet configured floors.

## 6. What happens when things fail, and who needs to know

- **Gate halt:** Runner exits with code 2; a human-readable decision note is appended to MongoDB `decisions`. The operator reads the failed check list and fixes the root cause before resuming.
- **Config missing at startup:** Process exits immediately with a message naming every missing required environment variable.
- **Azure rate limits / transient errors:** Retried with backoff; sustained failure drops records and is logged with `run_id` correlation.
- **Training submit failure:** `train` stage logs and exits non-zero; operator checks Foundry job logs.
