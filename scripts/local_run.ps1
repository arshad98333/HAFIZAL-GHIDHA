# Local run helper for Windows PowerShell.
#
# RECOMMENDED - single command:
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
# PowerShell 7.3+ can treat ANY stderr line from a native command (git,
# npm, az, docker -- even routine progress/warning text on success) as a
# terminating error when combined with $ErrorActionPreference = "Stop".
# Disable that so only real failures (checked via $LASTEXITCODE) stop
# this script. No effect on Windows PowerShell 5.1.
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (Test-Path ".\venv\Scripts\Activate.ps1") {
    .\venv\Scripts\Activate.ps1
}

$py = "python"
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
    Write-Error "python not found on PATH. Activate your venv first."
}

$argList = @("scripts/local_run.py", $Mode)

if ($Mode -eq "step") {
    if (-not $StepName) {
        Write-Error "step mode requires a step name, e.g. .\scripts\local_run.ps1 step setup"
    }
    $argList += $StepName
}

if ($Wave -gt 0) {
    $argList += @("--wave", "$Wave")
}
if ($Profile) {
    $argList += @("--profile", $Profile)
}
if ($MaxRecords -gt 0) {
    $argList += @("--max-records", "$MaxRecords")
}
if ($SkipTests) {
    $argList += "--skip-tests"
}
if ($SkipSetup) {
    $argList += "--skip-setup"
}

& $py @argList
exit $LASTEXITCODE
