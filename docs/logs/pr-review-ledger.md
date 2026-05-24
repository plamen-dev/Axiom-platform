# PR Review Ledger

## PR #5: Revit 2027 Compatibility — Discipline Extraction, Safety Guards, Chunked Inventory

**Branch:** `revit-2027-compatibility`
**Base:** `main`
**Status:** Merge-ready (live Revit 2027 validation passed)
**Scope:** Revit 2027 compatibility, schema-centric inventory, adaptive planner, safety hardening, full registry coverage workflow

---

### Key Changes

1. **Full InventoryModel blocked** (BUG-014): Crashes Revit 2027 on large models (~43K instances). Returns `clarification_needed` with safe workflow guidance. Blocked at both Python (prompt_resolver) and C# (PromptDispatcher) layers.

2. **Schema-centric inventory redesign** (BHV-013, BUG-015):
   - `Run InventoryModel schema` — whole-model parameter definitions, no values
   - `Run InventoryModel schema batch 500` — schema in bounded batches
   - `Run InventoryModel sample values` — limited value samples (10 per param)
   - `Run InventoryModel for Walls schema` — category schema only
   - `Run InventoryModel for Walls sample values` — category value samples
   - `Run InventoryModel batch 100` — now resolves to SCHEMA discovery (not full values)
   - `Run InventoryModel full values` — BLOCKED

3. **Safe chunked extraction modes** (BHV-011, BHV-012):
   - `Run InventoryModel for Walls` — category value scan
   - `Run InventoryModel on Level 1` — level scan
   - `Run InventoryModel for Walls on Level 1` — category+level scan
   - `inventory plan` / `extraction plan` — guides to CLI planner

4. **Adaptive extraction planner**: `axiom inventory-plan --file <summary.json>` builds extraction plan from summary counts. Now recommends schema discovery first, then category scans. Never recommends full value extraction.

5. **Batched/continuation extraction** (BHV-012): `limit`/`max`/`batch` sets `BatchSize` for paginated continuation. Each batch saved independently. CLI `inventory-combine` merges batch outputs.

5. **Discipline-based extraction**: `axiom inventory-export --chunk-by discipline` classifies elements by Architectural/Structural/Mechanical/Electrical/Plumbing/Other.

6. **Empty-elements guardrail**: Warning in console, summary markdown, and metadata when discipline split runs on summary-only JSON.

7. **Parameter discovery workflow (BHV-016, BUG-017)**: Complete safe parameter intelligence path: category parameter schema extraction, `inventory-import`/`inventory-summary` support for `parameter_schema.parquet`, `inventory-plan --mode parameter-schema` for copy-paste ready category commands, `parameter-registry-build` for deduplicating across multiple runs. Added Lighting Fixtures, Views, Sheets, Ducts, Pipes to known categories.

### Test Coverage

- 166 inventory tests + 207 other = 373 total pytest passing
- 35/35 grid scenarios, 18/18 level scenarios
- 46/46 validation run (prompt resolution, all modes)
- ruff clean

### Live Revit 2027 Validation

**Phase 1 (2026-05-21):**

| Mode | Result | Details |
|------|--------|---------|
| Summary | PASS | 42,881 instances, 2,276 types, 0 errors, 61ms |
| Category — Ceilings | PASS | 78 instances, 7 types, 1,599 parameters, 0 errors |
| Category — Plumbing Fixtures | PASS | 150 instances, 31 types, 4,119 parameters, 0 errors |
| inventory-import | PASS | Both category exports imported |
| inventory-summary | PASS | Summary works after import |
| Full scan | CRASH | Revit 2027 crashed (remains blocked) |
| Whole-model batch 100 | CRASH | Value extraction too expensive (BUG-015) |
| Object schema | PASS | 16MB JSON, 45,157 elements |
| Whole-model sample values | CRASH | Now blocked (BUG-016) |
| Parameter schema (whole-model) | CRASH | Now blocked (BUG-017) |
| Deployment | PASS | deploy-revit-2027.ps1 succeeded |

**Phase 2 (2026-05-23):**

| Mode | Result | Details |
|------|--------|---------|
| Walls parameter schema | PASS | 1,241 instances, 85 types, 104 parameter definitions |
| Plan execution max 10 | PASS | 10/10 categories completed, 0 failed, Revit stable |
| Plan execution priority only | PASS | 16/16 categories completed, 0 failed, Revit stable |
| inventory-import-batch | PASS | Manifest import worked |
| parameter-registry-build | PASS | 1,030 unique definitions, 21 source runs |
| Deploy script syntax fix | PASS | PowerShell parse clean |
| Structured dispatch | PASS | All categories dispatch correctly (no BLOCKED_UNSAFE) |

### Architecture Flag

Level filter is **post-collector / pre-extraction**: C# iterates all elements, skips non-matching levels before expensive parameter extraction. Recommendation: optimize with `ElementLevelFilter` for true pre-collector filtering in future.

### Remaining Validation

