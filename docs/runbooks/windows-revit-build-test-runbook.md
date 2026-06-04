# Windows / Revit Build & Test Runbook

General entry point for building and testing Axiom on Windows. The C# Revit
solution is now **vendored in-repo** under `src/axiom_revit/` (no manual file
copying into an external solution).

For version-specific build/deploy detail, use the canonical runbooks:
- Revit 2027: `docs/runbooks/revit-2027-compatibility-runbook.md`
- Multi-version: `docs/runbooks/revit-multi-version-runbook.md`
- Self-hosted CI runner (Axiom-01): `docs/runbooks/windows-revit-self-hosted-runner.md`

The 2024 baseline (`baseline-001-revit-2024-capability-platform`) must be preserved
unless explicitly instructed otherwise.

---

## Prerequisites

- Windows 10/11
- Revit 2024 and/or Revit 2027 installed
- .NET: .NET Framework 4.8 (2024 build) and/or .NET 10 SDK + Desktop Runtime (2027 build)
- Visual Studio 2022 (optional — for IDE builds) or `dotnet` CLI
- Python 3.12+ with Poetry
- Git

---

## 1. Clone / Update the Repo

```cmd
git clone https://github.com/plamen-hristov/Axiom-platform.git
cd Axiom-platform
git checkout main
git pull
```

(Or check out the specific PR branch you are validating.)

---

## 2. Install Python Dependencies

```cmd
poetry install
```

---

## 3. Build the C# Revit Add-in

The solutions live in the repo:

| Target | Solution | Framework |
|--------|----------|-----------|
| Revit 2024 (baseline) | `src/axiom_revit/Axiom.Revit.sln` | `net48` |
| Revit 2027 | `src/axiom_revit/Axiom.Revit.2027.sln` | `net10.0-windows` |

### Revit 2027 (recommended path)

```powershell
# Build only (no copy to Addins folder)
.\scripts\deploy-revit-2027.ps1 -BuildOnly

# Build + deploy to C:\Program Files\Autodesk\Revit\Addins\2027
.\scripts\deploy-revit-2027.ps1
```

See `revit-2027-compatibility-runbook.md` for .NET 10 setup, the shared-source
layout, and the 2024-vs-2027 differences table.

### Revit 2024 (baseline)

Open `src/axiom_revit/Axiom.Revit.sln` in Visual Studio (Debug | x64) and build,
or build the baseline via the multi-version runbook. The shared-source pattern
means capability logic is not duplicated across versions.

---

## 4. Verify the .addin Manifest

The add-in is loaded by Revit from a version-specific Addins folder. The manifest
file is named `Axiom.RevitAddin.addin` in **both** the 2024 and 2027 deployments
(the `2027` lives in a separate per-version folder, so the filenames don't clash).

| Target | Repo source manifest | Deployed location |
|--------|----------------------|-------------------|
| Revit 2027 | `src/axiom_revit/Axiom.RevitAddin.2027.addin` | `C:\Program Files\Autodesk\Revit\Addins\2027\Axiom.RevitAddin.addin` |
| Revit 2024 | `src/axiom_revit/Axiom.RevitAddin.addin` | `%ProgramData%\Autodesk\Revit\Addins\2024\Axiom.RevitAddin.addin` |

Notes:
- For **2027**, `deploy-revit-2027.ps1` *generates* the manifest as
  `Axiom.RevitAddin.addin` at the target (pointing `<Assembly>` at the absolute
  `...\Addins\2027\Axiom.RevitAddin.dll`). Do **not** use `ProgramData` for 2027 —
  it deploys under `Program Files`.
- The deploy step copies these files into the `2027` folder:
  `Axiom.RevitAddin.addin`, `Axiom.RevitAddin.dll`, `Axiom.Core.dll`,
  `Newtonsoft.Json.dll`.
- The repo's `Axiom.RevitAddin.2027.addin` is the source reference; the deployed
  file is renamed to `Axiom.RevitAddin.addin` by the script.

---

## 5. Run a Simulate Command (No Revit Needed)

Simulate bypasses the named pipe entirely, so it works without Revit running:

```cmd
poetry run axiom prompt "Create 10 vertical gridlines, 50 ft long, spaced 10 ft apart" --simulate
```

Expect `SIMULATION SUCCESS` with resolved grid parameters and telemetry events.
If it FAILS, check `src/axiom_core/pipe_client.py` — the simulate path must not
touch the pipe.

---

## 6. Run a Live Pipe Command (Revit Required)

1. Open Revit and load a project (be in a plan view — not 3D/drafting/legend/schedule).
2. Confirm the **Axiom** tab appears in the ribbon (add-in loaded).
3. From a terminal:

```cmd
poetry run axiom prompt "Create 10 vertical gridlines, 50 ft long, spaced 10 ft apart"
```

Expect `EXECUTION SUCCESS` with grids created in the model. If it FAILS, check the
Revit Output window for `[AxiomPipeServer]` messages and verify you are in a plan
view with no conflicting grid names.

---

## 7. Run the Python Tests

```cmd
poetry run pytest
poetry run ruff check .
```

Run the full suite at PR checkpoints; for small changes prefer targeted module
tests (see the testing/capacity policy). Report tests run, tests skipped, and the
reason skipped.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `SIMULATION FAILED` on Windows | Stale checkout | Pull latest `main` (or the PR branch) |
| `ModuleNotFoundError: win32file` | pywin32 not installed | `pip install pywin32` (only needed for the live pipe, not simulate) |
| C# build error: missing `RevitAPI` | Revit not installed / wrong version path | Install the target Revit version; the .2027 project resolves `C:\Program Files\Autodesk\Revit 2027\` |
| 2027 build fails: wrong SDK | .NET 10 SDK missing | `winget install Microsoft.DotNet.SDK.10` |
| Deploy can't copy DLL | Revit holding the DLL | Close Revit, or use `-ForceCloseRevit`, or `-BuildOnly` |
| Pipe timeout | Revit busy in a command/dialog | Ensure Revit is idle, then retry |
| "No active Revit document" | No project open | Open a Revit project before running |
