#Requires -Version 5.1
<#
.SYNOPSIS
    Mine Cursor AI, GitHub Copilot CLI, and Factory.ai sessions into the palace.

.DESCRIPTION
    Runs mempalace mine against all three AI chat sources in sequence.
    Each source gets its own wing so results are easy to filter.

.PARAMETER DryRun
    Show what would be filed without writing to the palace.

.PARAMETER Sources
    Which sources to mine. Default: all three (cursor, copilot, factory).
    Pass one or more of: cursor, copilot, factory.

.EXAMPLE
    .\mine-all-sessions.ps1
    .\mine-all-sessions.ps1 -DryRun
    .\mine-all-sessions.ps1 -Sources cursor, factory
    .\mine-all-sessions.ps1 -Sources copilot -DryRun

.NOTES
    Assumes `mempalace` is on PATH.  Install with: pip install mempalace
    or run from repo root:  uv run mempalace <args>
#>

param(
    [switch]$DryRun,
    [ValidateSet("cursor", "copilot", "factory")]
    [string[]]$Sources = @("cursor", "copilot", "factory")
)

$ErrorActionPreference = "Stop"

$CursorDir  = "$env:USERPROFILE\.cursor\chats"
$CopilotDir = "$env:USERPROFILE\.copilot\session-state"
$FactoryDir = "$env:USERPROFILE\.factory\sessions"

$dryFlag = if ($DryRun) { "--dry-run" } else { "" }

function Invoke-Mine {
    param([string]$Dir, [string]$Mode, [string]$Wing, [string]$Label)

    if (-not (Test-Path $Dir)) {
        Write-Host "  [SKIP] $Label`: $Dir not found" -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "--- $Label ---" -ForegroundColor Cyan

    $cmd = "python -m mempalace mine `"$Dir`" --mode $Mode --wing $Wing"
    if ($DryRun) { $cmd += " --dry-run" }

    Write-Host "  $cmd" -ForegroundColor DarkGray
    Invoke-Expression $cmd
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  MemPalace — Mine All Sessions" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
if ($DryRun) { Write-Host "  DRY RUN — nothing will be filed" -ForegroundColor Yellow }

foreach ($source in $Sources) {
    switch ($source) {
        "cursor"  { Invoke-Mine -Dir $CursorDir  -Mode "cursor" -Wing "cursor_chats"      -Label "Cursor AI" }
        "copilot" { Invoke-Mine -Dir $CopilotDir -Mode "convos" -Wing "copilot_sessions"  -Label "GitHub Copilot CLI" }
        "factory" { Invoke-Mine -Dir $FactoryDir -Mode "convos" -Wing "factory_sessions"  -Label "Factory.ai" }
    }
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Done.  Search with: mempalace search `"<query>`"" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
