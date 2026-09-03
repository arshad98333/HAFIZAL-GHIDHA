# Auto-sync repo -> HAFIZAL-GHIDHA-main folder.
# First loop: git pull main + copy. Then copy only every 30s.
#
#   .\scripts\watch-sync-desktop.ps1
# Press Ctrl+C to stop.

param(
    [string]$Source = 'C:\Users\HI\Desktop\HAFIZAL-GHIDHA',
    [string]$Dest = 'C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main',
    [int]$IntervalSeconds = 30
)

$ErrorActionPreference = 'Stop'
# PowerShell 7.3+ can treat ANY stderr line from a native command (git,
# npm, az, docker -- even routine progress/warning text on success) as a
# terminating error when combined with $ErrorActionPreference = "Stop".
# Disable that so only real failures (checked via $LASTEXITCODE) stop
# this script. No effect on Windows PowerShell 5.1.
$PSNativeCommandUseErrorActionPreference = $false
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$syncScript = Join-Path $scriptDir 'sync-desktop-folder.ps1'

if (-not (Test-Path $syncScript)) {
    $msg = 'Missing sync script: ' + $syncScript + '. Run: cd ' + $Source + '; git pull origin main'
    Write-Error $msg
}

Write-Host ('Watching ' + $Source + ' every ' + $IntervalSeconds + 's -> ' + $Dest)
Write-Host 'Press Ctrl+C to stop.'
Write-Host ''

$first = $true
while ($true) {
    if ($first) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $syncScript -Source $Source -Dest $Dest
        $first = $false
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $syncScript -Source $Source -Dest $Dest -RobocopyOnly
    }
    Start-Sleep -Seconds $IntervalSeconds
}
