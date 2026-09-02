# Local run helper for Windows PowerShell.
#
# Option 1 -- one command (setup + pipeline):
#   .\scripts\local_run.ps1 all -Wave 1 -MaxRecords 10
#   .\scripts\local_run.ps1 all -Wave 1
#
# Option 2 -- print step-by-step commands:
#   .\scripts\local_run.ps1 steps -Wave 1 -MaxRecords 10
#
# Option 2 -- run one step:
#   .\scripts\local_run.ps1 step setup
#   .\scripts\local_run.ps1 step plan -Wave 1
#   .\scripts\local_run.ps1 step generate -Wave 1 -MaxRecords 10

param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("all", "steps", "step", "audit")]
    [string]$Mode,

    [Parameter(Position = 1)]
    [string]$StepName,

    [int]$Wave = 0,
    [int]$MaxRecords = 0,
    [switch]$SkipTests,
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

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
