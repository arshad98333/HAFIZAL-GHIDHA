# One-time: point this folder at GitHub and track origin/main.
# ASCII-only for Windows PowerShell 5.1.
#
#   .\scripts\connect-github.ps1
#
# Then leave auto-update running in another terminal:
#   .\scripts\watch-github.ps1

param(
    [string]$RemoteUrl = "https://github.com/arshad98333/HAFIZAL-GHIDHA.git",
    [string]$Branch = "main"
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

if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Error "Not a git repository: $Root"
}

Write-Host "=== Connect local repo to GitHub ==="
Write-Host "Folder: $Root"
Write-Host "Remote: $RemoteUrl"
Write-Host "Branch: $Branch"
Write-Host ""

$hasOrigin = $false
try {
    $null = git remote get-url origin 2>$null
    if ($LASTEXITCODE -eq 0) { $hasOrigin = $true }
} catch {
    $hasOrigin = $false
}

if ($hasOrigin) {
    git remote set-url origin $RemoteUrl
    if ($LASTEXITCODE -ne 0) { throw 'git remote set-url failed' }
} else {
    git remote add origin $RemoteUrl
    if ($LASTEXITCODE -ne 0) { throw 'git remote add failed' }
}

Write-Host "Fetching origin..."
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }

$current = (git rev-parse --abbrev-ref HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or $current -ne $Branch) {
    git checkout $Branch 2>$null
    if ($LASTEXITCODE -ne 0) {
        git checkout -b $Branch "origin/$Branch"
        if ($LASTEXITCODE -ne 0) { throw "git checkout $Branch failed" }
    }
}

git branch --set-upstream-to="origin/$Branch" $Branch 2>$null
git pull --ff-only origin $Branch
if ($LASTEXITCODE -ne 0) { throw 'git pull failed' }

Write-Host ""
Write-Host "Connected. At commit: $(git rev-parse --short HEAD)"
Write-Host ""
Write-Host "Next (one time):"
Write-Host "  python -m venv venv"
Write-Host "  .\venv\Scripts\Activate.ps1"
Write-Host "  pip install -r requirements-dev.txt"
Write-Host "  copy .env.example .env"
Write-Host ""
Write-Host "Auto-update from GitHub (leave terminal open):"
Write-Host "  .\scripts\watch-github.ps1"
Write-Host ""
Write-Host "Manual update + optional Azure deploy:"
Write-Host "  .\scripts\update-all.ps1"
Write-Host "  .\scripts\update-all.ps1 -Deploy"
