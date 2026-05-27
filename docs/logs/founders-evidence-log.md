# Founder's Evidence Log

Chronological record of validated engineering milestones and evidence artifacts.

For detailed behavior history, see `docs/logs/behavior-change-ledger.md`.
For bug discovery and resolution, see `docs/logs/bug-validation-log.md`.
For PR-level review, see `docs/logs/pr-review-ledger.md`.

---

## EVID-001: Registry Milestone — Full Parameter Schema Coverage (2026-05-06)

**PRs:** #5 (Revit 2027 compatibility), #6 (Local Runner v0), #9 (export collision fix). PR #8 (registry reporting) superseded by PR #9.
**Status:** PRs #5, #6, #9 merged to main. PR #8 closed (changes included in PR #9 via cherry-pick).

### What Was Validated

| Metric | Value |
|--------|-------|
| Unique parameter/property definitions | 6,444 |
| Unique parameter names | 1,878 |
| Source runs | 1,748 |
| Source models | 5 (Snowdon Towers: Architectural, Electrical, HVAC, Plumbing, Structural) |
| Full plan categories executed | 278 successful, 1 skipped unsupported, 0 failed |
| Export path duplicates | 0 |
| Priority categories executed | 20/20 |
| Priority categories with definitions | 20/20 |

### Evidence Chain

1. **Revit 2027 live execution** — plan execution queue ran 278 category_parameter_schema jobs without crash
2. **Structured dispatch** — bypasses NLP, dispatches CategoryFilter + ScanMode directly (BHV-020)
3. **Export collision fix** — unique filenames per category, 0 duplicates (BUG-018, BHV-021)
4. **Registry coverage reporting** — distinguishes executed/definitions/zero-definitions/not-executed (BHV-022)
5. **Batch import** — `inventory-import-batch --manifest` imported all 278 exports
6. **Registry build** — `parameter-registry-build` deduped to 6,444 definitions using 8-tuple key

### Artifact Locations

| Artifact | Path |
|----------|------|
| Registry JSONL | `artifacts/parameter_registry_candidates/<run_id>/revit_property_registry.jsonl` |
| Registry Parquet | `artifacts/parameter_registry_candidates/<run_id>/revit_property_registry.parquet` |
| Registry summary | `artifacts/parameter_registry_candidates/<run_id>/summary.md` |
| Run metadata | `artifacts/parameter_registry_candidates/<run_id>/run_metadata.json` |
| Inventory runs | `artifacts/model_inventory_runs/` |
| Object registry | `artifacts/object_registry_candidates/<run_id>/` |

### Safety Status at Milestone

| Command | Status |
|---------|--------|
| Run full InventoryModel | BLOCKED |
| Run InventoryModel sample values (whole-model) | BLOCKED |
| Run InventoryModel parameter schema (whole-model) | BLOCKED |
| Plan queue category_parameter_schema | ALLOWED (validated) |
| CreateGrids / CreateLevels | Unchanged |
| Revit 2024 baseline | Protected |

### Known Next Gaps

1. **Broader model coverage** — only Snowdon Towers validated; need non-Snowdon models
2. **Family/library coverage** — family-level and shared parameter definitions not yet scanned
3. **Resume validation** — `plan resume` mode not yet tested on large partial manifests

---

## EVID-002: PR #5 Merge — Revit 2027 Compatibility (2026-05-06)

**PR:** #5 (`revit-2027-compatibility`)
**Commit:** `c5df9df`

### What Was Delivered

- Revit 2027 .NET 10 compatibility via shared source + version-specific csproj
- Schema-centric inventory redesign (object_schema, parameter_schema, sample_values tiers)
- Adaptive extraction planner with priority categories
- Plan execution queue (max N, priority only, resume)
- Structured dispatch bypassing NLP for plan execution
- Full InventoryModel, whole-model sample values, whole-model parameter schema all blocked
- 20 priority categories defined and validated
- Deploy script with PowerShell syntax fix and ForceCloseRevit flag

### Live Validation

- Summary mode: PASS (42,881 instances, 2,276 types)
- Category mode: PASS (Ceilings, Plumbing Fixtures)
- Object schema: PASS (45,157 elements, 16MB JSON)
- Plan max 10: PASS (10/10)
- Plan priority only: PASS (16/16)
- Full scan: CONFIRMED CRASH (remains blocked)
- Tests: 373 pytest passing, 35/35 grids, 18/18 levels

---

## EVID-003: PR #6 Merge — Local Runner v0 (2026-05-06)

**PR:** #6 (`feature/axiom-local-runner-v0`)
**Commit:** `45680ed`

### What Was Delivered

- Restricted local execution harness with 9 allowlisted actions
- Workspace restriction, timeout handling, artifact capture
- Command fix: `poetry run` instead of `python -m poetry run`
- No InventoryModel, CreateGrids, or CreateLevels behavior modified

### Live Validation

- git_status, test_grids, test_levels, ruff tasks: all PASS
- Failure artifact capture: PASS
- Tests: 22/22 local runner tests passing

---

## EVID-004: PR #9 Merge — Export Path Collision Fix (2026-05-06)

**PR:** #9 (`devin/1779605963-fix-export-path-collision`)
**Commit:** `0121777`

### What Was Delivered

- Unique export filenames: `inv_YYYYMMDD_HHmmss_fff_NNN_category_slug.json`
- Manifest duplicate detection in import-batch
- Registry coverage reporting: executed vs definitions vs zero-definitions vs not-executed
- No extraction behavior changed

### Live Validation

- 278 exports, 278 distinct paths, 0 duplicates (was 252 duplicates before fix)
- Registry: 6,444 definitions, 20/20 priority coverage
- Tests: 402 pytest passing
