# ============================================================================
# run-backend.ps1 -- Command file #1: run the API server locally.
#
# Open this project in VS Code, open a terminal (Terminal > New Terminal),
# and run:
#
#     .\run-backend.ps1
#
# Every run: pulls the latest code from GitHub first (so the project is
# always up to date when you launch it from VS Code), installs/updates
# Python dependencies, then starts the FastAPI server with auto-reload.
#
# Options:
#     .\run-backend.ps1 -Port 9000       # use a different port
#     .\run-backend.ps1 -NoPull          # skip the git pull step
#     .\run-backend.ps1 -NoInstall       # skip the pip install step
#
# ASCII-only for Windows PowerShell 5.1.
# ============================================================================

param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8080,
    [switch]$NoPull,
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "=== [1/4] Update project from GitHub ===" -ForegroundColor Cyan
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

Write-Host ""
Write-Host "=== [2/4] Python environment ===" -ForegroundColor Cyan
$py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    if (-not (Test-Command python)) {
        Write-Error "Python not found on PATH, and no venv exists. Install Python 3.11+ from https://python.org, then re-run."
    }
    Write-Host "Creating virtual environment (venv\)..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
}
Write-Host "Using: $py"

Write-Host ""
Write-Host "=== [3/4] Install/update dependencies ===" -ForegroundColor Cyan
if ($NoInstall) {
    Write-Host "Skipped (-NoInstall)."
} else {
    & $py -m pip install -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt failed" }
    Write-Host "Dependencies up to date."
}

if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "WARNING: .env not found. Copy .env.example to .env and fill in MONGODB_URI, AZURE_OPENAI_ENDPOINT, K2_API_KEY etc. before the API will work fully." -ForegroundColor Yellow
}

function Test-PortInUse([string]$HostName, [int]$PortNum) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $PortNum, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(300) -and $client.Connected
        $client.Close()
        return $ok
    } catch { return $false }
}
if (Test-PortInUse -HostName $ListenHost -PortNum $Port) {
    Write-Error "Port $Port is already in use. Another API server may already be running. Use .\run-backend.ps1 -Port 9000 for a different port."
}

Write-Host ""
Write-Host "=== [4/4] Start API server ===" -ForegroundColor Cyan
Write-Host "API docs: http://${ListenHost}:${Port}/docs"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

& $py -m uvicorn cold_chain.api.app:create_app --factory --host $ListenHost --port $Port --reload
exit $LASTEXITCODE
