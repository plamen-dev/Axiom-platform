# Revit Multi-Version Build & Test Runbook

## Overview

Axiom targets **Revit 2024** as the baseline. This document covers building and testing against **Revit 2027** (trial or licensed) without replacing the 2024 baseline.

**Do not assume Revit 2027 API compatibility until tested.**

---

## Version Matrix

| Property | Revit 2024 | Revit 2027 |
|----------|-----------|-----------|
| Runtime | .NET Framework 4.8 | .NET 10 |
| Target Framework | `net48` (old-style .csproj) | `net10.0-windows` (SDK-style .csproj) |
| RevitAPI.dll path | `C:\Program Files\Autodesk\Revit 2024\RevitAPI.dll` | `C:\Program Files\Autodesk\Revit 2027\RevitAPI.dll` |
| RevitAPIUI.dll path | `C:\Program Files\Autodesk\Revit 2024\RevitAPIUI.dll` | `C:\Program Files\Autodesk\Revit 2027\RevitAPIUI.dll` |
| .addin manifest folder | `C:\ProgramData\Autodesk\Revit\Addins\2024\` | `C:\Program Files\Autodesk\Revit\Addins\2027\` |
| .csproj format | Legacy (ToolsVersion 15.0) | SDK-style recommended |
| C# language | 7.3 | 12+ |
| Add-in isolation | Not available | `AddInDependencyBase`, `PublicAssemblies`, `Dependencies` |

---

## Version-Specific References in the Codebase

### Files with hard-coded Revit 2024 paths

| File | Line(s) | Reference |
|------|---------|-----------|
| `src/axiom_revit/Axiom.Core/Axiom.Core.csproj` | 56, 60 | `$(ProgramW6432)\Autodesk\Revit 2024\RevitAPI.dll` / `RevitAPIUI.dll` |
| `src/axiom_revit/Axiom.RevitAddin/Axiom.RevitAddin.csproj` | 56, 60 | `$(ProgramW6432)\Autodesk\Revit 2024\RevitAPI.dll` / `RevitAPIUI.dll` |

These are the **only** version-specific paths in the entire C# solution. Everything else (capabilities, services, bridge) uses the Revit API through type references that should remain compatible across versions unless Autodesk made breaking changes.

### .addin manifest

`src/axiom_revit/Axiom.RevitAddin.addin` — version-neutral content, but must be placed in the version-specific addins folder.

---

## Recommended Multi-Version Strategy

### Option A: MSBuild Property Override (Simplest, No File Changes)

Override the Revit version at build time using an MSBuild property. This works with the existing legacy .csproj files.

**How it works:**

The existing HintPaths use `$(ProgramW6432)\Autodesk\Revit 2024\`. To build against 2027 without modifying the .csproj, define a property that the HintPath references.

**Step 1:** Replace hard-coded version in both .csproj files (one-time change):

```xml
<!-- Before -->
<HintPath>$(ProgramW6432)\Autodesk\Revit 2024\RevitAPI.dll</HintPath>

<!-- After -->
<HintPath>$(ProgramW6432)\Autodesk\Revit $(RevitVersion)\RevitAPI.dll</HintPath>
```

Add a default at the top of each .csproj `<PropertyGroup>`:

```xml
<RevitVersion Condition="'$(RevitVersion)' == ''">2024</RevitVersion>
```

**Step 2:** Build for a specific version:

```powershell
# Default (2024)
msbuild Axiom.Revit.sln /p:Configuration=Debug /p:Platform=x64

# Revit 2027
msbuild Axiom.Revit.sln /p:Configuration=Debug /p:Platform=x64 /p:RevitVersion=2027
```

**Pros:** Minimal change, single source, easy CI matrix.
**Cons:** Still targets net48. Revit 2027 may require net10.0 — in which case this option won't work and you need Option B.

### Option B: Parallel SDK-Style .csproj for 2027 (Recommended if net48 ≠ net10.0)

Create separate .csproj files for 2027 that use SDK-style format and target `net10.0-windows`.

```
src/axiom_revit/
├── Axiom.Core/
│   ├── Axiom.Core.csproj              ← 2024 (net48, legacy)
│   └── Axiom.Core.2027.csproj         ← 2027 (net10.0-windows, SDK-style)
├── Axiom.RevitAddin/
│   ├── Axiom.RevitAddin.csproj        ← 2024 (net48, legacy)
│   └── Axiom.RevitAddin.2027.csproj   ← 2027 (net10.0-windows, SDK-style)
├── Axiom.Revit.sln                    ← 2024 solution
└── Axiom.Revit.2027.sln              ← 2027 solution
```

**Sample `Axiom.Core.2027.csproj`:**

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0-windows</TargetFramework>
    <RootNamespace>Axiom.Core</RootNamespace>
    <AssemblyName>Axiom.Core</AssemblyName>
    <LangVersion>latest</LangVersion>
    <Nullable>disable</Nullable>
  </PropertyGroup>

  <ItemGroup>
    <Reference Include="RevitAPI">
      <HintPath>$(ProgramW6432)\Autodesk\Revit 2027\RevitAPI.dll</HintPath>
      <Private>false</Private>
    </Reference>
    <Reference Include="RevitAPIUI">
      <HintPath>$(ProgramW6432)\Autodesk\Revit 2027\RevitAPIUI.dll</HintPath>
      <Private>false</Private>
    </Reference>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.4" />
  </ItemGroup>
</Project>
```

