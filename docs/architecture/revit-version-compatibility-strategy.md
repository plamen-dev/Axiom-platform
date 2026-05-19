# Revit Version Compatibility Strategy

## Overview

Axiom supports multiple Revit versions through **one shared capability system** with
**thin Revit-version adapters** where runtime or API differences require it.

The goal is to avoid maintaining four manually duplicated codebases. Instead:

- One shared Python orchestration layer (resolver, registry, CLI, telemetry)
- One shared capability registry with version-aware metadata
- Thin C# build projects per Revit version where the .NET runtime differs
- Version metadata fixtures that track compatibility status per capability

---

## Concepts

### SupportedRevitVersion

A Revit release that Axiom explicitly targets or plans to target.

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Revit year (e.g. `"2024"`, `"2027"`) |
| `runtime_family` | string | .NET runtime generation (see below) |
| `target_framework` | string | MSBuild TFM (e.g. `net48`, `net10.0-windows`) |
| `api_dll_path` | string | Expected path to `RevitAPI.dll` |
| `addin_folder` | string | Revit add-in manifest folder |
| `status` | string | Overall support status |
| `notes` | string | Free-form context |

### RuntimeFamily

Groups Revit versions by their .NET runtime generation. This determines whether
shared C# source code can be compiled against the same target framework or
requires a separate build project.

| RuntimeFamily | .NET Runtime | Revit Versions | Build Strategy |
|---------------|-------------|----------------|----------------|
| `net48` | .NET Framework 4.8 | 2024 | Legacy .csproj (current baseline) |
| `net8` | .NET 8 | 2025, 2026 | SDK-style .csproj, shared source |
| `net10` | .NET 10 | 2027 | SDK-style .csproj, shared source |

Capabilities share source code across runtime families. Only the build project
files (`.csproj`) and framework targeting differ.

### CapabilityCompatibility

Tracks the validation status of each capability per Revit version.

| Field | Type | Description |
|-------|------|-------------|
| `capability` | string | Capability name (e.g. `CreateGrids`) |
| `revit_version` | string | Revit year |
| `status` | string | Validation status (see below) |
| `last_tested` | string | ISO date of last validation |
| `tested_by` | string | Who performed validation |
| `notes` | string | Free-form context |

### VersionValidationStatus

Ordered validation stages for a capability against a Revit version:

| Status | Meaning |
|--------|---------|
| `planned` | Support intended but no work started |
| `simulated` | Python simulation passes (no Revit required) |
| `build_validated` | C# compiles against this Revit version's API DLLs |
| `startup_validated` | Add-in loads in Revit without errors |
| `real_validated` | Capability executes correctly in Revit with real model |
| `failed` | Attempted validation failed — see notes for details |
| `deprecated` | No longer targeting this Revit version |

Progression is always forward: `planned` → `simulated` → `build_validated` →
`startup_validated` → `real_validated`. A capability may be at different stages
for different Revit versions.

---

## Architecture Layers

### Layer 1: Python Orchestration (Version-Agnostic)

These components are completely independent of Revit version:

| Component | Location | Version Dependency |
|-----------|----------|-------------------|
| Capability registry | `src/axiom_core/capability_registry.py` | None |
| Prompt resolver | `src/axiom_core/prompt_resolver.py` | None |
| Mock/simulation execution | `src/axiom_core/pipe_client.py` | None |
| CLI commands | `src/axiom_cli/main.py` | None |
| Telemetry/logging | `src/axiom_core/execution_log.py` | None |
| Test harnesses | `src/axiom_core/testing/` | None |
| Storage (JSONL/SQLite/Parquet) | `src/axiom_core/inventory/` | None |

Python never interacts with `RevitAPI.dll` directly. It communicates with C#
through the named pipe bridge, which is protocol-based (JSON messages). The pipe
protocol is version-agnostic.

### Layer 2: C# Shared Source (Version-Neutral Logic)

Capability logic lives in shared `.cs` files that compile against any supported
Revit API version:

| Component | Location |
|-----------|----------|
| Parameter models | `Axiom.Core/Models/*.cs` |
| Capability classes | `Axiom.RevitAddin/Capabilities/*.cs` |
| Service implementations | `Axiom.RevitAddin/Services/*.cs` |
| Prompt dispatcher | `Axiom.RevitAddin/PromptDispatcher.cs` |
| Pipe bridge | `Axiom.RevitAddin/PipeBridge.cs` |

These files use standard Revit API types (`Document`, `Element`, `Parameter`,
`FilteredElementCollector`, `Grid.Create`, `Level.Create`, etc.) that are
expected to remain stable across Revit versions. If a specific API breaks in a
new version, the fix belongs in a version-specific adapter — not in the shared
source.

### Layer 3: Thin Version Adapters (Build Projects)

Each Revit version that requires a different .NET runtime gets its own set of
build project files. These projects reference the **same shared source files** —
only the build configuration and framework targeting differ.

**Current state (Revit 2024 baseline):**

