# Auto-pull from GitHub when origin/main moves. Installs deps on each update.
# ASCII-only for Windows PowerShell 5.1.
#
#   .\scripts\watch-github.ps1
#   .\scripts\watch-github.ps1 -IntervalSeconds 120
#   .\scripts\watch-github.ps1 -MirrorDesktop   # also copy to HAFIZAL-GHIDHA-main
#
# Press Ctrl+C to stop.

param(
    [string]$Branch = "main",
    [int]$IntervalSeconds = 60,
    [switch]$MirrorDesktop,
    [switch]$Deploy
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$updateScript = Join-Path $Root "scripts\update-all.ps1"
if (-not (Test-Path $updateScript)) {
    Write-Error "Missing $updateScript. Run: .\scripts\connect-github.ps1"
}

Write-Host "Watching origin/$Branch every ${IntervalSeconds}s"
Write-Host "Repo:   $Root"
if ($MirrorDesktop) {
    Write-Host "Mirror: enabled (HAFIZAL-GHIDHA-main)"
}
if ($Deploy) {
    Write-Host "Deploy: enabled on each update (Azure)"
}
Write-Host "Press Ctrl+C to stop."
Write-Host ""

while ($true) {
    $stamp = Get-Date -Format "HH:mm:ss"
    try {
        git fetch origin 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }

        $local = (git rev-parse HEAD).Trim()
        $remote = (git rev-parse "origin/$Branch").Trim()

        if ($local -ne $remote) {
            Write-Host "[$stamp] Update available: $local -> $remote"
            $args = @()
            if ($MirrorDesktop) { $args += '-MirrorDesktop' }
            if ($Deploy) { $args += '-Deploy' }
            & $updateScript @args
            if ($LASTEXITCODE -ne 0) { throw 'update-all failed' }
            Write-Host "[$stamp] Updated to $(git rev-parse --short HEAD)"
        } else {
            Write-Host "[$stamp] Up to date ($(git rev-parse --short HEAD))"
        }
    } catch {
        Write-Host "[$stamp] Error: $_"
    }

    Start-Sleep -Seconds $IntervalSeconds
}
