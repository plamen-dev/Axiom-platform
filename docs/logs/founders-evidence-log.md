# Founder's Evidence Log — Axiom-platform

Chronological record of development effort. Reconstructed from git history, PR ledgers, bug logs, and validation artifacts.

**Repo:** `plamen-hristov/Axiom-platform`
**Reconstruction date:** 2026-05-06
**Sources:** See `docs/logs/founders-evidence-source-index.md`

For detailed behavior history, see `docs/logs/behavior-change-ledger.md`.
For bug discovery and resolution, see `docs/logs/bug-validation-log.md`.
For PR-level review, see `docs/logs/pr-review-ledger.md`.

---

## Phase 1: Foundation (2025-12-13)

### EVID-001: Initial platform foundation

- **Date:** 2025-12-13
- **Workstream:** FOUNDATION
- **Work performed:** Created core schemas, input normalization, orchestrator agent, MCP layer, and CLI framework. Established Python project structure with Poetry, Click CLI, Pydantic models, and SQLAlchemy ORM.
- **Evidence source:** Commit `84799c0`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** Initial commit (direct to main)
- **Validation artifact:** N/A

---

## Phase 2: Persistence & Storage (2026-05-06)

### EVID-002: SQLite persistence with WAL mode

- **Date:** 2026-05-06
- **Workstream:** PERSISTENCE
- **Work performed:** Replaced in-memory storage with SQLite persistence using WAL mode for concurrent BIM data access. Applied black formatting to existing files.
- **Evidence source:** Commits `76cf496`, `282ff5e`; PR #1
- **Estimated hours:** TBD
- **Related PR/branch/commit:** [PR #1](https://github.com/plamen-hristov/Axiom-platform/pull/1) — merged `3423d58`
- **Validation artifact:** N/A

---

## Phase 3: Vertical Slice (2026-05-07 — 2026-05-19)

### EVID-003: Prompt-to-grid pipeline — core vertical slice

- **Date:** 2026-05-07
- **Workstream:** VERTICAL-SLICE
- **Work performed:** Implemented full prompt-to-grid pipeline including OrchestratorAgent, ExecutionAgent, PipeClient (Python↔C# named pipe bridge), AxiomPipeServer, GridCapability, GridCreationService, and general Axiom text prompt dialog.
- **Evidence source:** Commits `8efc206`, `8efa0e9`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** [PR #2](https://github.com/plamen-hristov/Axiom-platform/pull/2)
- **Validation artifact:** N/A

### EVID-004: Grid capability hardening — simulation, placement, parsing

- **Date:** 2026-05-08
- **Workstream:** CAPABILITY
- **Work performed:** Fixed simulate mode, GridCapability placement, plan status persistence. Added parsing for "every N feet", "N by M" grid dimensions, sentence-ending periods, abbreviations, "space evenly" patterns, and word-to-number dictionary.
- **Evidence source:** Commits `a91cc8b`, `35e86fb`, `6d302d7`, `53ada46`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** N/A

### EVID-005: Development process documentation

- **Date:** 2026-05-08
- **Workstream:** DOCS
- **Work performed:** Added development process documentation covering branching strategy, code review process, and deployment procedures.
- **Evidence source:** Commit `5464461`; [PR #3](https://github.com/plamen-hristov/Axiom-platform/pull/3)
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #3
- **Validation artifact:** N/A

### EVID-006: Devin Review response — grid orientation, validation

- **Date:** 2026-05-09
- **Workstream:** CAPABILITY
- **Work performed:** Addressed Devin Review findings on grid orientation, mock flag, and validation logic.
- **Evidence source:** Commit `bbc9b57`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** N/A

### EVID-007: Platform compatibility and pipe bridge fixes

- **Date:** 2026-05-10 — 2026-05-11
- **Workstream:** VERTICAL-SLICE
- **Work performed:** Fixed platform-specific test skips, detailed pipe error reporting, consolidated Revit solution into repo-owned `src/axiom_revit/`, fixed JSON property name mismatch between Python and C#, added pywin32 dependency, fixed vertical grid head direction, single-orientation prompt defaults, prompt-to-parameter mapping, Length parameter for line extent, user-friendly parameter names, A1 grid intersection anchor at origin.
- **Evidence source:** Commits `7097226`, `9224e4b`, `e532109`, `756fda3`, `ad822e8`, `4c6778b`, `36b618e`, `1ad49dd`, `44e0547`, `ab9b255`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** N/A

### EVID-008: Execution log and capability registry

- **Date:** 2026-05-11 — 2026-05-12
- **Workstream:** FOUNDATION
- **Work performed:** Added persistent JSONL execution log, capability registry metadata with SQLite telemetry persistence (Phase 1), replaced grid-specific dialog with general Axiom text prompt (Phase 2).
- **Evidence source:** Commits `18a033c`, `6b21bd3`, `7368e42`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** N/A

### EVID-009: Variable per-bay grid spacing

- **Date:** 2026-05-12
- **Workstream:** CAPABILITY
- **Work performed:** Added variable per-bay grid spacing support (Phase 3) — allows comma-separated and table-based spacing definitions.
- **Evidence source:** Commit `8efa572`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** N/A

### EVID-010: CreateGrids deterministic test harness

- **Date:** 2026-05-17
- **Workstream:** TESTING
- **Work performed:** Created CreateGrids deterministic test harness with layered storage, 31 YAML test cases. Added Capability Factory v1 checklist with CreateGrids mapping and CreateLevels plan. Fixed BUG-001 (clarification loop) and BUG-002 (mock count validation).
- **Evidence source:** Commits `503162b`, `37e25e2`, `782333a`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** `artifacts/grid_test_runs/`

### EVID-011: CreateLevels capability implementation

- **Date:** 2026-05-18
- **Workstream:** CAPABILITY
- **Work performed:** Implemented CreateLevels as Capability #2. Created CreateLevels capability plan, test fixtures (18 YAML cases), and checklist mapping. Level creation with FTF spacing, mock execution, and deterministic harness.
- **Evidence source:** Commits `270baf6`, `1ae38c6`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** `artifacts/level_test_runs/`

### EVID-012: InventoryModel read-only capability

- **Date:** 2026-05-18
- **Workstream:** CAPABILITY
- **Work performed:** Implemented InventoryModel read-only capability. Scans active Revit model for elements and parameters. Schema hardening, expanded tests, discovery infrastructure. Added inventory-summary CLI, generic parameter enumeration docs.
- **Evidence source:** Commits `2704183`, `2aae0d4`, `ddedee6`, `6a68432`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** `artifacts/model_inventory_runs/`

### EVID-013: Architecture documentation package

- **Date:** 2026-05-18 — 2026-05-19
- **Workstream:** DOCS
- **Work performed:** Revit multi-version build/test runbook, version compatibility metadata v1, multi-platform capability intelligence architecture, PR #2 consolidation (review ledger, bug log, merge checklist). Fixed double-dispatch in PromptCommand, pipe handle leak, level/grid resolution priority.
- **Evidence source:** Commits `05f34ea`, `83a919a`, `bd7861a`, `a87647a`, `b143502`, `f327469`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2 branch
- **Validation artifact:** N/A

### EVID-014: PR #2 merge — vertical slice complete

- **Date:** 2026-05-18 (merged 2026-05-19)
- **Workstream:** VERTICAL-SLICE
- **Work performed:** Merged PR #2 to main. Full prompt-to-grid pipeline with agents, pipe bridge, and C# capabilities. 84 files, +14,805 lines. 3 capabilities (CreateGrids, CreateLevels, InventoryModel), 31 grid test cases, 18 level test cases, 58 inventory tests.
- **Evidence source:** Merge commit `1c79cc7`; [PR #2](https://github.com/plamen-hristov/Axiom-platform/pull/2)
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #2
- **Validation artifact:** Grid/level/inventory test artifacts

---

## Phase 4: Revit 2027 Compatibility (2026-05-19 — 2026-05-24)

### EVID-015: Revit 2027 adapter — shared source, .NET 10

- **Date:** 2026-05-19
- **Workstream:** REVIT-COMPAT
- **Work performed:** Added Revit 2027 compatibility adapter using shared source with .NET 10 (net10.0-windows). Separate 2027 solution, .addin manifest, .csproj. RevitElementIdCompat helper for IntegerValue→Value migration (BUG-008). REVIEW.md for PR review agents.
- **Evidence source:** Commits `3a4c8dd`, `4c74669`, `4bb642c`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** [PR #5](https://github.com/plamen-hristov/Axiom-platform/pull/5), branch `revit-2027-compatibility`
- **Validation artifact:** N/A

### EVID-016: Revit 2027 deployment fixes

- **Date:** 2026-05-19
- **Workstream:** REVIT-COMPAT
- **Work performed:** Fixed .addin manifest absolute assembly path, Newtonsoft.Json.dll missing from deployment, addin path changed to Program Files, InventoryModel persistence/view restriction/dialog, System.Collections.Generic using, JSON export path display, CreateGrids clarification for arithmetic spacing.
- **Evidence source:** Commits `40e4f3d`, `ca117a7`, `e16f43e`, `1dab737`, `1f1206a`, `4cf8841`, `61af329`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-017: InventoryModel safety — crash prevention

- **Date:** 2026-05-19
- **Workstream:** SAFETY
- **Work performed:** Behavior History and Regression Evidence v1. Made InventoryModel safe/staged to prevent Revit crash (BUG-012). Full InventoryModel prompt disabled — crashes Revit 2027.
- **Evidence source:** Commits `9a4c5bf`, `16e9344`, `51837aa`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** `docs/logs/behavior-change-ledger.md` (on PR #5 branch)

### EVID-018: Inventory pipeline fixes

- **Date:** 2026-05-19
- **Workstream:** INVENTORY
- **Work performed:** UTF-8 BOM handling in Revit-exported JSON (inventory-import). inventory-summary supports summary-mode runs with 0 parameters.
- **Evidence source:** Commits `02d288f`, `2c56f3e`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-019: Review exports and discipline extraction

- **Date:** 2026-05-20
- **Workstream:** INVENTORY
- **Work performed:** Human-readable review exports (CSV, XLSX, Markdown) for scenario runs. Discipline-based extraction chunks. Empty-elements guardrail. Adaptive extraction planner.
- **Evidence source:** Commits `b78e391`, `c46f281`, `bf07c35`, `5969fc1`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-020: Safe chunked inventory and batched extraction

- **Date:** 2026-05-20 — 2026-05-21
- **Workstream:** INVENTORY
- **Work performed:** Safe chunked inventory (level, category+level, max threshold, plan prompt). Batched/continuation extraction with BatchSize for paginated processing. Validation run: 46/46 safe inventory modes passed. Whole-model batched extraction enabled with live Revit 2027 validation docs.
- **Evidence source:** Commits `c6a1de2`, `4206871`, `9ea389d`, `ccdf8be`, `b96767b`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** `artifacts/validation_runs/safe_inventory_modes/`

### EVID-021: Schema-centric inventory redesign

- **Date:** 2026-05-23
- **Workstream:** INVENTORY
- **Work performed:** Schema-centric inventory — separated schema discovery, value sampling, and full export. Blocked whole-model sample values (BUG-016, crashed Revit 2027). Split schema into object_schema and parameter_schema (BHV-015). Blocked whole-model parameter schema (BUG-017/BHV-016).
- **Evidence source:** Commits `b33f6ca`, `1b2a89d`, `f8968a0`, `ae51abc`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-022: Parameter discovery workflow

- **Date:** 2026-05-24
- **Workstream:** INVENTORY
- **Work performed:** Complete parameter discovery workflow — schema, import, summary, planner, registry. Parameter schema export with Object Category and param defs. Enriched parameter schema with Revit API metadata (DataTypeId, DataTypeLabel, GroupTypeId, GroupTypeLabel, IsMeasurableSpec, UnitTypeId, UnitLabel). Plan artifacts.
- **Evidence source:** Commits `90b7f74`, `1fe2a21`, `f260a17`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-023: Prompt traceability

- **Date:** 2026-05-24
- **Workstream:** INVENTORY
- **Work performed:** Added prompt traceability fields (raw_prompt, resolved_capability, result_class, source, active_view) to C# exports, JSON persistence, and Python import pipeline.
- **Evidence source:** Commit `c3d0749`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-024: Deploy script and Revit lock pre-check

- **Date:** 2026-05-24
- **Workstream:** REVIT-COMPAT
- **Work performed:** Revit.exe lock pre-check in deploy script. Warns about DLL file lock with PID display.
- **Evidence source:** Commit `839ca60`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-025: Full registry coverage workflow v1

- **Date:** 2026-05-24
- **Workstream:** INVENTORY
- **Work performed:** Object registry candidate from object_schema. Batch import support. Enhanced extraction planner with priority categories. Property registry builder with 8-tuple dedup. Coverage summary with missing category analysis.
- **Evidence source:** Commit `24067f0`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-026: Parameter schema plan execution queue

- **Date:** 2026-05-24
- **Workstream:** INVENTORY
- **Work performed:** C# plan executor reads parameter_schema_plan.json, executes category-by-category, writes manifest. Supports max N, priority only, resume variants. CLI manifest import. 11 new tests. Phase 4b complete.
- **Evidence source:** Commit `d16258f`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

### EVID-027: PR #5 hardening packet

- **Date:** 2026-05-24
- **Workstream:** SAFETY
- **Work performed:** Plan handoff path fix (BHV-019) — dual-write to repo + LocalAppData. Plan diagnostics command. Manifest hardening. Import-batch improvements. Registry coverage reporting with priority analysis. Deploy script polish (-ForceCloseRevit). REVIEW.md update. Docs/logs update. 7 new targeted tests. Total: 164 inventory tests, 373 full suite.
- **Evidence source:** Commit `2178f20`
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5 branch
- **Validation artifact:** N/A

---

## Phase 5: Infrastructure Tooling (2026-05-24)

### EVID-028: Axiom Local Runner v0

- **Date:** 2026-05-24
- **Workstream:** INFRA
- **Work performed:** Restricted local execution harness with 9 allowlisted actions (7 implemented, 2 placeholders). Workspace validation, timeout handling, artifact capture (run_log.json, stdout/stderr, failure_summary.md). CLI integration. 5 example task files. Runbook documentation. 22 tests passing.
- **Evidence source:** Commit `d450287`; [PR #6](https://github.com/plamen-hristov/Axiom-platform/pull/6)
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #6, branch `feature/axiom-local-runner-v0`
- **Validation artifact:** N/A

---

## Phase 6: Post-Merge Registry Milestone (2026-05-06)

### EVID-029: PR #5 merge — Revit 2027 compatibility

- **Date:** 2026-05-06
- **Workstream:** REVIT-COMPAT
- **Work performed:** Merged PR #5 to main. Revit 2027 .NET 10 compatibility, schema-centric inventory, adaptive planner, plan execution queue, structured dispatch, safety hardening. Live Revit 2027 validation: summary PASS, category PASS, object schema PASS, plan max 10 (10/10), plan priority only (16/16), full scan CONFIRMED CRASH (blocked). 373 pytest, 35/35 grids, 18/18 levels.
- **Evidence source:** Merge commit `c5df9df`; [PR #5](https://github.com/plamen-hristov/Axiom-platform/pull/5)
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #5
- **Validation artifact:** `docs/logs/pr-review-ledger.md` (PR #5 section)

### EVID-030: PR #6 merge — Local Runner v0

- **Date:** 2026-05-06
- **Workstream:** INFRA
- **Work performed:** Merged PR #6 to main. Restricted local execution harness, 9 allowlisted actions, workspace restriction, artifact capture. Command fix: `poetry run` instead of `python -m poetry run`. Live validation: git_status, test_grids, test_levels, ruff all PASS. 22/22 tests.
- **Evidence source:** Merge commit `45680ed`; [PR #6](https://github.com/plamen-hristov/Axiom-platform/pull/6)
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #6
- **Validation artifact:** `docs/runbooks/local-runner-runbook.md`

### EVID-031: PR #8 superseded — registry reporting (closed)

- **Date:** 2026-05-06
- **Workstream:** INVENTORY
- **Work performed:** PR #8 created to fix misleading registry coverage terminology. Before merge, export collision bug discovered. PR #9 created to fix both issues. PR #8 closed, branch deleted — all changes cherry-picked into PR #9.
- **Evidence source:** [PR #8](https://github.com/plamen-hristov/Axiom-platform/pull/8) (closed)
- **Estimated hours:** N/A (work subsumed by PR #9)
- **Related PR/branch/commit:** PR #8 → superseded by PR #9
- **Validation artifact:** N/A

### EVID-032: PR #9 merge — export path collision fix

- **Date:** 2026-05-06
- **Workstream:** INVENTORY
- **Work performed:** Fixed export path collision (BUG-018). Changed filename from `inv_YYYYMMDD_HHmmss.json` to `inv_YYYYMMDD_HHmmss_fff_NNN_category_slug.json` (milliseconds + atomic counter + slug). Added manifest duplicate detection. Included PR #8 registry reporting improvements. 402 pytest passing.
- **Evidence source:** Merge commit `0121777`; [PR #9](https://github.com/plamen-hristov/Axiom-platform/pull/9)
- **Estimated hours:** TBD
- **Related PR/branch/commit:** PR #9
- **Validation artifact:** N/A

### EVID-033: Registry milestone — full parameter schema coverage

- **Date:** 2026-05-06
- **Workstream:** INVENTORY
- **Work performed:** End-to-end parameter registry workflow validated on live Revit 2027 after all fixes merged.
- **Evidence source:** [PR #10](https://github.com/plamen-hristov/Axiom-platform/pull/10) (milestone documentation)
- **Estimated hours:** N/A (validation/documentation)
- **Related PR/branch/commit:** PR #10
- **Validation artifact:** `artifacts/parameter_registry_candidates/<run_id>/`

**Milestone results:**

| Metric | Value |
|--------|-------|
| Unique parameter/property definitions | 6,444 |
| Unique parameter names | 1,878 |
| Source runs | 1,748 |
| Source models | 5 (Snowdon Towers: Architectural, Electrical, HVAC, Plumbing, Structural) |
| Full plan categories executed | 278 successful, 1 skipped unsupported, 0 failed |
| Export path duplicates | 0 (was 252 before BUG-018 fix) |
| Priority categories executed | 20/20 |
| Priority categories with definitions | 20/20 |

**Safety status at milestone:**

| Command | Status |
|---------|--------|
| Run full InventoryModel | BLOCKED |
| Run InventoryModel sample values (whole-model) | BLOCKED |
| Run InventoryModel parameter schema (whole-model) | BLOCKED |
| Plan queue category_parameter_schema | ALLOWED (validated) |
| CreateGrids / CreateLevels | Unchanged |
| Revit 2024 baseline | Protected |

**Known next gaps:**
1. Broader model coverage — only Snowdon Towers validated; need non-Snowdon models
2. Family/library coverage — family-level and shared parameter definitions not yet scanned
3. Resume validation — `plan resume` mode not yet tested on large partial manifests

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total evidence entries | 33 |
| Date range | 2025-12-13 — 2026-05-06 |
| PRs created | 10 (#1–#10) |
| PRs merged to main | 6 (#1, #2, #5, #6, #9, #10) |
| PRs closed/superseded | 1 (#8, superseded by #9) |
| Capabilities implemented | 3 (CreateGrids, CreateLevels, InventoryModel) |
| Bugs documented | BUG-001 through BUG-018 |
| Behavior changes documented | BHV-001 through BHV-022 |
| Test count (full suite) | 402 |
| Safety blocks implemented | 3 (full inventory, sample values, parameter schema) |
| Revit versions supported | 2024 (baseline), 2027 (compatibility adapter) |
| Registry definitions | 6,444 unique (from 1,748 runs, 5 models) |
