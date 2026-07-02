<#
.SYNOPSIS
    Build and deploy Axiom add-in to Revit 2025.

.DESCRIPTION
    Builds the Axiom.Revit.2025 solution in Release|x64, then copies the
    output DLLs and .addin manifest to the Revit 2025 add-ins folder.

.PARAMETER Configuration
    Build configuration. Default: Release.

.PARAMETER BuildOnly
    Build without deploying (skip copy to Addins folder).

.EXAMPLE
    .\deploy-revit-2025.ps1
    .\deploy-revit-2025.ps1 -Configuration Debug
    .\deploy-revit-2025.ps1 -BuildOnly
#>
param(
    [string]$Configuration = "Release",
    [switch]$BuildOnly,
    [switch]$ForceCloseRevit
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$slnPath = Join-Path $repoRoot "src\axiom_revit\Axiom.Revit.2025.sln"
$addinSource = Join-Path $repoRoot "src\axiom_revit\Axiom.RevitAddin.2025.addin"
$addinTarget = "C:\ProgramData\Autodesk\Revit\Addins\2025"
$outputDir = Join-Path $repoRoot "src\axiom_revit\Axiom.RevitAddin.2025\bin\x64\$Configuration\net8.0-windows"

Write-Host "=== Axiom Revit 2025 Build & Deploy ===" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Verify .NET 8 SDK ---
Write-Host "[1/4] Checking .NET SDK..." -ForegroundColor Yellow
$dotnetVersion = dotnet --version 2>$null
$dotnetMajor = if ($dotnetVersion) { [int]($dotnetVersion.Split(".")[0]) } else { 0 }
if ($dotnetMajor -lt 8) {
    Write-Host "ERROR: .NET SDK 8+ required (net8.0-windows target). Install from https://dotnet.microsoft.com/download/dotnet/8.0" -ForegroundColor Red
    Write-Host "Current dotnet version: $dotnetVersion" -ForegroundColor Red
    exit 1
}
Write-Host "  .NET SDK: $dotnetVersion" -ForegroundColor Green

# --- Step 2: Verify Revit 2025 API DLLs ---
Write-Host "[2/4] Checking Revit 2025 API..." -ForegroundColor Yellow
$revitApiPath = "$env:ProgramW6432\Autodesk\Revit 2025\RevitAPI.dll"
$revitApiUiPath = "$env:ProgramW6432\Autodesk\Revit 2025\RevitAPIUI.dll"
if (-not (Test-Path $revitApiPath)) {
    Write-Host "ERROR: RevitAPI.dll not found at $revitApiPath" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $revitApiUiPath)) {
    Write-Host "ERROR: RevitAPIUI.dll not found at $revitApiUiPath" -ForegroundColor Red
    exit 1
}
Write-Host "  RevitAPI.dll: Found" -ForegroundColor Green
Write-Host "  RevitAPIUI.dll: Found" -ForegroundColor Green

# --- Step 3: Build ---
Write-Host "[3/4] Building $Configuration|x64..." -ForegroundColor Yellow
dotnet build $slnPath -c $Configuration -p:Platform=x64
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Build failed." -ForegroundColor Red
    exit 1
}
Write-Host "  Build succeeded." -ForegroundColor Green

if ($BuildOnly) {
    Write-Host ""
    Write-Host "Build-only mode: skipping deployment." -ForegroundColor Yellow
    Write-Host "Output: $outputDir" -ForegroundColor Cyan
    exit 0
}

