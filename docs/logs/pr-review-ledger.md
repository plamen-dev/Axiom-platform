# PR Review Ledger

## PR #2: Vertical Slice — Prompt-to-Grid Pipeline with Agents, Pipe Bridge, and C# Capabilities

**Branch:** `devin/1778113509-vertical-slice`
**Base:** `main`
**Status:** Merge-ready (pending real Revit validation)
**Scope:** 84 files changed, +14,805 lines

---

### Feature Summary

| # | Feature | Key Files | Tests |
|---|---------|-----------|-------|
| 1 | **CreateGrids end-to-end** | `prompt_resolver.py`, `pipe_client.py`, `GridCapability.cs`, `GridCreationService.cs`, `GridParameters.cs` | 31/31 harness, 30+ pytest |
| 2 | **Variable grid spacing** | `prompt_resolver.py` (comma/table parsing), `GridParameters.cs` (`HorizontalSpacingsFeet`, `VerticalSpacingsFeet`) | 6 harness cases |
| 3 | **Clarification loop** | `_check_grid_clarification()`, `PromptDispatcher.CheckGridClarification()` | 7 pytest, 4 harness |
| 4 | **General Revit Prompt dialog** | `PromptCommand.cs` (text input, replaces grid-specific dialog) | Manual Revit test pending |
| 5 | **CreateLevels capability** | `LevelCapability.cs`, `LevelCreationService.cs`, `LevelParameters.cs`, resolver + mock | 18/18 harness, 26 pytest |
| 6 | **InventoryModel capability** | `InventoryModelCapability.cs`, `ModelInventoryService.cs`, `InventoryParameters.cs`, storage, reviewer | 58 pytest |
| 7 | **inventory-summary utility** | `src/axiom_core/inventory/review.py`, CLI `inventory-summary` command | 14 pytest |
| 8 | **Grid learning loop harness** | `src/axiom_core/testing/grid_harness.py`, `axiom test-grids` CLI | 31 test cases |
| 9 | **Level learning loop harness** | `src/axiom_core/testing/level_harness.py`, `axiom test-levels` CLI | 18 test cases |
| 10 | **Revit version compatibility metadata** | `supported_revit_versions.yaml`, `capability_compatibility.yaml`, `parameter_availability_examples.yaml` | Fixtures only |
| 11 | **Multi-platform architecture proposal** | `multi-platform-capability-intelligence.md` | Docs only |

### Infrastructure

| Component | Detail |
|-----------|--------|
| Capability registry | 3 capabilities: CreateGrids (validated), CreateLevels (validated), InventoryModel (validated) |
| Storage layers | JSONL (append-only), SQLite (queryable, WAL mode), Parquet (structured datasets) |
| CLI commands | `axiom prompt`, `axiom test-grids`, `axiom test-levels`, `axiom inventory-model`, `axiom inventory-summary` |
| C# solution | `Axiom.Core` + `Axiom.RevitAddin` targeting Revit 2024 (net48) |
| Pipe bridge | Named pipe (JSON protocol) for Python↔C# communication |

### Architecture Docs Added

| Document | Purpose |
|----------|---------|
| `capability-creation-checklist.md` | 13-step repeatable process for adding capabilities |
| `capability-design-pattern.md` | Template every capability follows |
| `create-levels-capability-plan.md` | CreateLevels pre-implementation plan |
| `revit-version-compatibility-strategy.md` | Shared capability + thin adapter approach for 2024–2027 |
| `revit-parameter-versioning-strategy.md` | One canonical ParameterAvailability registry |
| `multi-platform-capability-intelligence.md` | Platform vision: 9 concepts, Revit as Adapter 001 |
| `revit-multi-version-runbook.md` | Build/test procedures for multiple Revit versions |
| `model-inventory-runbook.md` | InventoryModel usage, schema reference, query examples |
| `grid-learning-loop-runbook.md` | Grid harness usage and regression workflow |

### Commit History (30 commits)

Earliest to latest:

1. Grid orientation fixes and prompt parsing improvements
2. Word-to-number dictionary, abbreviation support
3. Pipe bridge error handling, platform-specific test fixes
4. Revit solution consolidation into `src/axiom_revit/`
5. Capability registry + SQLite telemetry (Phase 1)
6. General Revit Prompt dialog (Phase 2)
7. Variable per-bay grid spacing (Phase 3)
8. Grid deterministic test harness + layered storage
9. Capability Factory v1 checklist
10. BUG-001 clarification loop + BUG-002 mock validation fix
11. CreateLevels capability plan (docs only)
12. CreateLevels implementation (Capability #2)
13. InventoryModel implementation (read-only)
14. Revit multi-version runbook (2024/2027)
15. InventoryModel schema hardening + expanded tests
16. Generic enumeration documentation
17. inventory-summary CLI utility
18. Revit version compatibility metadata v1
19. Multi-platform capability intelligence architecture

### Test Results

| Suite | Count | Status |
|-------|-------|--------|
| pytest | 192 | All passing |
| test-grids (simulate) | 31/31 | All passing |
| test-levels (simulate) | 18/18 | All passing |
| ruff lint | 0 errors | Clean |

---

## PR #1: SQLite Persistence (WAL Mode)

**Status:** Merged
**Scope:** Replace in-memory storage with SQLite persistence layer
