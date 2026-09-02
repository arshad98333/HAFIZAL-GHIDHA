# Auto-sync when files change in the git repo (optional background watcher).
# Run in a separate PowerShell window while you develop:
#
#   .\scripts\watch-sync-desktop.ps1
#
# Press Ctrl+C to stop.

param(
    [string]$Source = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA",
    [string]$Dest = "C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main",
    [int]$IntervalSeconds = 30
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$syncScript = Join-Path $scriptDir "sync-desktop-folder.ps1"

Write-Host "Watching $Source every ${IntervalSeconds}s -> $Dest"
Write-Host "Press Ctrl+C to stop."

while ($true) {
    & $syncScript -Source $Source -Dest $Dest
    Start-Sleep -Seconds $IntervalSeconds
}