# --- Pre-deploy: Check if Revit is running (DLL lock) ---
$revitProc = Get-Process -Name "Revit" -ErrorAction SilentlyContinue
if ($revitProc) {
    Write-Host "" -ForegroundColor Red
    Write-Host "WARNING: Revit is currently running." -ForegroundColor Red
    Write-Host "  Axiom.RevitAddin.dll cannot be copied while Revit is running." -ForegroundColor Red
    Write-Host "  The DLL file is locked by the Revit.exe process." -ForegroundColor Red
    Write-Host "" -ForegroundColor Red
    Write-Host "Revit PID(s): $($revitProc.Id -join ', ')" -ForegroundColor Yellow
    Write-Host ""

    if ($ForceCloseRevit) {
        Write-Host "ForceCloseRevit flag set -- stopping Revit..." -ForegroundColor Yellow
        $revitProc | Stop-Process -Force
        Start-Sleep -Seconds 2
        Write-Host "  Revit closed." -ForegroundColor Green
    } else {
        $response = Read-Host "Continue anyway? (y/N)"
        if ($response -ne "y" -and $response -ne "Y") {
            Write-Host "Deployment cancelled. Close Revit and re-run." -ForegroundColor Yellow
            Write-Host "  Tip: Use -ForceCloseRevit to auto-close Revit before deploy." -ForegroundColor DarkGray
            exit 1
        }
    }
}

# --- Step 4: Deploy ---
Write-Host "[4/4] Deploying to $addinTarget..." -ForegroundColor Yellow

if (-not (Test-Path $addinTarget)) {
    New-Item -ItemType Directory -Path $addinTarget -Force | Out-Null
    Write-Host "  Created: $addinTarget" -ForegroundColor Green
}

# Generate .addin manifest with absolute assembly path
$addinLines = @(
    '<?xml version="1.0" encoding="utf-8"?>',
    '<RevitAddIns>',
    '  <AddIn Type="Application">',
    '    <Name>Axiom</Name>',
    "    <Assembly>$addinTarget\Axiom.RevitAddin.dll</Assembly>",
    '    <FullClassName>Axiom.RevitAddin.App</FullClassName>',
    '    <AddInId>E5AD3C50-0BB8-4ADA-B31B-5DCB2D408B5F</AddInId>',
    '    <VendorId>Axiom</VendorId>',
    '    <VendorDescription>Axiom Revit Automation</VendorDescription>',
    '  </AddIn>',
    '</RevitAddIns>'
)
$addinLines -join "`r`n" | Out-File -FilePath "$addinTarget\Axiom.RevitAddin.addin" -Encoding utf8
Write-Host "  Generated: Axiom.RevitAddin.addin (Assembly=$addinTarget\Axiom.RevitAddin.dll)" -ForegroundColor Green

# Copy output DLLs
$dlls = @(
    "Axiom.RevitAddin.dll",
    "Axiom.Core.dll"
)

foreach ($dll in $dlls) {
    $srcFile = Join-Path $outputDir $dll
    if (Test-Path $srcFile) {
        Copy-Item $srcFile $addinTarget -Force
        Write-Host "  Copied: $dll" -ForegroundColor Green
    } else {
        Write-Host "  ERROR: $dll not found at $srcFile" -ForegroundColor Red
        exit 1
    }
}

# Copy Newtonsoft.Json.dll -- search output dir and fallback to NuGet cache
$newtonsoftSrc = Join-Path $outputDir "Newtonsoft.Json.dll"
if (-not (Test-Path $newtonsoftSrc)) {
    # Fallback: search NuGet package cache
    $nugetCache = Join-Path $env:USERPROFILE ".nuget\packages\newtonsoft.json"
    if (Test-Path $nugetCache) {
        $newtonsoftSrc = Get-ChildItem -Path $nugetCache -Filter "Newtonsoft.Json.dll" -Recurse |
            Where-Object { $_.FullName -match "net[0-9]" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if ($newtonsoftSrc -and (Test-Path $newtonsoftSrc)) {
    Copy-Item $newtonsoftSrc $addinTarget -Force
    Write-Host "  Copied: Newtonsoft.Json.dll" -ForegroundColor Green
} else {
    Write-Host "  ERROR: Newtonsoft.Json.dll not found in output or NuGet cache." -ForegroundColor Red
    Write-Host "         Run 'dotnet restore' and rebuild, or install Newtonsoft.Json 13.0.3." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Cyan
Write-Host "Restart Revit 2025 to load the add-in." -ForegroundColor White
Write-Host "Look for the 'Axiom' tab in the ribbon." -ForegroundColor White