```
src/axiom_revit/
├── Axiom.Core/
│   └── Axiom.Core.csproj              ← net48, legacy format
├── Axiom.RevitAddin/
│   └── Axiom.RevitAddin.csproj        ← net48, legacy format
└── Axiom.Revit.sln
```

**Planned state (when Revit 2027 is validated):**

```
src/axiom_revit/
├── Axiom.Core/
│   ├── Axiom.Core.csproj              ← 2024 (net48)
│   └── Axiom.Core.2027.csproj         ← 2027 (net10.0-windows, SDK-style)
├── Axiom.RevitAddin/
│   ├── Axiom.RevitAddin.csproj        ← 2024 (net48)
│   └── Axiom.RevitAddin.2027.csproj   ← 2027 (net10.0-windows, SDK-style)
├── Axiom.Revit.sln                    ← 2024 solution
└── Axiom.Revit.2027.sln              ← 2027 solution
```

The 2027 `.csproj` files use `<Compile Include="..." />` or
`<Link>` references to include the same `.cs` source files as the 2024 projects.
No source duplication.

### Layer 4: Version-Specific API Adapters (Future, If Needed)

If a Revit API change breaks a specific capability in a new version, the fix
goes into a small adapter file — not into the shared capability source.

Example (hypothetical):

```
src/axiom_revit/Axiom.RevitAddin/Adapters/
├── GridCreationAdapter2024.cs    ← Grid.Create(doc, line) signature
└── GridCreationAdapter2027.cs    ← Grid.Create(doc, line, view) if changed
```

**Do not create adapters preemptively.** Only add them when a real API
incompatibility is discovered through build or runtime validation.

---

## Version Support Policy

### Baseline

Revit 2024 is the current baseline and production target. All capabilities must
pass `real_validated` against 2024 before any other version is pursued.

### .NET 8 Generation (Revit 2025/2026)

- Same API surface as 2024 with minor additions
- Requires SDK-style `.csproj` targeting `net8.0-windows`
- Treated as the next natural upgrade path
- Status: `planned` — no local install available yet

### .NET 10 Generation (Revit 2027)

- Major runtime jump from .NET Framework 4.8 to .NET 10
- May introduce add-in isolation, assembly loading changes, namespace changes
- Status: `planned` — pending local install validation
- See `docs/runbooks/revit-multi-version-runbook.md` for build strategy

### Version Retirement

When a Revit version reaches end-of-support from Autodesk, its status moves to
`deprecated`. Deprecated versions are not actively tested but build projects are
kept for reference.

---

## Validation Workflow

For each new Revit version, follow this validation sequence:

```
1. Python tests + harness simulation     → simulated
2. C# build against version API DLLs     → build_validated
3. Add-in loads in Revit (no execution)  → startup_validated
4. Smoke test each capability            → real_validated
5. InventoryModel scan (captures params) → confirms API surface
6. Update compatibility metadata         → version fixtures updated
```

### InventoryModel as Compatibility Probe

`InventoryModel` plays a special role in version validation. Because it
enumerates all elements and parameters via generic enumeration
(`elem.Parameters`), its output reveals whether:

- Parameter names/types changed between versions
- New built-in parameters were added
- Element categories changed
- Type hierarchies were restructured

After running InventoryModel on the same test model in two Revit versions, the
Parquet outputs can be diffed to identify API surface changes.

---

## Metadata Fixtures

Version compatibility metadata is stored as YAML fixtures for testability and
readability:

| Fixture | Location | Purpose |
|---------|----------|---------|
| Supported versions | `tests/fixtures/compatibility/supported_revit_versions.yaml` | SupportedRevitVersion definitions |
| Capability status | `tests/fixtures/compatibility/capability_compatibility.yaml` | Per-capability, per-version status |
| Parameter availability | `tests/fixtures/compatibility/parameter_availability_examples.yaml` | Known version-specific parameter differences |

These fixtures are not runtime dependencies. They are reference data for:

- Documentation (what is supported and at what stage)
- Test assertions (verify compatibility metadata is consistent)
- Future automation (version-aware build/test matrix)

---

## Anti-Patterns

1. **Do NOT fork capability source per version.** Shared `.cs` files compile
   against all supported versions. Only build config differs.
2. **Do NOT create version-specific Python code.** Python is completely
   version-agnostic — it communicates via the pipe protocol.
3. **Do NOT assume API compatibility.** Every new version must go through the
   full validation sequence before its status advances.
4. **Do NOT preemptively create adapters.** Only add adapters when a real API
   break is discovered and validated.
5. **Do NOT maintain separate parameter models per version** (see parameter
   versioning strategy).

---

## Related Documents

- [Multi-Platform Capability Intelligence](multi-platform-capability-intelligence.md) — this document is the Revit-specific instantiation of the VersionCompatibilityRegistry concept
- [Revit Multi-Version Build & Test Runbook](../runbooks/revit-multi-version-runbook.md)
- [Revit Parameter Versioning Strategy](revit-parameter-versioning-strategy.md)
- [Capability Creation Checklist](capability-creation-checklist.md)
