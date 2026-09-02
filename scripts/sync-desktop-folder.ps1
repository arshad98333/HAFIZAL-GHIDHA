# Optional mirror: copy this git repo to a second folder (no git history).
# Preserves .env and pipeline_logs.json in the destination.
#
# Most developers work only in the git clone. Use -MirrorDesktop on update-all instead.
#
#   .\scripts\sync-desktop-folder.ps1 -RobocopyOnly
#   .\scripts\update-all.ps1 -MirrorDesktop

param(
    [string]$Source = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA",
    [string]$Dest = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main",
    [string]$Branch = "main",
    [switch]$RobocopyOnly,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) {
    Write-Host "Source repo not found: $Source"
    Write-Host "Clone first:"
    Write-Host "  git clone https://github.com/arshad98333/HAFIZAL-GHIDHA.git $Source"
    exit 1
}

if (-not $RobocopyOnly) {
    Remove-Item (Join-Path $Source ".git\HEAD.lock") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $Source ".git\index.lock") -Force -ErrorAction SilentlyContinue

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & git -C $Source fetch origin 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "git fetch failed with exit code $LASTEXITCODE"
        }

        $currentBranch = (& git -C $Source rev-parse --abbrev-ref HEAD 2>&1 | Out-String).Trim()
        if ($currentBranch -ne $Branch) {
            & git -C $Source checkout $Branch 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                & git -C $Source checkout -b $Branch "origin/$Branch" 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "git checkout $Branch failed with exit code $LASTEXITCODE"
                }
            }
        }

        & git -C $Source pull --ff-only origin $Branch 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "git pull failed with exit code $LASTEXITCODE"
        }
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

if (-not (Test-Path $Dest)) {
    New-Item -ItemType Directory -Path $Dest | Out-Null
}

$envBackup = Join-Path $env:TEMP "hafizal-env.bak"
$logsBackup = Join-Path $env:TEMP "hafizal-logs.bak"
if (Test-Path (Join-Path $Dest ".env")) { Copy-Item (Join-Path $Dest ".env") $envBackup -Force }
if (Test-Path (Join-Path $Dest "pipeline_logs.json")) { Copy-Item (Join-Path $Dest "pipeline_logs.json") $logsBackup -Force }

if (-not $Quiet) {
    Write-Host "Mirroring $Source -> $Dest"
}
robocopy $Source $Dest /E /XD .git .venv venv node_modules __pycache__ .pytest_cache .mypy_cache .ruff_cache /XF *.pyc /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
$robocopyExit = $LASTEXITCODE
if ($robocopyExit -ge 8) { throw "robocopy failed with exit $robocopyExit" }

if (Test-Path $envBackup) { Copy-Item $envBackup (Join-Path $Dest ".env") -Force }
if (Test-Path $logsBackup) { Copy-Item $logsBackup (Join-Path $Dest "pipeline_logs.json") -Force }

if (-not $Quiet) {
    Write-Host ""
    Write-Host "Done. Mirrored: $Dest"
    if (-not $RobocopyOnly) {
        Write-Host "Branch: $Branch ($(git -C $Source rev-parse --short HEAD))"
    }
}

exit 0
