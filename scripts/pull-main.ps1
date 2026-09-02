# Emergency reset to match origin/main exactly (discards local commits).
# Prefer: git pull --ff-only origin main
#
#   .\scripts\pull-main.ps1

param(
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Fetching origin/$Branch..."
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

git reset --hard "origin/$Branch"
if ($LASTEXITCODE -ne 0) { throw 'git reset failed' }

Write-Host "Reset to origin/$Branch @ $(git rev-parse --short HEAD)"
Write-Host ""
Write-Host "Next:"
Write-Host "  .\scripts\update-all.ps1"
Write-Host "  .\scripts\watch-github.ps1"
