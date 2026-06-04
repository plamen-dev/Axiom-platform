# Current Axiom File Set

Maps the codebase across the Python repo and the vendored C# Revit solution.
Reflects the current tree (post Evidence Runner / Command Registry / Validation
Registry / Discovery Harness work). Regenerate when the package layout changes.

---

## Python Repo: `Axiom-platform`

GitHub: `plamen-hristov/Axiom-platform`

```
Axiom-platform/
├── src/
│   ├── axiom_core/                       # Core logic (Revit-agnostic where possible)
│   │   ├── schemas.py                    # Pydantic models: Job, Plan, ToolStep, ToolResult, QAReport
│   │   ├── orchestrator.py               # Plan generation and execution engine
│   │   ├── mcp_layer.py                  # Mock MCP layer (Revit tool simulation)
│   │   ├── persistence.py                # SQLite-backed Storage class
│   │   ├── database.py                   # SQLAlchemy engine, session, WAL mode
│   │   ├── models.py                     # SQLAlchemy ORM models (incl. discovery registries)
│   │   ├── input_normalization.py        # Excel → NormalizedJob
│   │   ├── pipe_client.py                # Named-pipe client (Python → C# bridge)
│   │   ├── prompt_resolver.py            # Prompt → capability parameters
│   │   ├── word_numbers.py               # Spelled-number parsing helper
│   │   ├── execution_log.py              # Execution logging
│   │   ├── capability_registry.py        # Capability metadata registry
│   │   ├── set_parameter_value.py        # SetParameterValue v0 core (preview/apply, evidence)
│   │   ├── automation_bridge.py          # External driver over the named-pipe bridge (PR #19)
│   │   ├── validation_loop.py            # Validation Automation Loop v0 orchestrator (PR #16)
│   │   ├── agents/                       # Coordination only (agents route; capabilities execute)
│   │   │   ├── orchestrator_agent.py
│   │   │   ├── execution_agent.py
│   │   │   ├── telemetry_agent.py
│   │   │   ├── geometry_agent.py         # Stub
│   │   │   └── knowledge_agent.py        # Stub
│   │   ├── inventory/                    # InventoryModel pipeline (Discovery foundation)
│   │   │   ├── storage.py                # Enriched parameter export schema + stable join (PR #21)
│   │   │   ├── extraction_planner.py     # Category/parameter scan planning
│   │   │   ├── report.py / review.py     # Inventory reporting + review export
│   │   │   ├── discipline.py / discipline_export.py
│   │   │   └── discipline_mapping.json
│   │   ├── discovery/                    # Discovery Harness v1 (PR #20) — read-only interpreter
│   │   │   ├── harness.py                # Orchestrator + simulate/live export loaders
│   │   │   ├── interpret.py              # Pure interpreter: export → categories/params/candidates
│   │   │   ├── registries.py             # Optional SQLite persistence (reuses PR #1 stack)
│   │   │   └── reports.py                # summary/categories/parameters/candidate reports
│   │   ├── runner/                       # Command governance (PR #22)
│   │   │   └── command_registry.py       # CommandRegistry, AllowedCommand, ExecutionContext, …
│   │   ├── validation/                   # Validation governance + evidence (PR #24, #25)
│   │   │   ├── validation_registry.py    # CapabilityValidationRegistry + seed procedures
│   │   │   ├── persistence.py            # SQLite persistence for validation definitions
│   │   │   └── evidence_runner.py        # EvidenceRunner — durable evidence bundles (PR #25)
│   │   └── testing/                      # Test-case loading/running/reporting harness
│   │       ├── loader.py / models.py / runner.py / report.py / storage.py
│   ├── axiom_cli/
│   │   └── main.py                       # Click CLI — all axiom commands (see command registry)
│   └── axiom_revit/                      # Vendored C# Revit solution (see below)
├── contracts/
│   └── pipe_message_schema.json          # JSON-RPC 2.0 message format (Python ↔ C#)
├── tests/                                # pytest suite + fixtures/
│   ├── test_*.py                         # per-module tests (discovery, validation, command
│   │                                     #   registry, evidence runner, inventory, bridge, …)
│   └── fixtures/                         # behavior_regressions/, compatibility/, *_test_cases/
├── tools/
│   ├── local_runner/                     # Restricted local execution harness (allowlist) + examples
│   └── sample_data/sample_registry.jsonl
├── scripts/
│   ├── deploy-revit-2027.ps1
│   └── local/                            # run-validation-loop.ps1, setup-github-runner-notes.ps1
├── .github/workflows/
│   ├── python-ci.yml                     # Python-only CI (pytest + ruff)
│   └── windows-revit-validation.yml      # Self-hosted Axiom-01 runner (workflow_dispatch)
├── .agents/skills/                       # Reusable Devin skills (e.g. testing-axiom-cli)
├── docs/                                 # architecture/, logs/, runbooks/
├── artifacts/                            # Evidence + run outputs (mostly gitignored)
├── README.md  REVIEW.md
└── pyproject.toml  poetry.lock           # Poetry config, CLI entrypoints
```

