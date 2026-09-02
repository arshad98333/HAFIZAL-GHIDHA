# Pull latest main into this repo (bootstrap when update-all.ps1 is missing).
# ASCII-only for Windows PowerShell 5.1.
#
#   .\scripts\pull-main.ps1
#   .\scripts\pull-main.ps1 -Branch main

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

Write-Host "Updated to origin/$Branch @ $(git rev-parse --short HEAD)"
Write-Host ""
Write-Host "Next:"
Write-Host "  .\scripts\update-all.ps1"
Write-Host "  .\scripts\update-all.ps1 -Deploy"
