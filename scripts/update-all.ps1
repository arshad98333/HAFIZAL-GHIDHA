# One command: pull latest from GitHub, install deps, sync -main folder, optional Azure deploy.
#
#   .\scripts\update-all.ps1
#   .\scripts\update-all.ps1 -Deploy          # also deploy UI+API to Azure (skip image rebuild)
#   .\scripts\update-all.ps1 -Branch main
#
# ASCII-only for Windows PowerShell 5.1.

param(
    [string]$Branch = "main",
    [string]$Source = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA",
    [string]$Dest = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main",
    [switch]$Deploy,
    [switch]$SkipSync,
    [switch]$SkipDeps,
    [switch]$SkipFrontendDeps
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command git)) {
    Write-Error 'git not found on PATH'
}

Write-Host "=== Step 1/4: Git pull origin/$Branch ==="
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }

$current = (git rev-parse --abbrev-ref HEAD).Trim()
if ($current -ne $Branch) {
    git checkout $Branch
    if ($LASTEXITCODE -ne 0) {
        git checkout -b $Branch "origin/$Branch"
        if ($LASTEXITCODE -ne 0) { throw "git checkout $Branch failed" }
    }
}

git pull origin $Branch
if ($LASTEXITCODE -ne 0) { throw 'git pull failed' }
Write-Host "At commit: $(git rev-parse --short HEAD)"

if (-not $SkipDeps) {
    Write-Host ""
    Write-Host "=== Step 2/4: Python dependencies ==="
    $py = Join-Path $Root "venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Write-Host "Creating venv..."
        python -m venv venv
        if ($LASTEXITCODE -ne 0) { throw 'python -m venv failed' }
    }
    & $py -m pip install -q -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
} else {
    Write-Host ""
    Write-Host "=== Step 2/4: Skipped Python deps (-SkipDeps) ==="
}

if (-not $SkipFrontendDeps) {
    Write-Host ""
    Write-Host "=== Step 3/4: Frontend dependencies ==="
    if (-not (Test-Command npm)) {
        Write-Error 'npm not found. Install Node.js 20+ from https://nodejs.org'
    }
    Push-Location (Join-Path $Root "frontend")
    npm ci 2>$null
    if ($LASTEXITCODE -ne 0) { npm install }
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    Pop-Location
} else {
    Write-Host ""
    Write-Host "=== Step 3/4: Skipped frontend deps (-SkipFrontendDeps) ==="
}

if (-not $SkipSync) {
    Write-Host ""
    Write-Host "=== Step 4/4: Sync to desktop -main folder ==="
    & (Join-Path $Root "scripts\sync-desktop-folder.ps1") -Source $Source -Dest $Dest -Branch $Branch -RobocopyOnly
    if ($LASTEXITCODE -ne 0) { throw 'sync-desktop-folder failed' }
} else {
    Write-Host ""
    Write-Host "=== Step 4/4: Skipped sync (-SkipSync) ==="
}

if ($Deploy) {
    Write-Host ""
    Write-Host "=== Bonus: Azure deploy (API already in ACR) ==="
    if (-not (Test-Command az)) {
        Write-Error 'az not found. Run: az login, then retry with -Deploy'
    }
    & (Join-Path $Root "scripts\deploy-azure-web.ps1") -SkipApiImage
    if ($LASTEXITCODE -ne 0) { throw 'deploy-azure-web failed' }
}

Write-Host ""
Write-Host "=== Update complete ==="
Write-Host "Git repo:  $Root ($Branch @ $(git rev-parse --short HEAD))"
if (-not $SkipSync) {
    Write-Host "Synced to: $Dest"
}
Write-Host ""
Write-Host "Run locally (two terminals):"
Write-Host "  .\scripts\api_server.ps1"
Write-Host "  .\scripts\ui.ps1"
if (-not $Deploy) {
    Write-Host ""
    Write-Host "Deploy to Azure:"
    Write-Host "  .\scripts\update-all.ps1 -Deploy"
}
