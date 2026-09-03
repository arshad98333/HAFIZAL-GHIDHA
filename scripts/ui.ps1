# Start the React web UI (Windows).
#   .\scripts\ui.ps1

param(
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
# PowerShell 7.3+ can treat ANY stderr line from a native command (git,
# npm, az, docker -- even routine progress/warning text on success) as a
# terminating error when combined with $ErrorActionPreference = "Stop".
# Disable that so only real failures (checked via $LASTEXITCODE) stop
# this script. No effect on Windows PowerShell 5.1.
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Join-Path $Root "venv\Scripts\python.exe"
$frontend = Join-Path $Root "frontend"

if (-not (Test-Path $frontend)) {
    Write-Error "frontend/ not found"
}

if (Test-Path (Join-Path $Root "venv\Scripts\Activate.ps1")) {
    .\venv\Scripts\Activate.ps1
}

Set-Location $frontend
if (-not (Test-Path "node_modules")) {
    npm install
}

Write-Host "UI: http://127.0.0.1:$Port (proxies /api -> backend on :8080)"
Write-Host "Start API in another terminal: .\scripts\api_server.ps1"
npm run dev -- --port $Port
