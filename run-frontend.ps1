# ============================================================================
# run-frontend.ps1 -- Command file #2: run the web UI locally.
#
# Open this project in VS Code, open a terminal (Terminal > New Terminal),
# and run:
#
#     .\run-frontend.ps1
#
# Every run: pulls the latest code from GitHub first (so the project is
# always up to date when you launch it from VS Code), installs/updates
# frontend dependencies, then starts the Vite dev server.
#
# Start the backend in another terminal first: .\run-backend.ps1
#
# Options:
#     .\run-frontend.ps1 -Port 5174      # use a different port
#     .\run-frontend.ps1 -NoPull         # skip the git pull step
#     .\run-frontend.ps1 -NoInstall      # skip the npm install step
#
# ASCII-only for Windows PowerShell 5.1.
# ============================================================================

param(
    [int]$Port = 5173,
    [switch]$NoPull,
    [switch]$NoInstall
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

Write-Host "=== [1/3] Update project from GitHub ===" -ForegroundColor Cyan
if ($NoPull) {
    Write-Host "Skipped (-NoPull)."
} elseif (-not (Test-Command git)) {
    Write-Host "git not found on PATH -- skipping update. Install Git for Windows to enable auto-update." -ForegroundColor Yellow
} elseif (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Host "Not a git repository yet -- run .\deploy.ps1 once first, or clone the repo normally." -ForegroundColor Yellow
} else {
    git fetch origin 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Could not reach GitHub (offline?) -- continuing with the code you already have." -ForegroundColor Yellow
    } else {
        $before = (git rev-parse HEAD 2>$null)
        git merge --ff-only origin/main 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Could not fast-forward (you have local changes not on GitHub yet) -- continuing with your current code as-is." -ForegroundColor Yellow
            Write-Host "Run .\deploy.ps1 to push your local changes first, then re-run this." -ForegroundColor Yellow
        } else {
            $after = (git rev-parse HEAD 2>$null)
            if ($before -ne $after) {
                Write-Host "Updated to $(git rev-parse --short HEAD)."
            } else {
                Write-Host "Already up to date."
            }
        }
    }
}

$frontend = Join-Path $Root "frontend"
if (-not (Test-Path $frontend)) {
    Write-Error "frontend\ folder not found."
}

Write-Host ""
Write-Host "=== [2/3] Install/update frontend dependencies ===" -ForegroundColor Cyan
if (-not (Test-Command npm)) {
    Write-Error "npm not found on PATH. Install Node.js 20+ from https://nodejs.org, then re-run."
}
Push-Location $frontend
if ($NoInstall) {
    Write-Host "Skipped (-NoInstall)."
} elseif (-not (Test-Path "node_modules")) {
    Write-Host "Installing dependencies (first run, this can take a minute)..."
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
} else {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
}

Write-Host ""
Write-Host "=== [3/3] Start UI dev server ===" -ForegroundColor Cyan
Write-Host "UI:  http://127.0.0.1:$Port  (proxies /api -> backend on :8080)"
Write-Host "Make sure the backend is running in another terminal: .\run-backend.ps1"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

npm run dev -- --port $Port
$code = $LASTEXITCODE
Pop-Location
exit $code