---

## C# Revit Solution (vendored under `src/axiom_revit/`)

Now lives in-repo (no longer an external `C:\Dev\Axiom` path). Shared-source
pattern: the 2027 projects link the same sources as the 2024 baseline projects and
build for `net10.0-windows`, preserving the 2024 baseline.

```
src/axiom_revit/
├── Axiom.Revit.sln                       # 2024 baseline solution (net48)
├── Axiom.Revit.2027.sln                  # Revit 2027 solution (net10.0-windows)
├── Axiom.RevitAddin.addin                # 2024 manifest (relative Assembly: Axiom.RevitAddin.dll)
├── Axiom.RevitAddin.2027.addin           # 2027 source manifest (Assembly → Program Files\…\Addins\2027\Axiom.RevitAddin.dll)
├── Axiom.Core/                           # Revit-agnostic contracts + bridge
│   ├── Capabilities/                     # IAxiomCapability.cs, CapabilityResult.cs
│   ├── Bridge/                           # AxiomPipeServer.cs, PipeMessage.cs,
│   │                                     #   ToolRegistry.cs, PromptDispatcher.cs
│   ├── Compat/RevitElementIdCompat.cs    # ElementId.Value vs IntegerValue (2027 vs 2024)
│   ├── Models/                           # GridParameters, LevelParameters,
│   │                                     #   InventoryParameters, SetParameterValueParameters
│   └── Properties/AssemblyInfo.cs
├── Axiom.Core.2027/                      # Shared-source 2027 build of Axiom.Core
├── Axiom.RevitAddin/                     # Revit-dependent commands, services, capabilities
│   ├── App.cs                            # IExternalApplication: ribbon + pipe server start
│   ├── GridsCommands.cs                  # Button-based grid command(s)
│   ├── PromptCommand.cs                  # Prompt dialog → PromptDispatcher
│   ├── Capabilities/                     # GridCapability, LevelCapability,
│   │                                     #   InventoryModelCapability, SetParameterValueCapability
│   ├── Services/                         # GridCreationService, LevelCreationService,
│   │                                     #   ModelInventoryService, ParameterEditService
│   ├── UI/                               # AxiomPromptDialog.cs, GridPromptDialog.cs
│   ├── Logging/ExecutionLogStub.cs
│   └── Properties/AssemblyInfo.cs
└── Axiom.RevitAddin.2027/                # Shared-source 2027 build of the add-in
```

**Key rules:**
- Capability impls (e.g. `GridCapability.cs`) live in `Axiom.RevitAddin` (not
  `Axiom.Core`) because they depend on the Revit `*Service` classes. `Axiom.Core`
  holds only shared contracts + bridge infrastructure.
- Do not duplicate capability logic across Revit versions — prefer shared source
  with thin version-specific build/deploy adapters. The 2024 baseline
  (`baseline-001-revit-2024-capability-platform`) must be preserved unless
  explicitly instructed otherwise.

---

## Project References

- `Axiom.RevitAddin` → references `Axiom.Core` (project reference); the `.2027`
  projects mirror this with shared sources.
- Both reference `RevitAPI.dll` / `RevitAPIUI.dll` (Copy Local: False).
- `Axiom.Core` references `Newtonsoft.Json` (NuGet).
