# GCC Cold-Chain Compliance AI

[![License: MIT](https://img.shields.io/badge/license-MIT-3C3489)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-0C447C)](requirements.txt)
[![Docker](https://img.shields.io/badge/container-Dockerfile-085041)](Dockerfile)

Train an AI model to review GCC cold-chain field artifacts (temperature logs, chat messages, QC forms, voice notes) and emit a disposition: **accept**, **hold**, **reject**, or **insufficient data**. Every training label comes from a deterministic rules engine grounded in GCC food-safety law — no LLM ever produces a label.

Executive summary: [`One_Engine_Six_Jurisdictions.pdf`](One_Engine_Six_Jurisdictions.pdf)

---

## Quick start — one command

After setup (Steps 1–6 below), **everything** runs through a single entry point:

| Goal | Linux / macOS | Windows PowerShell |
|------|---------------|-------------------|
| **Re-score existing data** (you already generated wave 1) | `make run` | `.\scripts\run.ps1` |
| **First-time smoke test** (10 records) | `make run-smoke` | `.\scripts\run.ps1 -Profile smoke` |
| **Full wave** (~663 records, API calls) | `make run-wave` | `.\scripts\run.ps1 -Profile wave` |
| **CI-quality run** (tests + full wave) | `make run-full` | `.\scripts\run.ps1 -Profile full` |

Equivalent Python (all platforms):

```bash
python scripts/local_run.py run --wave 1 --profile rescore   # default — gate-a + export + kpi + preflight
python scripts/local_run.py run --wave 1 --profile smoke    # 10-record end-to-end test
python scripts/local_run.py run --wave 1 --profile wave     # full generation + evaluation
```

Every `run` appends a JSON log entry to **`pipeline_logs.json`** in the repo root.

---

## Step-by-step setup (first time only)

### Step 1 — Get the code

**Use Git** (required for updates). Do not use the GitHub ZIP download — it misses the latest branch.

```bash
git clone https://github.com/arshad98333/HAFIZAL-GHIDHA.git
cd HAFIZAL-GHIDHA
git checkout cursor/local-run-orchestrator-2905
```

Windows PowerShell:

```powershell
git clone https://github.com/arshad98333/HAFIZAL-GHIDHA.git
cd HAFIZAL-GHIDHA
git fetch origin cursor/local-run-orchestrator-2905
git checkout cursor/local-run-orchestrator-2905
```

### Step 2 — Python environment

| Tool | Version |
|------|---------|
| Python | **3.11 or 3.12** (3.14 may work but is not CI-tested) |
| Git | any recent |
| Azure CLI | `az login` before generate/gate-a |
| Make | optional on Linux/macOS |

```bash
python3 -m venv .venv
source .venv/bin/activate    # Linux/macOS
pip install -r requirements-dev.txt
```

Windows:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

### Step 3 — Offline tests (no credentials)

```bash
make test-fast
# 345+ tests, no network
```

### Step 4 — Configure `.env`

```bash
cp .env.example .env
```

| Variable | Required for |
|----------|--------------|
| `MONGODB_URI` | all stages except `health` |
| `AZURE_OPENAI_ENDPOINT` | plan, generate, gates |
| `FOUNDRY_PROJECT_ENDPOINT` | train |
| `FOUNDRY_COMPUTE_CLUSTER` | train |
| `FOUNDRY_BASE_MODEL` | train |
| `TRAINING_REGION` | train |

**MongoDB password:** URL-encode special characters (`@` → `%40`).

Never commit `.env`.

### Step 5 — MongoDB Atlas

1. Create a cluster at [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas).
2. Database user with `readWrite` on database `cold_chain` only.
3. Network Access: allow your IP.
4. Paste connection string into `MONGODB_URI`.

### Step 6 — Azure login

```bash
az login
```

Your identity needs `Cognitive Services OpenAI User` on the Azure OpenAI resource.

Verify:

```bash
python -m cold_chain.runner health   # config OK
python -m cold_chain.runner ready    # MongoDB OK
```

---

## Run profiles (what the single command does)

### `rescore` — re-evaluate existing data (default)

Use when you **already generated** wave 1 and want updated Gate A / KPI scores.

```
gate-a → export → kpi → preflight → pipeline_logs.json
```

```bash
make run                              # WAVE=1 PROFILE=rescore
python scripts/local_run.py run --wave 1 --profile rescore
```

Gate A exit code **2** means the gate halted — read the failure list. Your MongoDB data is unchanged.

### `smoke` — first-time 10-record test

```
tests → health → ready → plan → generate(10) → gate-a → export → audit → kpi → preflight → train dry-run → log
```

```bash
make run-smoke
python scripts/local_run.py run --wave 1 --profile smoke
```

Gate A often fails on 10 records by design (thresholds target full waves).

### `wave` — full corpus generation

```
health → ready → plan → generate(~663) → gate-a → export → audit → kpi → preflight → train dry-run → log
```

```bash
make run-wave
python scripts/local_run.py run --wave 1 --profile wave
```

Takes 30–90+ minutes depending on Azure rate limits.

### `full` — tests + full wave

Same as `wave` but runs `pytest` first.

```bash
make run-full
python scripts/local_run.py run --wave 1 --profile full
```

---

## After the run

| Artifact | Location |
|----------|----------|
| JSON run log | `pipeline_logs.json` |
| Exported corpus | `exports/generation_log_wave01.jsonl` |
| Guardrail audit | `CORPUS_GUARDRAIL_AUDIT_wave01.md` |
| KPI scorecard | printed in terminal (12 dimensions, target ≥ 7/10) |
| Gate A result | MongoDB `wave_artifacts.gate_a.json` |

Inspect:

```bash
python scripts/local_run.py audit --wave 1
make kpi WAVE=1
make preflight WAVE=1
```

When Gate A passes:

```bash
python -m cold_chain.runner train --wave 1              # submit SFT job
python -m cold_chain.runner train --wave 1 --dry-run    # validate only
python -m cold_chain.runner gate-b --wave 1             # needs student endpoint
```

---

## Manual step-by-step (fallback)

Print the command list:

```bash
python scripts/local_run.py steps --wave 1 --max-records 10
```

Run one stage:

```bash
python scripts/local_run.py step setup
python scripts/local_run.py step plan --wave 1
python scripts/local_run.py step generate --wave 1 --max-records 10
python scripts/local_run.py step gate-a --wave 1
python scripts/local_run.py step export --wave 1
```

Full operational guide: [`docs/LOCAL_RUNBOOK.md`](docs/LOCAL_RUNBOOK.md)

---

## Makefile reference

| Command | What it does |
|---------|--------------|
| **`make run`** | **Single command — rescore wave 1** |
| `make run-smoke` | 10-record smoke test |
| `make run-wave` | Full wave generation + evaluation |
| `make run-rescore` | Same as `make run` |
| `make run-full` | Tests + full wave |
| `make install` | Install dependencies |
| `make test-fast` | Offline unit tests |
| `make check` | Lint + typecheck + tests (CI) |
| `make kpi WAVE=1` | KPI scorecard only |
| `make preflight WAVE=1` | Training readiness only |

Override wave: `make run WAVE=2`

---

## Architecture

### Pipeline

```
plan → generate → gate-a → train → gate-b
```

![Pipeline stages](architecture_diagrams/pipeline_stages.svg)

### Package layers

| Layer | Path | Role |
|-------|------|------|
| cli | `cold_chain/cli/runner.py` | Stage entry points |
| domain | `cold_chain/domain/` | Rules, gates, curriculum (no I/O) |
| adapters | `cold_chain/adapters/` | MongoDB, Azure, training |
| observability | `cold_chain/observability/` | Structured JSON logs |

Full detail: [`docs/architecture.md`](docs/architecture.md)

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `local_run.py` not found | Wrong branch — `git checkout cursor/local-run-orchestrator-2905` |
| `fatal: not a git repository` | You used a ZIP download — clone with Git instead |
| `git fetch` / `HEAD.lock` errors | `Remove-Item .git\HEAD.lock -Force` then retry checkout |
| MongoDB auth / DNS | URL-encode password; check Atlas IP allowlist |
| Gate A exit 2 on smoke | Expected — use `--profile wave` for real thresholds |
| `near_duplicate_rate` high (~40%) | Regenerate on this branch: `make run-wave` after `reset_pipeline_state.py --yes` |
| `train` blocked | Gate A must pass first |
| `gate-b` blocked | Set `STUDENT_INFERENCE_ENDPOINT` or use `--results <path>` |
| Python 3.14 issues | Use Python 3.11 or 3.12 |

---

## Safeguards

- Labels from `rules_engine.py` only — never from an LLM.
- Golden-set database has no grant to the pipeline MongoDB user.
- Every kept record carries a provenance envelope.
- Gate A or Gate B failure halts the pipeline (exit code 2).

## License

MIT — see [`LICENSE`](LICENSE).