**Sample `Axiom.RevitAddin.2027.csproj`:**

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0-windows</TargetFramework>
    <RootNamespace>Axiom.RevitAddin</RootNamespace>
    <AssemblyName>Axiom.RevitAddin</AssemblyName>
    <LangVersion>latest</LangVersion>
    <UseWindowsForms>true</UseWindowsForms>
    <Nullable>disable</Nullable>
  </PropertyGroup>

  <ItemGroup>
    <Reference Include="RevitAPI">
      <HintPath>$(ProgramW6432)\Autodesk\Revit 2027\RevitAPI.dll</HintPath>
      <Private>false</Private>
    </Reference>
    <Reference Include="RevitAPIUI">
      <HintPath>$(ProgramW6432)\Autodesk\Revit 2027\RevitAPIUI.dll</HintPath>
      <Private>false</Private>
    </Reference>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.4" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\Axiom.Core\Axiom.Core.2027.csproj" />
  </ItemGroup>
</Project>
```

**Pros:** Clean separation, proper framework targeting, no risk to 2024 builds.
**Cons:** Two sets of project files to maintain (source files are shared — only build config differs).

### Option C: Conditional Multi-Targeting in SDK-Style .csproj

Migrate both projects to SDK-style .csproj with multi-targeting:

```xml
<TargetFrameworks>net48;net10.0-windows</TargetFrameworks>
```

**Not recommended yet** — this requires migrating the 2024 .csproj from legacy to SDK format, which changes the baseline. Defer until 2027 compatibility is validated.

---

## .addin Manifest Deployment

### Revit 2024 (current)

Copy the .addin file and built DLLs:

```powershell
$source = "src\axiom_revit\Axiom.RevitAddin\bin\x64\Debug"
$addinDir = "C:\ProgramData\Autodesk\Revit\Addins\2024"

Copy-Item "src\axiom_revit\Axiom.RevitAddin.addin" "$addinDir\Axiom.RevitAddin.addin"
Copy-Item "$source\Axiom.RevitAddin.dll" "$addinDir\Axiom.RevitAddin.dll"
Copy-Item "$source\Axiom.Core.dll" "$addinDir\Axiom.Core.dll"
Copy-Item "$source\Newtonsoft.Json.dll" "$addinDir\Newtonsoft.Json.dll"
```

### Revit 2027

Same .addin manifest content, different target folder:

```powershell
$source2027 = "src\axiom_revit\Axiom.RevitAddin\bin\x64\Debug\net10.0-windows"  # if using SDK-style
$addinDir2027 = "C:\Program Files\Autodesk\Revit\Addins\2027"

# Create the 2027 addins folder if needed
New-Item -ItemType Directory -Force -Path $addinDir2027

Copy-Item "src\axiom_revit\Axiom.RevitAddin.addin" "$addinDir2027\Axiom.RevitAddin.addin"
Copy-Item "$source2027\Axiom.RevitAddin.dll" "$addinDir2027\Axiom.RevitAddin.dll"
Copy-Item "$source2027\Axiom.Core.dll" "$addinDir2027\Axiom.Core.dll"
Copy-Item "$source2027\Newtonsoft.Json.dll" "$addinDir2027\Newtonsoft.Json.dll"
```

The `.addin` manifest file itself is version-neutral:

```xml
<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>Axiom</Name>
    <Assembly>Axiom.RevitAddin.dll</Assembly>
    <FullClassName>Axiom.RevitAddin.App</FullClassName>
    <AddInId>E5AD3C50-0BB8-4ADA-B31B-5DCB2D408B5F</AddInId>
    <VendorId>Axiom</VendorId>
    <VendorDescription>Axiom Revit Automation</VendorDescription>
  </AddIn>
