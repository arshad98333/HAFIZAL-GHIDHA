# Deprecated: use watch-github.ps1 instead.
# Kept for backward compatibility.
#
#   .\scripts\watch-github.ps1
#   .\scripts\watch-github.ps1 -MirrorDesktop

param(
    [string]$Source = 'C:\Users\HI\Desktop\HAFIZAL-GHIDHA',
    [string]$Dest = 'C:\Users\HI\Desktop\HAFIZAL-GHIDHA-main',
    [int]$IntervalSeconds = 60
)

Write-Host 'watch-sync-desktop.ps1 is deprecated. Use watch-github.ps1 instead.'
Write-Host ''

$watchScript = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'watch-github.ps1'
if (-not (Test-Path $watchScript)) {
    Write-Error "Missing $watchScript. Run: git pull origin main"
}

& $watchScript -IntervalSeconds $IntervalSeconds -MirrorDesktop
