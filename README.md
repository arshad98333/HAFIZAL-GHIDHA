# GCC cold-chain fine-tuning pipeline

[![CI](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml)
[![CD - Azure Container Apps](https://github.com/<OWNER>/<REPO>/actions/workflows/cd.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/cd.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-3C3489)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-0C447C)](requirements.txt)
[![Docker](https://img.shields.io/badge/container-Dockerfile-085041)](Dockerfile)
[![Deploy to Azure](https://img.shields.io/badge/Azure-Container%20Apps-0C447C)](https://portal.azure.com/#create/Microsoft.Template/uri=https%3A%2F%2Fraw.githubusercontent.com%2F<OWNER>%2F<REPO>%2Fmain%2Finfra%2Fmain.json)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-712B13)](CONTRIBUTING.md)

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri=https%3A%2F%2Fraw.githubusercontent.com%2F<OWNER>%2F<REPO>%2Fmain%2Finfra%2Fmain.json)

> Replace `<OWNER>/<REPO>` above with this repo's actual GitHub path once
> pushed — GitHub badges and the Deploy-to-Azure button both need a real,
> public URL to resolve. See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full
> Azure Container Apps CI/CD setup (OIDC login, required GitHub secrets,
> one-time role assignments), [`ROADMAP.md`](ROADMAP.md) for what's planned
> next, and [`CONTRIBUTING.md`](CONTRIBUTING.md) to open a PR.

An agentic data-generation and evaluation pipeline that builds a 5,304-record,
English-language training corpus (8 waves of 663) for a student model that
triages messy GCC cold-chain field artifacts — logger CSV dumps, chat
messages, OCR'd QC forms, voice-note transcripts — into a strict-JSON
disposition (`accept` / `hold_for_qa` / `reject` / `insufficient_data`).

Every ground-truth label comes from a pure Python rule engine, never a
language model. Every threshold that rule engine applies, and every guardrail
a downstream reasoning agent is held to, traces to a cited source: the
bundled `gcc_food_law_json/` knowledge base (six GCC country food-law
profiles) and the `guardrails/` pack derived from it. Fully asynchronous; the
logbook of record is MongoDB Atlas, not local JSONL.

```
CURRICULUM.md ─┐
Mongo: ledger, coverage_state ├─→ cold_chain/curriculum.py ─→ plan.json (wave_artifacts)
                                          │
                                          ▼
     synthetic-physics-v1 ──→ world states ──→ rules_engine.py (+ guardrails.py) ──→ LABEL
                                          │
              gpt-5.4-mini ──→ render (label masked) ──→ screen ──→ round-trip extract
                                          │
                            guardrails.check_artifact_text ──→ defense-in-depth net
                                          │
                                      GATE A ──── fail ──→ HALT
                                          │
                        Managed training compute SFT (submitted, not run in-process)
                                          │
                                      GATE B ──── human-supplied results file, or the
                                          │        Azure judge model as gatekeeper ──→ HALT on fail
                                          │
                              Mongo: ledger ──→ next wave
```

## What's in this repo

| Path | Role |
|---|---|
| `cold_chain/` | The pipeline package (see below) |
| `gcc_food_law_json/` | Knowledge base: six GCC country food-law profiles + schema |
| `guardrails/` | 85-rule guardrail pack for a downstream reasoning agent, derived from the knowledge base and a real failure sample |
| `CURRICULUM.md`, `AUTORESEARCH.md` | The two files a human edits between waves |
| `MANUAL_TESTING_GUIDE.md` | Ordered, copy-pasteable commands from first setup through a full-corpus audit |
| `scripts/` | Connectivity smoke test, Mongo export, corpus guardrail audit, real-time stream demo, second-pass review, system report |
| `Dockerfile`, `.dockerignore` | Container image for any stage (`docker run --env-file .env <image> generate --wave 1`) |
| `infra/main.json` | ARM template provisioning an Azure Container Apps Job to run pipeline stages unattended — see [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| `.github/workflows/ci.yml` | pytest across Python 3.11/3.12 + a Docker build check on every push/PR |
| `.github/workflows/cd.yml` | Builds and pushes the image to GHCR, then updates the Azure Container Apps Job on push to `main` |
| [`ROADMAP.md`](ROADMAP.md) | What's shipped, what's planned next, and what's explicitly out of scope |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev setup, coding standards, and the review process for changes to `rules_engine.py` / `guardrails/` |
| [`LICENSE`](LICENSE) | MIT |

### `cold_chain/`

```
config.py         pydantic-settings; fails fast on a missing/misconfigured var
telemetry.py       structured JSON logging, correlation id per run
clients.py          async Azure OpenAI + Content Safety + student-endpoint clients
knowledge_base.py    loader for gcc_food_law_json/ -- citations, competent authorities
guardrails.py         loader + deterministic checks for guardrails/ -- temperature
                       bands, sentinel-value handling, text-pattern violation checks
logbook.py          async MongoDB Atlas-backed logbook (ledger, coverage, provenance)
rules_engine.py     deterministic disposition labeller -- the only source of truth
simulate.py          world-state synthesis + prompt construction (label-blind renderer)
curriculum.py       deterministic wave allocation + Azure-judge-authored rationale
gates.py            Gate A / Gate B evaluation, ratchet rule
agentic_eval.py     self-consistency-voted agentic review board + automated Gate B
runner.py           async CLI orchestrating one stage of one wave at a time
```

## The knowledge base and guardrail pack

`gcc_food_law_json/` holds one JSON profile per GCC state (UAE, Saudi Arabia,
Qatar, Kuwait, Oman, Bahrain) — competent authorities, primary statute,
standards framework, labelling, import clearance, and enforcement, compiled
from official sources and schema-validated (`00_schema.json`). See
`CHANGELOG_AND_VERIFICATION.md` in that directory for what was verified, what
was corrected, and what remains an open gap. This is reference data with a
`data_current_as_of` date, not a live regulatory feed, and it is not legal
advice — every citation names the instrument so it can be verified at source.

`guardrails/` is an 85-rule pack (25 base + 10 per country × 6 countries)
written for an *agent's* disposition reasoning, mined from the knowledge base
and a real failure sample (`wave_9001.jsonl` — see `guardrails/README.md`,
"What wave_9001 actually taught the pack"). Most rules are behavioural
constraints for a downstream reasoning agent's system prompt / eval rubric.
The subset that is mechanically checkable is wired directly into this
pipeline:

- **`rules_engine.py`** pulls its temperature bands, the sentinel-value set,
  and the frozen-regime refreeze threshold from `guardrails.py`, so the
  deterministic labeller and the guardrail pack can never silently disagree
  about what counts as an excursion (GCC-EDGE-001, GCC-EDGE-013).
- **`expedite_sale` is never emitted as a label.** It stays in the
  disposition vocabulary (a downstream agent must be able to recognise and
  refuse it) but the rule engine — the only source of ground truth — always
  routes what would have been an `expedite_sale` case to `hold_for_qa`
  instead (GCC-EDGE-015: "commercial pressure never converts an excursion
  into a release").
- **`guardrails.check_artifact_text`** runs as a second, independent net on
  every rendered artifact in `runner._generate_one`, in addition to (not
  instead of) the LLM screener — catching metadata leakage, expedite-sale
  wording, or a truncated `logger_csv` tail (`gates.GATE_A
  ["guardrail_violation_rate"]`).
- **`jurisdiction`** is a new balanced covariate (one of the six GCC states
  per record, see CURRICULUM.md section 2) that ties every kept record to a
  legal citation (`knowledge_base.citation`) and a country guardrail overlay,
  without ever influencing the label itself.

## The two instruction files

`CURRICULUM.md` and `AUTORESEARCH.md` are the only files a human edits between
waves. They are plain English. Editing them changes agent behaviour without
touching code.

## Step-by-step: getting a wave to run

### 1. Python environment

```bash
cd files
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt        # add -r requirements-dev.txt for pytest
```

### 2. MongoDB Atlas

1. Create (or reuse) an Atlas cluster in a region you're comfortable holding
   pipeline data in.
2. Create a **database user scoped to one database** (`cold_chain` by
   default): Atlas → Database Access → Add New Database User → custom role
   `readWrite` on `cold_chain` only. Do not reuse a user that also has access
   to a `golden` database — that separation is the actual enforcement of
   "the golden set is never mounted into an agent environment," not a config
   flag.
3. Network Access → allow your runner's IP (or `0.0.0.0/0` only for local
   throwaway testing, never for anything durable).
4. Copy the connection string. If you ever pasted a real password into a
   chat window, a doc, or a committed file, treat it as burned — rotate it in
   Atlas (Database Access → edit user → Edit Password) before using it here.
5. Collections and indexes are created automatically on first connect
   (`Logbook._ensure_indexes` in `cold_chain/logbook.py`) — nothing to
   provision by hand beyond the user and network rule above.

### 3. Fill in `.env`

```bash
cp .env.example .env
```

Edit `.env` (never commit this file) with:
- `MONGODB_URI` — the connection string from step 2, real password included
- `MONGODB_DB_NAME` — leave as `cold_chain` unless you have a reason not to
- `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_DEPLOYMENT` — your Foundry
  gpt-5.4-mini deployment (auth is AAD via `DefaultAzureCredential`, not an
  API key — run `az login`, or rely on managed identity in the job container).
  This one deployment renders, screens, extracts, and judges — there is a
  single external model provider in this pipeline.
- `FOUNDRY_PROJECT_ENDPOINT` / `FOUNDRY_COMPUTE_CLUSTER` — only needed once you
  reach the `train` stage
- `FOUNDRY_BASE_MODEL` — the student checkpoint this run fine-tunes. Not
  pinned to any particular size or family; pick what your training compute
  and downstream serving target actually is.
- `TRAINING_REGION` — whatever region this deployment's training compute
  runs in. Not pinned or validated by the pipeline; it is tagged onto the
  submitted job for tracking.
- `KNOWLEDGE_BASE_DIR` / `GUARDRAILS_DIR` — defaults resolve relative to the
  repo root; override only for a non-standard checkout layout.

### 4. Pre-wave-1 gates (do these before trusting any output)

1. Confirm every threshold in `cold_chain/rules_engine.py` / `guardrails/`
   against current GSO / SFDA / Dubai Municipality text beyond what
   `gcc_food_law_json/CHANGELOG_AND_VERIFICATION.md` already verified, and
   bump `RULES_VERSION` accordingly. **HITL 0, blocking.**
2. Hand-label 100–300 real seed artifacts and check the rule engine
   reproduces them. If it doesn't, no amount of generated data helps.
3. Confirm GPU quota is approved for the training compute cluster — this is
   procurement lead time, not engineering time.
4. Verify the current `azure-ai-ml` job submission surface before relying on
   `stage_train` in `cold_chain/runner.py` — that SDK moves; the docs are the
   authority, not this file.

### 5. Run a wave, one stage at a time

Each stage is a separate, resumable CLI invocation — a wave is not one long
process you hope doesn't crash at record 600.

```bash
python -m cold_chain.runner plan     --wave 1
python -m cold_chain.runner generate --wave 1
python -m cold_chain.runner gate-a   --wave 1
```

`gate-a` exits `2` and halts if data quality fails — read the failure list it
prints, fix the underlying issue (renderer prompt, screener threshold,
simulator physics, a `guardrails.check_artifact_text` hit), and re-run
`generate` before trying `gate-a` again.

```bash
python -m cold_chain.runner train    --wave 1
```

This submits the SFT job and returns immediately; it does not poll for
completion. The AutoResearch ratchet loop (`AUTORESEARCH.md`) runs inside
that job's container.

Gate B has two paths. Default is agentic — the Azure judge model scores the
student's holdout predictions with self-consistency voting
(`agentic_eval.AutoGateB`), no human file required:

```bash
python -m cold_chain.runner gate-b --wave 1
```

The original human-sealed-eval path still works for teams that want a
periodic human sign-off — a human runs the sealed golden-set evaluation by
hand, on a workstation with no agent credential, and writes the result to a
JSON file shaped like:

```json
{
  "metrics": {"malformed_json_rate": 0.002, "hallucinated_field_rate": 0.004, "...": "..."},
  "cell_f1": {"finfish_seafood|in_spec": 0.91, "...": "..."},
  "confusions": [[["hold_for_qa", "reject"], 6]]
}
```

```bash
python -m cold_chain.runner gate-b --wave 1 --results wave01_golden_eval.json
```

On pass, either path also appends the ledger row and closes the wave, so
wave 2's `plan` has something to read.

### 6. Repeat

Wave 2 onward is the same commands with `--wave 2`, etc., through wave 8.
`CURRICULUM.md` section 3 drives what each wave targets automatically via
`cold_chain/curriculum.py:WAVE_FOCUS`.

Exit code 2 from any command means a gate halted the wave. That is the system
working, not a bug to route around.

## Standing constraints

1. No label in this system is ever produced by a language model —
   `rules_engine.py` is a pure function called with the model output never in
   scope.
2. The golden set is never mounted into any agent's environment; Gate B's
   human path only ever consumes a human-produced results file (`--results`).
3. The renderer never sees the label field — `simulate.render_prompt` builds
   its input from `WorldState` fields only. `jurisdiction` only adds a
   scene-setting sentence; it is never extracted back out and never enters
   the label.
4. `expedite_sale` is never autonomously emitted by the rule engine
   (GCC-EDGE-015); it stays in the vocabulary only so a downstream agent can
   recognise and refuse it.
5. Wave 8 is rendered by a different model and never trained on
   (`curriculum.WAVE_FOCUS[8]["holdout"]`).
6. Every kept record carries a full provenance envelope: `rng_seed`,
   `rule_engine_sha`, `prompt_template_hash`, `generator_model`,
   `renderer_model`, `jurisdiction`, `parent_request_id` — see
   `cold_chain.logbook.Envelope`.
7. Gates A and B halt the process (exit code 2) rather than continue past a
   failed check.
8. Never put a live credential in `.env.example` or any committed file — only
   in your local `.env`. If one is ever exposed (chat, commit, screenshot),
   rotate it immediately; treat "was it seen by anyone" as "yes."

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers the deterministic core (`rules_engine`, `guardrails`,
`knowledge_base`, `curriculum` allocation math, `logbook` coverage
structures, `simulate` synthesis) without needing MongoDB or Azure
credentials — the async clients and Mongo-backed logbook are exercised via
the smoke test instead:

```bash
python scripts/smoke_test.py
```

## Manually running and evaluating a wave

For the full copy-pasteable, ordered walkthrough (setup through a full
~5,304-record corpus audit), see `MANUAL_TESTING_GUIDE.md`. Summary below.

### One command, the whole wave

`scripts/run_pipeline.py` runs plan, generate, Gate A, export, the guardrail
audit, and the tied-together system report in one invocation, printing each
stage's real output as it happens rather than hiding it. It calls the same
tested entry points below in sequence — it does not reimplement any of them —
and stops with a clear message at the first stage that actually fails. If
Gate A halts the wave (its normal, correct behavior when a check fails), this
still runs export and the audit so you can see why, and skips only the final
report.

```bash
python scripts/run_pipeline.py --wave 1 --max-records 10   # cheap smoke run
python scripts/run_pipeline.py --wave 1                    # full 663-record wave
```

### Or step by step

For a cheap end-to-end dry run, override the wave size and cap the record
count so you're not generating 663 records to check that things work:

```bash
# .env: set WAVE_SIZE=20 CELL_TARGET=5 for a small test wave, or just cap generate:
python -m cold_chain.runner plan     --wave 1
python -m cold_chain.runner generate --wave 1 --max-records 10
python -m cold_chain.runner gate-a   --wave 1
```

`gate-a` prints every metric against its bound and exits `2` on failure — the
failure list tells you exactly which check to look at. To eyeball the actual
records:

```bash
python scripts/export_wave.py --wave 1              # kept only -> exports/generation_log_wave01.jsonl
python scripts/export_wave.py --wave 1 --all         # include dropped records too, with the drop reason
```

### Second-pass review with Azure OpenAI's Responses API

`scripts/azure_review.py` is a standalone tool (not part of the pipeline or
its gates) that reviews a sample of kept records via the same Azure OpenAI
deployment the pipeline already uses (`AZURE_OPENAI_ENDPOINT` /
`AZURE_OPENAI_DEPLOYMENT` in `.env`), called through the newer Responses API
(`client.responses.create`) instead of Chat Completions. Read the module
docstring before trusting its output: because it's the same deployment the
pipeline itself renders, screens, extracts, and judges with, this is a
structurally separate second pass, not an independently-trained second
opinion — it will not catch a systematic blind spot in that deployment's own
judgment. No output token cap is applied. The `openai` package is a core
dependency (`requirements.txt`) since `cold_chain.clients.AzureClient` also
uses it now, not just this script.

```bash
# confirm the endpoint/credential/deployment work at all
python scripts/azure_review.py --ping

# review up to 20 kept records from wave 1, pulled live from MongoDB
python scripts/azure_review.py --wave 1 --limit 20

# or from a local export instead of hitting MongoDB
python scripts/azure_review.py --export exports/generation_log_wave01.jsonl --limit 20 --out azure_review_wave01.jsonl
```

For each record it asks the model to independently propose a disposition
and flag any concerns (label leakage, metadata leakage, an ungrounded
disposition), then prints an agree/disagree tally. Disagreements are worth
reading in full.

### Full system report

`scripts/generate_system_report.py` ties Gate A/B results, coverage, the
drop-reason breakdown, and the review above into one Markdown file:

```bash
python scripts/generate_system_report.py --wave 1 --review-limit 20
# writes SYSTEM_EVALUATION_REPORT_wave01.md
```

Pass `--review-limit 0` to skip that section and just get the Gate A/B +
coverage picture.

### If you're re-running a wave after upgrading the pipeline

`plan.json`, `coverage_state`, and `generation_log` are schema-coupled to
whatever version of `cold_chain` wrote them (cell targets, the
language/jurisdiction covariates, wave definitions). Re-running `plan` or
`generate` against a MongoDB database that already holds waves from an
older schema (a previous corpus size, the retired language axis, a
different disposition set) will not work cleanly — `build_plan` sees old
coverage as "already at target" and refuses to plan, or `generate` replays a
stale `plan.json` that references a covariate value (e.g. `code_switched`)
the current code no longer knows about. Mixing schema eras in one database
isn't safe to patch around:

```bash
python scripts/reset_pipeline_state.py --dry-run     # see what's there
python scripts/reset_pipeline_state.py --yes         # clear it (access_audit is kept)
python -m cold_chain.runner plan --wave 1            # start the wave sequence over
```