</RevitAddIns>
```

**Note:** Revit 2027 introduces add-in isolation features (`PublicAssemblies`, `Dependencies`). These are optional and can be added later if assembly conflicts arise. Do not add them preemptively.

---

## Revit 2027 Compatibility Testing Procedure

### Prerequisites

- Windows machine with Revit 2027 (trial or licensed) installed
- .NET 10 SDK installed (`dotnet --version` → 10.x)
- Visual Studio 2022 17.14+ (for .NET 10 support)

### Step 1: Verify Revit 2027 API DLLs exist

```powershell
Test-Path "C:\Program Files\Autodesk\Revit 2027\RevitAPI.dll"
Test-Path "C:\Program Files\Autodesk\Revit 2027\RevitAPIUI.dll"
```

### Step 2: Create 2027 project files (Option B)

If not already done, create the `*.2027.csproj` and `*.2027.sln` files as described in Option B above.

### Step 3: Build for 2027

```powershell
cd src\axiom_revit
dotnet build Axiom.Revit.2027.sln -c Debug
```

### Step 4: Watch for build errors

**Expected issues to investigate:**

| Risk | Details | Likely Fix |
|------|---------|------------|
| Namespace changes | Autodesk may have moved/renamed types | Update `using` directives |
| Removed APIs | `FilteredElementCollector` method signatures may change | Check SDK release notes |
| WinForms changes | `System.Windows.Forms` on .NET 10 may differ | Test dialog rendering |
| Assembly loading | .NET 10 has different assembly resolution | Verify all DLL deps load |
| `LangVersion` | C# 12+ enables new syntax; old code should still compile | Should be fine |

### Step 5: Deploy to 2027

Follow the .addin manifest deployment steps above for Revit 2027.

### Step 6: Test in Revit 2027

Run these prompts and document results:

1. `Create 5 gridlines spaced 10 ft apart` → CreateGrids
2. `Create 3 levels spaced 12 ft apart` → CreateLevels
3. `Run InventoryModel` → InventoryModel

**For each, record:**
- Build succeeded? (yes/no)
- Add-in loaded in Revit? (yes/no)
- Axiom tab appeared? (yes/no)
- Prompt dialog opened? (yes/no)
- Capability executed correctly? (yes/no)
- Any error messages or exceptions

### Step 7: Document findings

Update this runbook with actual compatibility results after testing.

---

## Known Risks

1. **Framework jump (net48 → net10.0):** This is not a minor version bump. Binary compatibility is not guaranteed. All DLLs must be rebuilt against .NET 10.

2. **Newtonsoft.Json compatibility:** The current solution uses Newtonsoft.Json 13.0.4 via packages.config (legacy NuGet). SDK-style projects use `<PackageReference>` instead. Verify the same version is available for net10.0.

3. **WinForms on .NET 10:** `AxiomPromptDialog` and `GridPromptDialog` use System.Windows.Forms. WinForms is supported on .NET 10 but rendering may differ slightly.

4. **RevitAPI breaking changes:** Autodesk may have deprecated or changed APIs used by Axiom. Key APIs to validate:
   - `FilteredElementCollector` (used by ModelInventoryService)
   - `Document.Create.NewGrid` (used by GridCreationService)
   - `Level.Create` (used by LevelCreationService)
   - `IExternalApplication` / `IExternalCommand` interfaces
   - `UIControlledApplication.CreateRibbonTab/Panel`
   - Named pipe communication (`System.IO.Pipes`)

5. **Trial limitations:** Revit 2027 trial may have feature or time restrictions. Verify the trial supports add-in loading before investing build effort.

---

## Keeping 2024 Stable

**Do not modify these files for 2027 support:**

- `Axiom.Core.csproj` — leave targeting net48 with Revit 2024 paths
- `Axiom.RevitAddin.csproj` — same
- `Axiom.Revit.sln` — same
- `Axiom.RevitAddin.addin` — content is already version-neutral

**When 2027 support is validated**, we can choose to either:
- Maintain parallel .csproj files (Option B) indefinitely
- Migrate to SDK-style multi-targeting (Option C) as a future consolidation step
- Drop 2024 support once the team has fully transitioned

---

## Quick Reference

### Build and deploy 2024 (current baseline)

```powershell
cd src\axiom_revit
msbuild Axiom.Revit.sln /p:Configuration=Debug /p:Platform=x64
# Deploy to C:\ProgramData\Autodesk\Revit\Addins\2024\
```

### Build and deploy 2027 (when ready)

```powershell
cd src\axiom_revit
dotnet build Axiom.Revit.2027.sln -c Debug
# Deploy to C:\Program Files\Autodesk\Revit\Addins\2027\
```

### Python side (unchanged for both versions)

```powershell
python -m poetry install
python -m poetry run pytest                          # 158 tests
python -m poetry run axiom test-grids --mode simulate  # 31/31
python -m poetry run axiom test-levels --mode simulate # 18/18
python -m poetry run axiom inventory-model             # inventory
```

The Python side communicates via named pipe and is completely version-agnostic. No Python changes are needed for Revit 2027.
