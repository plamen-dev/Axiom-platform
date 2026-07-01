---
name: revit-adapter
description: Operate and verify the Revit product adapter (Adapter 001) — the C# add-in, named-pipe automation bridge, capability execution against Revit (CreateGrids, CreateLevels, InventoryModel, SetParameterValue), and version deployment. Use when building, deploying, or live-validating Revit-facing changes.
---

# Revit adapter (Adapter 001)

**status: scaffold** — populate sections the first time verified operational knowledge exists for this domain (same PR as the change; see `.agents/skills/README.md`).

## Domain

Revit is Adapter 001, not the end state. Current baseline: `baseline-001-revit-2024-capability-platform`. Bridge: Python ↔ C# named pipe (`src/axiom_core/automation_bridge.py`, `pipe_client.py`).

## Commands

_(to be populated — build/deploy commands verified on the operator machine)_

## Registry pointers

- Current Revit capabilities: CreateGrids, CreateLevels, InventoryModel, SetParameterValue (capability registry is the source of truth).

## Verification checklists

For live Revit PRs (per repo policy):
- preview must be tested before apply;
- apply must be tested on a disposable/sample model first;
- evidence artifacts must be inspected;
- failure becomes a bug/evidence entry, not just a chat note.

## Tests

C# changes: prefer `dotnet build` / deploy build validation for the affected Revit solution; do not run full Python pytest unless Python files changed.

## Notes / gotchas

- Revit 2027 compatibility stays isolated in its own branch/PR; uses Program Files add-in deployment (`C:\Program Files\Autodesk\Revit\Addins\2027`) with the manifest pointing at the DLL there; do not rely on ProgramData. Revit 2027 `ElementId` uses `Value` instead of `IntegerValue` — use compatibility helpers, not scattered version conditionals.
- Live validation runs on the operator machine (AXIOM-01); Devin's Ubuntu box cannot run Revit.
