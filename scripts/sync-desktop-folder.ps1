# Sync latest code into C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main
# Preserves .env and pipeline_logs.json in the destination.
#
# Usage:
#   .\scripts\sync-desktop-folder.ps1
#   .\scripts\sync-desktop-folder.ps1 -RobocopyOnly   # copy files only, no git

param(
    [string]$Source = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA",
    [string]$Dest = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main",
    [string]$Branch = "main",
    [switch]$RobocopyOnly
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) {
    Write-Host "Source repo not found: $Source"
    Write-Host "Cloning into source folder..."
    git clone -b $Branch https://github.com/arshad98333/HAFIZAL-GHIDHA.git $Source
}

if (-not $RobocopyOnly) {
    Set-Location $Source
    Remove-Item .git\HEAD.lock -Force -ErrorAction SilentlyContinue
    Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue
    git fetch origin
    git checkout $Branch 2>$null
    if ($LASTEXITCODE -ne 0) {
        git checkout -b $Branch "origin/$Branch"
    }
    git reset --hard "origin/$Branch"
}

if (-not (Test-Path $Dest)) {
    New-Item -ItemType Directory -Path $Dest | Out-Null
}

$envBackup = Join-Path $env:TEMP "hafizal-env.bak"
$logsBackup = Join-Path $env:TEMP "hafizal-logs.bak"
if (Test-Path (Join-Path $Dest ".env")) { Copy-Item (Join-Path $Dest ".env") $envBackup -Force }
if (Test-Path (Join-Path $Dest "pipeline_logs.json")) { Copy-Item (Join-Path $Dest "pipeline_logs.json") $logsBackup -Force }

Write-Host "Syncing $Source -> $Dest"
robocopy $Source $Dest /E /XD .git .venv __pycache__ .pytest_cache .mypy_cache .ruff_cache /XF *.pyc /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit $LASTEXITCODE" }

if (Test-Path $envBackup) { Copy-Item $envBackup (Join-Path $Dest ".env") -Force }
if (Test-Path $logsBackup) { Copy-Item $logsBackup (Join-Path $Dest "pipeline_logs.json") -Force }

Write-Host ""
Write-Host "Done. Updated: $Dest"
if (-not $RobocopyOnly) {
    Write-Host "Branch: $Branch ($(git -C $Source rev-parse --short HEAD))"
}
Write-Host ""
Write-Host "Next:"
Write-Host "  cd $Dest"
Write-Host "  .\venv\Scripts\Activate.ps1"
Write-Host "  python scripts/local_run.py run --wave 1 --profile rescore"
