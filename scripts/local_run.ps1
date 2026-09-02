# Local run helper for Windows PowerShell.
#
# RECOMMENDED — single command:
#   .\scripts\run.ps1 -Wave 1
#   .\scripts\run.ps1 -Wave 1 -Profile smoke
#
# Or via this wrapper:
#   .\scripts\local_run.ps1 run -Wave 1 -Profile rescore

param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("run", "all", "steps", "step", "audit", "kpi", "preflight", "rescore")]
    [string]$Mode,

    [Parameter(Position = 1)]
    [string]$StepName,

    [int]$Wave = 0,
    [ValidateSet("smoke", "wave", "rescore", "full", "")]
    [string]$Profile = "",
    [int]$MaxRecords = 0,
    [switch]$SkipTests,
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (Test-Path ".\venv\Scripts\Activate.ps1") {
    .\venv\Scripts\Activate.ps1
}

$py = "python"
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
    Write-Error "python not found on PATH. Activate your venv first."
}

$cmd = @($py, "scripts/local_run.py", $Mode)

if ($Mode -eq "step") {
    if (-not $StepName) {
        Write-Error "step mode requires a step name, e.g. .\scripts\local_run.ps1 step setup"
    }
    $cmd += $StepName
}

if ($Wave -gt 0) {
    $cmd += @("--wave", "$Wave")
}
if ($Profile) {
    $cmd += @("--profile", $Profile)
}
if ($MaxRecords -gt 0) {
    $cmd += @("--max-records", "$MaxRecords")
}
if ($SkipTests) {
    $cmd += "--skip-tests"
}
if ($SkipSetup) {
    $cmd += "--skip-setup"
}

& @cmd
exit $LASTEXITCODE
