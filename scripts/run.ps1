# THE single command for Windows - runs a profile and logs to pipeline_logs.json
#
#   .\scripts\run.ps1                    # rescore wave 1 (default)
#   .\scripts\run.ps1 -Wave 1 -Profile smoke
#   .\scripts\run.ps1 -Wave 1 -Profile wave
#   .\scripts\run.ps1 -Wave 1 -Profile full

param(
    [int]$Wave = 1,
    [ValidateSet("smoke", "wave", "rescore", "full")]
    [string]$Profile = "rescore",
    [int]$MaxRecords = 0,
    [switch]$SkipTests
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
    Write-Error "python not found. Create a venv: python -m venv venv"
}

# PowerShell: & @($py, "a", "b") is wrong - splat args only, not the executable.
$argList = @("scripts/local_run.py", "run", "--wave", "$Wave", "--profile", $Profile)
if ($MaxRecords -gt 0) {
    $argList += @("--max-records", "$MaxRecords")
}
if ($SkipTests) {
    $argList += "--skip-tests"
}

& $py @argList
exit $LASTEXITCODE
