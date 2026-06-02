<#
.SYNOPSIS
    Axiom Validation Automation Loop v0 — Windows wrapper.

.DESCRIPTION
    Drives the validation loop around the single live-Revit human step:

      pre   : record context/git, run Python tests + ruff, optionally deploy,
              capture deployed DLL timestamps, and print the manual Revit steps.
      scan  : after the human performs the Revit step, scan evidence across ALL
              user profiles, validate conditions, and classify pass/fail.
      all   : pre work followed immediately by scan (live step already done).

    Admin / non-admin handling:
      - git / tests / evidence scanning run in the NORMAL (non-admin) shell.
      - Only deploy needs admin. Pass -Deploy to attempt deploy. If this shell
        is NOT elevated and -Deploy is requested, the script can relaunch ONLY
        the deploy step elevated via -ElevateDeploy, or otherwise reports
        needs_admin without touching the rest of the loop.
      - Evidence scanning always searches C:\Users\*\AppData\Local\Axiom to
        avoid IMSAdmin vs interactive-user LOCALAPPDATA confusion.

.PARAMETER Scenario
    Validation scenario id or alias. Default: set_parameter_preview_apply_wall_comments.

.PARAMETER Branch
    Target git branch to record (and pull when -Pull is set).

.PARAMETER RevitVersion
    Revit version for deploy/evidence. Default: 2027.

.PARAMETER Phase
    pre | scan | all. Default: pre.

.PARAMETER MaxAttempts
    Bounded retry budget for the evidence scan. Default: 5. Increase to confirm
    larger testing concepts (e.g. -MaxAttempts 20).

.PARAMETER Pull
    Fast-forward pull the target branch before running (requires -Branch).

.PARAMETER NoTests
    Skip the Python tests + ruff in pre/all phases.

.PARAMETER Deploy
    Attempt build/deploy via scripts/deploy-revit-<version>.ps1 (needs admin).

.PARAMETER ElevateDeploy
    When -Deploy is requested and this shell is not elevated, relaunch ONLY the
    deploy step in an elevated shell, then continue the loop non-elevated.

.PARAMETER RunId
    Reuse/resume an existing run id (typically for -Phase scan).

.EXAMPLE
    # Before live Revit: tests + manual steps
    .\scripts\local\run-validation-loop.ps1 -Phase pre -Branch main

.EXAMPLE
    # After live Revit: evaluate evidence with a bigger retry budget
    .\scripts\local\run-validation-loop.ps1 -Phase scan -MaxAttempts 20

.EXAMPLE
    # Deploy from a non-admin shell, elevating only the deploy step
    .\scripts\local\run-validation-loop.ps1 -Phase pre -Deploy -ElevateDeploy
#>
param(
    [string]$Scenario = "set_parameter_preview_apply_wall_comments",
    [string]$Branch,
    [string]$RevitVersion = "2027",
    [ValidateSet("pre", "scan", "all")]
    [string]$Phase = "pre",
    [int]$MaxAttempts = 5,
    [switch]$Pull,
    [switch]$NoTests,
    [switch]$Deploy,
    [switch]$ElevateDeploy,
    [string]$RunId
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $repoRoot

function Test-IsAdmin {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

$isAdmin = Test-IsAdmin
Write-Host "=== Axiom Validation Automation Loop v0 ===" -ForegroundColor Cyan
Write-Host "  Scenario:     $Scenario"
Write-Host "  Phase:        $Phase"
Write-Host "  Revit:        $RevitVersion"
Write-Host "  Max attempts: $MaxAttempts"
Write-Host "  Admin shell:  $isAdmin"
Write-Host ""

# --- Admin-only deploy handling -------------------------------------------
# Deploy is the ONLY step that needs elevation. Everything else (git, tests,
# evidence scanning) runs in the normal shell. We deploy SEPARATELY from the
# Python runner so the runner never needs admin.
$deployHandledExternally = $false
if ($Deploy -and ($Phase -eq "pre" -or $Phase -eq "all")) {
    $deployScript = Join-Path $repoRoot "scripts\deploy-revit-$RevitVersion.ps1"
    if (-not (Test-Path $deployScript)) {
        Write-Host "ERROR: Deploy script not found: $deployScript" -ForegroundColor Red
        Write-Host "Classification hint: deploy_failed" -ForegroundColor Yellow
        exit 1
    }
    if ($isAdmin) {
        Write-Host "[deploy] Running deploy in this elevated shell..." -ForegroundColor Yellow
        & powershell -ExecutionPolicy Bypass -File $deployScript -ForceCloseRevit
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Classification hint: deploy_failed" -ForegroundColor Red
            exit 1
        }
        $deployHandledExternally = $true
    }
    elseif ($ElevateDeploy) {
        Write-Host "[deploy] Not elevated; relaunching ONLY the deploy step as admin..." -ForegroundColor Yellow
        $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList @(
            "-ExecutionPolicy", "Bypass", "-File", "`"$deployScript`"", "-ForceCloseRevit"
        )
        if ($p.ExitCode -ne 0) {
            Write-Host "Classification hint: deploy_failed (elevated deploy exit $($p.ExitCode))" -ForegroundColor Red
            exit 1
        }
        $deployHandledExternally = $true
    }
    else {
        Write-Host "Classification hint: needs_admin" -ForegroundColor Red
        Write-Host "Deploy requires an elevated shell. Re-run with -ElevateDeploy," -ForegroundColor Yellow
        Write-Host "or run this script from an Administrator PowerShell." -ForegroundColor Yellow
        exit 1
    }
}

# --- Build the Python runner argument list (non-admin) ---------------------
# Note: do NOT use $args here; it is a PowerShell automatic/reserved variable.
$runnerArgs = @("validation-run", "--scenario", $Scenario, "--phase", $Phase,
                "--revit-version", $RevitVersion, "--max-attempts", $MaxAttempts)

if ($Branch)  { $runnerArgs += @("--branch", $Branch) }
if ($Pull)    { $runnerArgs += "--pull" }
if ($NoTests) { $runnerArgs += "--no-tests" }
if ($RunId)   { $runnerArgs += @("--run-id", $RunId) }

# Deploy is handled above (elevated/separate) so the runner never needs admin.
$runnerArgs += "--no-deploy"

Write-Host "[runner] poetry run axiom $($runnerArgs -join ' ')" -ForegroundColor DarkGray
& poetry run axiom @runnerArgs
$runnerExit = $LASTEXITCODE

Write-Host ""
if ($deployHandledExternally) {
    Write-Host "Note: deploy was executed separately (elevated)." -ForegroundColor DarkGray
}
exit $runnerExit
