# Local Runbook

> **Start here:** use the single command. See [README.md](../README.md) for full setup.

## The one command

| Platform | Command |
|----------|---------|
| **Windows** | `.\scripts\run.ps1` |
| **Linux/macOS** | `make run` |
| **Any** | `python scripts/local_run.py run --wave 1` |

All variants append to `pipeline_logs.json`.

## Profiles

| Profile | When to use |
|---------|-------------|
| `rescore` (default) | Data already in MongoDB — re-run gate-a, export, kpi, preflight |
| `smoke` | First time — 10 records, full validation chain |
| `wave` | Production — generate ~663 records + evaluate |
| `full` | CI-style — pytest + full wave |

```powershell
# Windows examples
.\scripts\run.ps1 -Wave 1                      # rescore
.\scripts\run.ps1 -Wave 1 -Profile smoke
.\scripts\run.ps1 -Wave 1 -Profile wave
```

```bash
# Linux/macOS examples
make run
make run-smoke
make run-wave
make run-full
```

## What each profile runs

**rescore:** gate-a → export → kpi → preflight → log

**smoke:** tests → health → ready → plan → generate(10) → gate-a → export → audit → kpi → preflight → train dry-run → log

**wave:** health → ready → plan → generate → gate-a → export → audit → kpi → preflight → train dry-run → log

## Prerequisites

1. Python 3.11 or 3.12 venv with `pip install -r requirements-dev.txt`
2. `.env` configured (copy from `.env.example`)
3. `az login` before any Azure API stage
4. Branch: `cursor/local-run-orchestrator-2905`

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Config / connectivity error |
| 2 | Gate halted or KPI below 7/10 (expected on smoke) |

## After rescore

```powershell
type pipeline_logs.json
python scripts/local_run.py audit --wave 1
```

## Regenerate for better diversity

If `near_duplicate_rate` is high, reset and regenerate:

```powershell
python scripts/reset_pipeline_state.py --dry-run
python scripts/reset_pipeline_state.py --yes
.\scripts\run.ps1 -Profile wave
```

## KPI dimensions (12)

schema_validity · round_trip_recovery · screener_calibration · corpus_uniqueness · cell_balance · class_balance · leakage_resistance · qualitative_review · guardrail_integrity · training_readiness · inference_gate_b_readiness · operational_maturity

Target: all ≥ 7/10
