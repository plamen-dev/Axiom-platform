# Naming Conventions

---

## File Naming

| Type | Convention | Example |
|------|-----------|---------|
| Documentation (Markdown) | kebab-case `.md` | `bug-validation-log.md` |
| Python source | snake_case `.py` | `pipe_client.py` |
| C# source | PascalCase `.cs` | `GridCapability.cs` |
| JSON contracts/schemas/fixtures | snake_case `.json` | `pipe_message_schema.json` |
| PowerShell scripts | kebab-case `.ps1` | `deploy-revit-2027.ps1` |
| Revit add-in manifest | matches the add-in DLL | `Axiom.RevitAddin.addin` |

## Code Naming

### Python

- Classes: `PascalCase` — `OrchestratorAgent`, `PipeClient`
- Functions/methods: `snake_case` — `resolve_prompt()`, `execute_tool()`
- Variables: `snake_case` — `h_count`, `pipe_name`
- Constants: `UPPER_SNAKE_CASE` — `_GRID_DEFAULTS`
- Modules: `snake_case` — `prompt_resolver.py`

### C#

- Classes/interfaces: `PascalCase` — `GridCapability`, `IAxiomCapability`
- Methods: `PascalCase` — `Execute()`, `CreateHorizontalGrids()`
- Properties: `PascalCase` — `HorizontalCount`, `SpacingFeet`
- Private fields: `_camelCase` — `_registry`, `_pipeName`
- Constants: `PascalCase` — `DefaultPipeName`
- Namespaces: `PascalCase` with dots — `Axiom.Core.Capabilities`

## Architecture Naming

| Term | Meaning | Layer |
|------|---------|-------|
| **Agent** | Orchestration class (Python) | Python |
| **Capability** | Executable unit implementing `IAxiomCapability` | C# (or Python) |
| **Service** | Existing implementation (kept as-is internally) | C# |
| **Bridge** | Named pipe communication layer | Both |

## Versioned Documents & Artifacts

- Architecture/design packets may carry a `-vN` suffix as they evolve, e.g.
  `discovery-harness-v1.md`, `revit-automation-bridge-v0.md`. Add a new version
  rather than overwriting the prior one.
- Run artifacts under `artifacts/` are timestamped/run-id folders (e.g.
  `model_inventory_runs/inv_YYYYMMDD_HHMMSS/`); the latest run is the newest id.
- The Revit baseline is tracked by tag, e.g. `baseline-001-revit-2024-capability-platform`.
