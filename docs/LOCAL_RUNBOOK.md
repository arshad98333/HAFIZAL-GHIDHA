# Local Runbook

One-page guide for running the cold-chain pipeline on a developer machine (Windows or Linux).

## Prerequisites

- Python 3.11 or 3.12
- `az login` (Azure OpenAI + optional Foundry)
- MongoDB Atlas URI in `.env` (password URL-encoded: `@` → `%40`)
- Copy `.env.example` → `.env` and fill required vars

## One-command flows

```bash
# Setup + smoke (10 records)
make local-setup
make smoke-run WAVE=1 MAX=10

# Full wave (~663 records)
make wave-run WAVE=1

# KPI scorecard (target: all 12 >= 7/10)
make kpi WAVE=1
```

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python scripts/local_run.py all --wave 1 --max-records 10
python scripts/local_run.py kpi --wave 1
```

## Step-by-step

```bash
python scripts/local_run.py steps --wave 1
```

| Step | Command |
|------|---------|
| Health | `python -m cold_chain.runner health` |
| Ready | `python -m cold_chain.runner ready` |
| Plan | `python -m cold_chain.runner plan --wave 1` |
| Generate | `python -m cold_chain.runner generate --wave 1` |
| Gate A | `python -m cold_chain.runner gate-a --wave 1` |
| Export | `python scripts/export_wave.py --wave 1` |
| Preflight | `python -m cold_chain.runner preflight --wave 1` |
| Train (dry-run) | `python -m cold_chain.runner train --wave 1 --dry-run` |
| Gate B | `python -m cold_chain.runner gate-b --wave 1` |
| KPI | `python scripts/local_run.py kpi --wave 1` |

## Expected exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Config / connectivity error |
| 2 | Gate halted or KPI below 7/10 target |

Gate A exit 2 on a **smoke run** (10–100 records) is normal — metrics need a full wave.

## After a full wave generate

Re-run Gate A on existing data (no regenerate needed):

```bash
python scripts/local_run.py rescore --wave 1
```

This runs gate-a, export, kpi, and preflight, and appends a JSON entry to `pipeline_logs.json` in the repo root.

```bash
python -m cold_chain.runner gate-a --wave 1
python scripts/local_run.py audit --wave 1
python scripts/local_run.py kpi --wave 1
```

## Training readiness

```bash
python -m cold_chain.runner preflight --wave 1
python -m cold_chain.runner train --wave 1 --dry-run
python -m training.sft --wave 1 --base-model $FOUNDRY_BASE_MODEL --dry-run
```

Training submit requires Gate A pass + export on disk + Foundry config.

## Gate B paths

1. **Auto (default):** set `STUDENT_INFERENCE_ENDPOINT` + `STUDENT_INFERENCE_KEY`, then `gate-b --wave 1`
2. **Human sealed eval:** `gate-b --wave 1 --results path/to/results.json`

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `python3` not found (Windows) | Use `python` |
| `source` not found (PowerShell) | `.\venv\Scripts\Activate.ps1` |
| MongoDB DNS error | Check hostname in `MONGODB_URI` |
| Auth failed `@` in password | URL-encode special chars |
| `near_duplicate_rate: not measured` | Re-run gate-a on latest code (embedding batching fixed) |
| `cell_fill_deviation` high on smoke | Expected; run full wave |
| Train blocked | Gate A must pass first |
| Gate B blocked | Deploy student endpoint or use `--results` |

## KPI dimensions (12)

1. schema_validity  
2. round_trip_recovery  
3. screener_calibration  
4. corpus_uniqueness  
5. cell_balance  
6. class_balance  
7. leakage_resistance  
8. qualitative_review  
9. guardrail_integrity  
10. training_readiness  
11. inference_gate_b_readiness  
12. operational_maturity  
