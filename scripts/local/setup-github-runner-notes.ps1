<#
.SYNOPSIS
    Checklist + environment probe for configuring the Axiom-01 self-hosted
    GitHub Actions runner. PRINTS GUIDANCE ONLY - it does NOT register a
    runner, does NOT download anything, and does NOT contain tokens/secrets.

.DESCRIPTION
    Run this on Axiom-01 to sanity-check prerequisites before registering the
    self-hosted runner described in
    docs/runbooks/windows-revit-self-hosted-runner.md.

    The actual runner registration token must be obtained interactively from
    the GitHub repo Settings -> Actions -> Runners page and pasted into the
    official ./config.cmd step. NEVER hard-code or commit that token.

.EXAMPLE
    .\scripts\local\setup-github-runner-notes.ps1
#>
param()

$ErrorActionPreference = "Continue"

function Write-Section($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Test-Cmd($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Show-Check($label, $ok, $detail) {
    $mark = if ($ok) { "[ OK ]" } else { "[MISS]" }
    $color = if ($ok) { "Green" } else { "Yellow" }
    Write-Host ("{0} {1}{2}" -f $mark, $label, $(if ($detail) { " - $detail" } else { "" })) -ForegroundColor $color
}

Write-Host "Axiom-01 self-hosted runner readiness check (guidance only)" -ForegroundColor White
Write-Host "No tokens are requested, printed, or stored by this script." -ForegroundColor DarkGray

# --- Context ---------------------------------------------------------------
Write-Section "Machine / user context"
Write-Host "Machine : $env:COMPUTERNAME"
Write-Host "User    : $(whoami)"
try {
    $isAdmin = (New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch {
    $isAdmin = $false
}
Write-Host "Admin   : $isAdmin"
if ($isAdmin) {
    Write-Host "NOTE: Running the runner as a highly-privileged/admin service is" -ForegroundColor Yellow
    Write-Host "      discouraged. Prefer the interactive Revit-licensed user so" -ForegroundColor Yellow
    Write-Host "      Revit licensing and user profile paths resolve correctly." -ForegroundColor Yellow
}

# --- Tooling ---------------------------------------------------------------
Write-Section "Required tooling"
Show-Check "git"     (Test-Cmd git)     $(if (Test-Cmd git) { (git --version) })
Show-Check "python"  (Test-Cmd python)  $(if (Test-Cmd python) { (python --version 2>&1) })
Show-Check "poetry"  (Test-Cmd poetry)  $(if (Test-Cmd poetry) { (poetry --version 2>&1) })
Show-Check "dotnet"  (Test-Cmd dotnet)  $(if (Test-Cmd dotnet) { ("SDK " + (dotnet --version 2>&1)) })

# --- Revit 2027 ------------------------------------------------------------
Write-Section "Revit 2027 (for optional add-in build)"
$revitApi = "$env:ProgramW6432\Autodesk\Revit 2027\RevitAPI.dll"
Show-Check "RevitAPI.dll" (Test-Path $revitApi) $revitApi
$addinDir = "C:\Program Files\Autodesk\Revit\Addins\2027"
Show-Check "Addins\2027 dir" (Test-Path $addinDir) $addinDir
Write-Host "Reminder: this foundation workflow only BUILDS (BuildOnly). It does" -ForegroundColor DarkGray
Write-Host "not copy DLLs into the Addins folder. Live deploy stays manual." -ForegroundColor DarkGray

# --- Runner labels ---------------------------------------------------------
Write-Section "Required runner labels"
Write-Host "Register the runner with ALL of these labels:" -ForegroundColor White
Write-Host "  self-hosted, windows, axiom-01, revit-2027"
Write-Host "(self-hosted + windows are applied automatically; add axiom-01 and"
Write-Host " revit-2027 explicitly during ./config.cmd via --labels.)"

# --- Next steps ------------------------------------------------------------
Write-Section "Next steps (manual)"
Write-Host "1. Open GitHub -> repo Settings -> Actions -> Runners -> New self-hosted runner (Windows x64)."
Write-Host "2. Follow the official download/config steps shown there. The page"
Write-Host "   provides a one-time registration TOKEN - paste it into ./config.cmd."
Write-Host "   Do NOT store that token in this repo."
Write-Host "3. Add labels: --labels axiom-01,revit-2027"
Write-Host "4. Start the runner (./run.cmd) or install as a service (see runbook)."
Write-Host "5. Trigger: GitHub -> Actions -> 'Windows Revit Validation (Axiom-01)'"
Write-Host "   -> Run workflow (workflow_dispatch)."
Write-Host ""
Write-Host "Full guidance: docs/runbooks/windows-revit-self-hosted-runner.md" -ForegroundColor Cyan
