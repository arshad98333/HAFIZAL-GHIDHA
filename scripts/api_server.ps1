# Start the FastAPI HTTP server (Windows).
#
#   .\scripts\api_server.ps1
#   .\scripts\api_server.ps1 -Port 9000
#   .\scripts\api_server.ps1 -Reload

param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8080,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "venv not found at $py. Create it: python -m venv venv"
}

if (Test-Path ".\venv\Scripts\Activate.ps1") {
    .\venv\Scripts\Activate.ps1
}

function Test-PortInUse {
    param([string]$HostName, [int]$PortNum)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $PortNum, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne(300)
        if ($connected -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

if (Test-PortInUse -HostName $ListenHost -PortNum $Port) {
    Write-Host ""
    Write-Host "Port $Port is already in use on $ListenHost."
    Write-Host "Another API server may already be running in another terminal."
    Write-Host "Use that terminal, or stop it, or start on a different port:"
    Write-Host "  .\scripts\api_server.ps1 -Port 9000"
    exit 1
}

Write-Host "Using Python: $py"
& $py -m pip install -q fastapi uvicorn
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install fastapi uvicorn failed"
}

$argList = @(
    "-m", "uvicorn",
    "cold_chain.api.app:create_app",
    "--factory",
    "--host", $ListenHost,
    "--port", "$Port"
)
if ($Reload) {
    $argList += "--reload"
}

Write-Host "API docs: http://${ListenHost}:${Port}/docs"
& $py @argList
exit $LASTEXITCODE