- [x] Summary mode on real model — PASS
- [x] Category scan on real model — PASS (Ceilings, Plumbing Fixtures)
- [x] Deployment — PASS
- [x] Full scan confirmed crash — remains blocked
- [x] Object schema on real model — PASS
- [x] Whole-model sample values — CRASH (now blocked)
- [x] Parameter schema on real model — CRASH (now blocked)
- [x] Category parameter schema — PASS (Walls: 104 param defs)
- [x] Plan execution queue max 10 — PASS (10/10)
- [x] Plan execution queue priority only — PASS (16/16)
- [x] inventory-import-batch --manifest — PASS
- [x] parameter-registry-build with object registry — PASS
- [x] Deploy script syntax fix — PASS
- [ ] Level scan on real model
- [ ] Category+level scan on real model
- [ ] Constrained sample values
- [ ] Level filter performance profiling

### Progressive Coverage Validation Roadmap

The queue mechanism is validated, but full-model coverage is not yet validated. Only capped and priority plan execution have been validated so far. Direct full-model extraction remains blocked.

**Next steps (progressive validation):**

1. `Run InventoryModel parameter schema plan max 50` — expand coverage boundary
2. `Run InventoryModel parameter schema plan max 100` — stress test with larger batch
3. `Run InventoryModel parameter schema plan resume` — validate resume on partially completed manifest
4. `Run InventoryModel parameter schema plan` (full) — only if steps 1-3 are stable

Do not skip directly to full plan. Each step validates Revit stability at increasing scale before proceeding.

---

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

### Hardening Packet (Phase 4b+)

**Date:** 2026-05-06
**Focus:** Reliability, path handoff, docs, diagnostics, merge-readiness

Changes:
1. **Plan handoff path fix (BHV-019):** `inventory-plan` now writes plan JSON to both repo artifacts AND `%LOCALAPPDATA%\Axiom\inventory_plans\latest\` for Revit pickup.
2. **C# plan search order:** LocalAppData/latest → LocalAppData/flat → LocalAppData subdirs → repo artifacts subdirs. Dialog shows all searched paths on failure.
3. **Plan diagnostics:** `axiom inventory-plan-status` reports plan locations, existence, category/priority counts, next Revit prompts.
4. **Manifest hardening:** Per-category `prompt` field added. All required fields present: plan_id, source_model, started_at, completed_at, max_categories, priority_only, resume, per-category prompt/status/export_path/duration_ms/error_message.
5. **Import-batch reliability:** Failed/skipped manifest entries reported clearly. Missing export files counted and warned. All-failed manifest provides resume guidance.
6. **Registry coverage reporting:** Priority category coverage (covered/missing). Output paths in summary. Before/after dedup counts.
7. **Plan file usability:** Preferred execution path (plan queue) documented in plan markdown. Post-processing commands included. Manual prompt warning added.
8. **Deploy script polish:** `-ForceCloseRevit` flag added. DLL lock message improved. Default remains cancel.
9. **REVIEW.md:** Section 8 added with review agent instructions (safety blocks, testing policy, no code changes in review mode).
10. **Docs/logs updated:** pr-review-ledger, behavior-change-ledger (BHV-019), model-inventory-runbook.

### Phase 5: Structured dispatch fix (2026-05-06)

11. **Structured category dispatch (BHV-020):** Plan executor now calls `DispatchCategoryParameterSchema()` directly instead of round-tripping through NLP prompt parsing. Fixes 231 BLOCKED_UNSAFE failures caused by unrecognized categories (Grids, Materials, Project Information, etc.) falling through to the whole-model block.
12. **Non-executable category pre-filtering:** `(No Category)`, `<Unnamed>` skipped before execution with `skipped_unsupported` status. Python planner also filters these from plan generation.
13. **Manifest status distinctions:** `success`, `failed`, `skipped_unsupported`, `skipped_resume`, `skipped_no_elements`.

### Phase 6: Merge-readiness cleanup (2026-05-06)

14. **Environment.CurrentDirectory fallback removed from Revit plan search:** Only `%LOCALAPPDATA%` is the supported Revit plan source. Repo artifacts are CLI-only.
15. **Manifest write failure now reported in dialog** instead of silently showing path to nonexistent file.
16. **PersistInventoryJson catch-all now logs exception** via `Debug.WriteLine`.

### Review Findings Classification

| Finding | Classification | Disposition |
|---------|---------------|-------------|
| B-1: `Environment.CurrentDirectory` unreliable in Revit | Fixed | Removed repo artifact fallback from Revit; LocalAppData is sole supported path |
| B-2: Plan execution queue not live-validated | Resolved | Validated: max 10 (10/10), priority only (16/16) |
| R-2: Manifest write failure silent | Fixed | Dialog now shows WARNING when manifest write fails |
| R-3: Priority categories inconsistent Python/C# | Verified consistent | Both use same 20 categories |
| R-4: PersistInventoryJson catch-all | Improved | Now logs exception; returns null (caller checks) |
| R-5: knownCats duplication in PromptDispatcher | Deferred | Structured dispatch bypasses NLP entirely for plan execution; NLP resolver only used for ad-hoc prompts |

### Test Results

| Suite | Count | Status |
|-------|-------|--------|
| pytest | 373 (full checkpoint) | All passing |
| test-grids (simulate) | 35/35 | All passing |
| test-levels (simulate) | 18/18 | All passing |
| ruff lint | 0 errors | Clean |

---

## PR #1: SQLite Persistence (WAL Mode)

**Status:** Merged
**Scope:** Replace in-memory storage with SQLite persistence layer
