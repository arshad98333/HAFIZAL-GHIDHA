# Re-score wave 1 and append to pipeline_logs.json
# Usage (after git pull):
#   .\venv\Scripts\Activate.ps1
#   .\scripts\rescore.ps1

param(
    [int]$Wave = 1
)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot\..

if (Test-Path ".\venv\Scripts\Activate.ps1") {
    .\venv\Scripts\Activate.ps1
}

python scripts/local_run.py rescore --wave $Wave
exit $LASTEXITCODE
