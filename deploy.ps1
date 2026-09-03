# ============================================================================
# deploy.ps1 -- Command file #3: push updates to GitHub and deploy to Azure.
#
# Open this project in VS Code, open a terminal (Terminal > New Terminal),
# and run:
#
#     .\deploy.ps1
#
# What it does, in order:
#   1. Commits any local changes and pushes them to GitHub (main branch).
#   2. Deploys the API to Azure Container Apps (image rebuilt in Azure
#      Container Registry -- no local Docker required) and the UI to
#      Azure Static Web Apps.
#
# Options:
#     .\deploy.ps1 -Message "Fix rate-limit banner"   # custom commit message
#     .\deploy.ps1 -SkipGitHub                        # Azure deploy only
#     .\deploy.ps1 -SkipAzure                          # GitHub push only
#     .\deploy.ps1 -SkipApiImage                       # Azure: reuse the last built image (faster, UI-only refresh)
#
# First-time setup this depends on:
#   - You can already "git push" to https://github.com/arshad98333/HAFIZAL-GHIDHA
#     from this machine (Git Credential Manager / SSH key already configured).
#   - You have run "az login" at least once (for the Azure deploy step).
#
# ASCII-only for Windows PowerShell 5.1.
# ============================================================================

param(
    [string]$Message = "",
    [switch]$SkipGitHub,
    [switch]$SkipAzure,
    [switch]$SkipApiImage
)

$ErrorActionPreference = "Stop"
# PowerShell 7.3+ treats ANY stderr line from a native command (even
# git's routine progress text, e.g. "From https://..." on fetch or
# "To https://..." on push) as a terminating error when combined with
# $ErrorActionPreference = "Stop". Disable that so only real failures
# (checked via $LASTEXITCODE below) stop the script. No effect on
# Windows PowerShell 5.1, where this feature does not exist.
$PSNativeCommandUseErrorActionPreference = $false
$Root = $PSScriptRoot
Set-Location $Root

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# --- Step 1: GitHub ---------------------------------------------------------

if ($SkipGitHub) {
    Write-Host "=== [1/2] GitHub: skipped (-SkipGitHub) ===" -ForegroundColor Cyan
} else {
    Write-Host "=== [1/2] Push updates to GitHub ===" -ForegroundColor Cyan

    if (-not (Test-Command git)) {
        Write-Error "git not found on PATH. Install Git for Windows: https://git-scm.com/download/win"
    }
    if (-not (Test-Path (Join-Path $Root ".git"))) {
        Write-Error "This folder is not a git repository. Re-run project setup, or clone https://github.com/arshad98333/HAFIZAL-GHIDHA.git fresh."
    }

    $branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
    if ($branch -ne "main") {
        Write-Host "Current branch is '$branch', not 'main'. Deploying from 'main' only -- switch first if this is unexpected." -ForegroundColor Yellow
    }

    git fetch origin 2>$null

    $changes = git status --porcelain
    if ($changes) {
        Write-Host "Local changes found:"
        git status --short | ForEach-Object { Write-Host "  $_" }

        git add -A
        if ($LASTEXITCODE -ne 0) { throw "git add failed" }

        if (-not $Message) {
            $Message = "Update from local dev machine ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
        }
        git commit -m $Message
        if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
        Write-Host "Committed: $Message"
    } else {
        Write-Host "No local changes to commit."
    }

    # Try a normal push first. If GitHub has commits we don't have locally,
    # fast-forward-merge them in and retry once -- never force-push.
    git push origin $branch 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Push rejected -- pulling latest from GitHub first..." -ForegroundColor Yellow
        git merge --ff-only "origin/$branch" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "GitHub has changes that don't fast-forward with your local history. Resolve manually (git pull / git merge) and re-run .\deploy.ps1."
        }
        git push origin $branch
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git push failed even after syncing. Check your GitHub credentials (git push manually to see the real error)."
        }
    }

    Write-Host "Pushed to https://github.com/arshad98333/HAFIZAL-GHIDHA (branch: $branch, commit: $(git rev-parse --short HEAD))"
}

# --- Step 2: Azure -----------------------------------------------------------

if ($SkipAzure) {
    Write-Host ""
    Write-Host "=== [2/2] Azure: skipped (-SkipAzure) ===" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "=== [2/2] Deploy to Azure ===" -ForegroundColor Cyan

    if (-not (Test-Command az)) {
        Write-Error "Azure CLI (az) not found. Install: https://learn.microsoft.com/cli/azure/install-azure-cli, then run 'az login' and re-run .\deploy.ps1."
    }
    $account = az account show --query id -o tsv 2>$null
    if (-not $account) {
        Write-Error "Not logged in to Azure. Run: az login"
    }

    $deployArgs = @()
    if ($SkipApiImage) { $deployArgs += "-SkipApiImage" }

    & (Join-Path $Root "scripts\deploy-azure-web.ps1") @deployArgs
    if ($LASTEXITCODE -ne 0) { throw "Azure deploy failed (see output above)" }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
if (-not $SkipGitHub) {
    Write-Host "GitHub: https://github.com/arshad98333/HAFIZAL-GHIDHA"
}
if (-not $SkipAzure) {
    Write-Host "Azure:  see API/UI URLs printed above."
}
