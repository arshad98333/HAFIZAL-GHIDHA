# Sync latest code into C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main
# Preserves .env and pipeline_logs.json in the destination.
#
# Usage:
#   .\scripts\sync-desktop-folder.ps1
#   .\scripts\sync-desktop-folder.ps1 -RobocopyOnly
#   .\scripts\sync-desktop-folder.ps1 -InstallDeps -Deploy

param(
    [string]$Source = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA",
    [string]$Dest = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main",
    [string]$Branch = "main",
    [switch]$RobocopyOnly,
    [switch]$InstallDeps,
    [switch]$Deploy
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) {
    Write-Host "Source repo not found: $Source"
    Write-Host "Cloning into source folder..."
    git clone -b $Branch https://github.com/arshad98333/HAFIZAL-GHIDHA.git $Source
}

if (-not $RobocopyOnly) {
    Remove-Item (Join-Path $Source ".git\HEAD.lock") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $Source ".git\index.lock") -Force -ErrorAction SilentlyContinue

    # Git writes informational messages to stderr; do not treat them as fatal errors.
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

        & git -C $Source reset --hard "origin/$Branch" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "git reset --hard origin/$Branch failed with exit code $LASTEXITCODE"
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

Write-Host "Syncing $Source -> $Dest"
robocopy $Source $Dest /E /XD .git .venv node_modules __pycache__ .pytest_cache .mypy_cache .ruff_cache /XF *.pyc /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
# Robocopy uses 0-7 for success (1 = files copied). Only 8+ is failure.
$robocopyExit = $LASTEXITCODE
if ($robocopyExit -ge 8) { throw "robocopy failed with exit $robocopyExit" }

if (Test-Path $envBackup) { Copy-Item $envBackup (Join-Path $Dest ".env") -Force }
if (Test-Path $logsBackup) { Copy-Item $logsBackup (Join-Path $Dest "pipeline_logs.json") -Force }

Write-Host ""
Write-Host "Done. Updated: $Dest"
if (-not $RobocopyOnly) {
    Write-Host "Branch: $Branch ($(git -C $Source rev-parse --short HEAD))"
}

$updateAll = Join-Path $Source "scripts\update-all.ps1"
if ($InstallDeps -or $Deploy) {
    if (-not (Test-Path $updateAll)) {
        Write-Host ""
        Write-Host "update-all.ps1 not found yet. Run:"
        Write-Host "  git -C $Source pull origin $Branch"
        Write-Host "  .\scripts\update-all.ps1 -Deploy"
    } else {
        Write-Host ""
        Write-Host "Running update-all.ps1 (deps + optional deploy)..."
        $uaArgs = @('-SkipSync')
        if ($Deploy) { $uaArgs += '-Deploy' }
        if (-not $InstallDeps -and -not $Deploy) { $uaArgs += '-SkipDeps'; $uaArgs += '-SkipFrontendDeps' }
        & $updateAll @uaArgs
        if ($LASTEXITCODE -ne 0) { throw 'update-all failed' }
    }
} else {
    Write-Host ""
    if (Test-Path $updateAll) {
        Write-Host "Next (one command for everything):"
        Write-Host "  .\scripts\update-all.ps1"
        Write-Host "  .\scripts\update-all.ps1 -Deploy"
    } else {
        Write-Host "Next (pull latest scripts first):"
        Write-Host "  git -C $Source pull origin $Branch"
        Write-Host "  .\scripts\update-all.ps1 -Deploy"
        Write-Host ""
        Write-Host "Or use sync which already fetched main:"
        Write-Host "  git -C $Source reset --hard origin/$Branch"
    }
    Write-Host ""
    Write-Host "Run API + UI (two terminals):"
    Write-Host "  cd $Dest"
    Write-Host "  .\scripts\api_server.ps1"
    Write-Host "  .\scripts\ui.ps1"
}

# Robocopy success codes (1-7) must not propagate to callers as failure.
exit 0
