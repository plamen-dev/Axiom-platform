# Revit 2027 Compatibility Runbook

Build, deploy, and test Axiom against Revit 2027.

---

## Prerequisites

| Requirement | Version | Check Command |
|-------------|---------|---------------|
| Revit 2027 | Installed at `C:\Program Files\Autodesk\Revit 2027` | `dir "C:\Program Files\Autodesk\Revit 2027\RevitAPI.dll"` |
| .NET 10 SDK | 10.x | `dotnet --version` |
| .NET 10 Desktop Runtime | 10.x | `dotnet --list-runtimes` (look for `Microsoft.WindowsDesktop.App 10.x`) |
| Git | Any recent version | `git --version` |

### Installing .NET 10 SDK

If not already installed:

```powershell
winget install Microsoft.DotNet.SDK.10
```

Or download from: https://dotnet.microsoft.com/download/dotnet/10.0

---

## Architecture

The Revit 2027 adapter uses the **shared source** pattern — no code duplication:

```
src/axiom_revit/
  Axiom.Core/                    # Shared source (2024 .csproj + source files)
  Axiom.Core.2027/               # 2027 project file only (links to shared source)
  Axiom.RevitAddin/              # Shared source (2024 .csproj + source files)
  Axiom.RevitAddin.2027/         # 2027 project file only (links to shared source)
  Axiom.Revit.sln                # 2024 solution (net48)
  Axiom.Revit.2027.sln           # 2027 solution (net10.0-windows)
  Axiom.RevitAddin.addin         # 2024 manifest
  Axiom.RevitAddin.2027.addin    # 2027 manifest
```

**Key differences between 2024 and 2027 builds:**

| Aspect | Revit 2024 | Revit 2027 |
|--------|-----------|-----------|
| Target framework | .NET Framework 4.8 (`net48`) | .NET 10 (`net10.0-windows`) |
| Project style | Old-style `.csproj` | SDK-style `.csproj` |
| RevitAPI.dll path | `C:\Program Files\Autodesk\Revit 2024\` | `C:\Program Files\Autodesk\Revit 2027\` |
| Newtonsoft.Json | NuGet via `packages.config` | NuGet via `PackageReference` |
| .addin folder | `C:\ProgramData\Autodesk\Revit\Addins\2024\` | `C:\Program Files\Autodesk\Revit\Addins\2027\` |
| C# language | 7.3 | Latest |

---

## Build Steps

### Option A: Automated (Recommended)

```powershell
# From the repo root:
.\scripts\deploy-revit-2027.ps1

# Build only (no deploy):
.\scripts\deploy-revit-2027.ps1 -BuildOnly

# Debug build + deploy:
.\scripts\deploy-revit-2027.ps1 -Configuration Debug
```

### Option B: Manual

```powershell
# 1. Verify .NET 10 SDK
dotnet --version
# Should show 10.x.x

# 2. Build the 2027 solution
cd src\axiom_revit
dotnet build Axiom.Revit.2027.sln -c Release -p:Platform=x64

# 3. Verify output
dir Axiom.RevitAddin.2027\bin\x64\Release\net10.0-windows\Axiom.RevitAddin.dll
dir Axiom.RevitAddin.2027\bin\x64\Release\net10.0-windows\Axiom.Core.dll
```

### Option C: Visual Studio

1. Open `src/axiom_revit/Axiom.Revit.2027.sln` in Visual Studio 2022 (17.14+)
2. Set platform to **x64**
3. Build → Build Solution (Ctrl+Shift+B)

---

## Deployment

### Deploy to Revit 2027

```powershell
$addinDir = "C:\Program Files\Autodesk\Revit\Addins\2027"
$outputDir = "src\axiom_revit\Axiom.RevitAddin.2027\bin\x64\Release\net10.0-windows"

# Create addins folder if needed
New-Item -ItemType Directory -Path $addinDir -Force

# Copy manifest
Copy-Item "src\axiom_revit\Axiom.RevitAddin.2027.addin" "$addinDir\Axiom.RevitAddin.addin"

