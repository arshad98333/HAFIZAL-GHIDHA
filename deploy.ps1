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
# PowerShell 7.3+ can treat a native command's stderr output (even git's
# routine progress text on a normal success, or its non-zero exit code) as
# a terminating error when combined with $ErrorActionPreference = "Stop".
# $PSNativeCommandUseErrorActionPreference is the documented switch for
# this, but it has proven unreliable across different PowerShell builds --
# so on top of setting it, every git call in this script goes through
# Invoke-Git below, which runs with $ErrorActionPreference forced to
# "Continue" for the duration of that one call. That makes this script's
# native-command handling correct regardless of PSNativeCommandUseErrorActionPreference's
# behavior on your specific PowerShell version. No effect on Windows
# PowerShell 5.1, where none of this exists.
$PSNativeCommandUseErrorActionPreference = $false
$Root = $PSScriptRoot
Set-Location $Root

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# Runs `git @GitArgs`, never lets a stderr line or non-zero exit code throw
# regardless of PowerShell version/preference quirks, and captures the real
# combined output in $script:LastGitOutput so callers can show it on
# failure instead of guessing blind. Returns the process exit code.
function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$GitArgs)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & git @GitArgs 2>&1
    $ErrorActionPreference = $prevEap
    $script:LastGitOutput = ($output | Out-String).Trim()
    return $LASTEXITCODE
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

    Invoke-Git @("fetch", "origin") | Out-Null

    $changes = git status --porcelain
    if ($changes) {
        Write-Host "Local changes found:"
        git status --short | ForEach-Object { Write-Host "  $_" }

        $exit = Invoke-Git @("add", "-A")
        if ($exit -ne 0) { Write-Error "git add failed:`n$script:LastGitOutput" }

        if (-not $Message) {
            $Message = "Update from local dev machine ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
        }
        $exit = Invoke-Git @("commit", "-m", $Message)
        if ($exit -ne 0) { Write-Error "git commit failed:`n$script:LastGitOutput" }
        Write-Host "Committed: $Message"
    } else {
        Write-Host "No local changes to commit."
    }

    # -u/--set-upstream is safe to pass every time: it's a no-op once the
    # branch already tracks origin/$branch, and it's what fixes the "main
    # has no upstream branch" error on a repo that was never pushed from
    # this machine before.
    $exit = Invoke-Git @("push", "-u", "origin", $branch)
    if ($exit -ne 0) {
        Write-Host "Push failed -- trying to sync with GitHub first:" -ForegroundColor Yellow
        Write-Host $script:LastGitOutput
        $exit = Invoke-Git @("merge", "--ff-only", "origin/$branch")
        if ($exit -ne 0) {
            Write-Error "GitHub has changes that don't fast-forward with your local history:`n$script:LastGitOutput`nResolve manually (git pull / git merge) and re-run .\deploy.ps1."
        }
        $exit = Invoke-Git @("push", "-u", "origin", $branch)
        if ($exit -ne 0) {
            Write-Error "git push failed even after syncing:`n$script:LastGitOutput"
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