# Copy DLLs
Copy-Item "$outputDir\Axiom.RevitAddin.dll" $addinDir
Copy-Item "$outputDir\Axiom.Core.dll" $addinDir
Copy-Item "$outputDir\Newtonsoft.Json.dll" $addinDir
```

### Verify deployment

```powershell
dir "C:\Program Files\Autodesk\Revit\Addins\2027\Axiom.RevitAddin.addin"
dir "C:\Program Files\Autodesk\Revit\Addins\2027\Axiom.RevitAddin.dll"
dir "C:\Program Files\Autodesk\Revit\Addins\2027\Axiom.Core.dll"
dir "C:\Program Files\Autodesk\Revit\Addins\2027\Newtonsoft.Json.dll"
```

---

## Testing

### Phase 1: Load Validation

1. Close Revit 2027 if running
2. Deploy using steps above
3. Start Revit 2027
4. Check for the **Axiom** tab in the ribbon
5. Click the **Prompt** button — the prompt dialog should open
6. Close the dialog

**Pass criteria:**
- No startup error dialogs
- Axiom tab visible
- Prompt button works

### Phase 2: Capability Smoke Tests

After Phase 1 passes, test each capability:

**InventoryModel (read-only, safest first):**
```
Type in Prompt dialog: Run InventoryModel
```
Expected: capability executes, no errors, returns element/parameter counts.

**CreateLevels:**
```
Type in Prompt dialog: Create 1 level at 0 feet
```
Expected: one level created at elevation 0'-0".

**CreateGrids:**
```
Type in Prompt dialog: Create 1 vertical grid 50 ft long
```
Expected: one grid line created.

### Phase 2b: Plan Execution Queue (Validated 2026-05-23)

After Phase 2 passes, test the plan execution queue:

```
Run InventoryModel parameter schema plan max 10
```
Expected: 10 categories complete, manifest created, no BLOCKED_UNSAFE.

```
Run InventoryModel parameter schema plan priority only
```
Expected: 16-20 priority categories complete.

**Deploy script notes:**
- If Revit is running, deploy warns about DLL lock and cancels by default
- Use `-ForceCloseRevit` flag to auto-close Revit before deploy
- Use `-BuildOnly` to build without deploying

### Phase 3: Python CLI via Pipe

After Phase 2 passes, test the Python CLI while Revit 2027 is running:

```powershell
# With Revit 2027 open and Axiom loaded:
python -m poetry run axiom inventory-model
python -m poetry run axiom prompt "Create 3 levels spaced 12 ft apart"
python -m poetry run axiom prompt "Create 5 vertical grids spaced 10 ft apart"
```

---

## Troubleshooting

### Build errors

| Error | Cause | Fix |
|-------|-------|-----|
| `NETSDK1045: The current .NET SDK does not support targeting` | .NET 10 SDK not installed | Install .NET 10 SDK |
| `Could not locate RevitAPI.dll` | Revit 2027 not installed at expected path | Verify `C:\Program Files\Autodesk\Revit 2027\RevitAPI.dll` exists |
| `Type or namespace 'Autodesk' could not be found` | Same as above | Same fix |

### Runtime errors

| Error | Cause | Fix |
|-------|-------|-----|
| Axiom tab doesn't appear | DLLs not in correct addins folder | Verify all files in `C:\Program Files\Autodesk\Revit\Addins\2027\` |
| "Could not load file or assembly" | Missing .NET 10 Desktop Runtime | Install from https://dotnet.microsoft.com/download/dotnet/10.0 |
| "Axiom Startup Error" dialog | Exception in `App.OnStartup` | Check Revit journal log at `%LocalAppData%\Autodesk\Revit\Autodesk Revit 2027\Journals\` |
| Pipe connection failed | Named pipe not connecting | Check that AxiomPipeServer started (no startup errors) |

### API Compatibility Issues

If any Revit API has changed between 2024 and 2027, document the issue here:

| API | 2024 Behavior | 2027 Change | Status |
|-----|---------------|-------------|--------|
| `ElementId.IntegerValue` | Returns `int` | **Removed** — use `ElementId.Value` (returns `long`) | Fixed via `RevitElementIdCompat` helper with `#if REVIT_2027` |

---

## Coexistence

Revit 2024 and 2027 addins are fully independent:

- Different addins folders (`2024\` vs `2027\`)
- Different solution files (`.sln`)
- Different output directories
- Same source code (shared via project file links)
- Same assembly names — do NOT load both Revit versions simultaneously

---

## Related Documents

- [Revit Multi-Version Runbook](revit-multi-version-runbook.md) — strategy overview for 2024/2025/2026/2027
- [Revit Version Compatibility Strategy](../architecture/revit-version-compatibility-strategy.md) — shared-capability architecture
- [Capability Compatibility Fixtures](../../tests/fixtures/compatibility/) — version validation tracking
