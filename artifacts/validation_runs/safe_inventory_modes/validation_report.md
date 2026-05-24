# Safe InventoryModel Replacement — Validation Report

**Date:** 2026-05-21 00:28 UTC
**Branch:** `revit-2027-compatibility`
**Total tests:** 46
**Passed:** 46
**Failed:** 0
**Environment:** Python prompt resolver (no live Revit)

---

## Architecture Note: Level Filtering

**Flag: Level filter is NOT pre-collector.** The C# `ModelInventoryService.CollectInventory()` uses `FilteredElementCollector(doc).WhereElementIsNotElementType()` which iterates ALL elements. Level filtering is applied inside the `foreach` loop (line 58-63) — **after** the element is retrieved from the collector but **before** parameter extraction (`CollectParameters()`).

This means:
- The Revit collector still enumerates all elements in the model
- Level lookup (`GetElementLevelName`) runs for every element (lightweight — reads one parameter)
- **Parameter extraction is skipped for filtered-out elements** — this is the expensive operation
- For category filter, same pattern: all elements enumerated, non-matching skipped before extraction

**Recommendation for future optimization:** Use `FilteredElementCollector` with `.WherePasses(new ElementLevelFilter(levelId))` for true pre-collector filtering. This would avoid even enumerating non-matching elements. Current approach is safe but not optimal.

---

## Results by Category

### 1. Summary mode — PASS (3/3)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-001 | `Run InventoryModel` | summary | — | — | — | resolved | PASS |
| VAL-002 | `InventoryModel` | summary | — | — | — | resolved | PASS |
| VAL-003 | `model inventory` | summary | — | — | — | resolved | PASS |

### 2. Sample mode — PASS (2/2)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-010 | `Run InventoryModel sample` | sample | — | — | 100 | resolved | PASS |
| VAL-011 | `inventory sample` | sample | — | — | 100 | resolved | PASS |

### 3. Single-category mode — PASS (6/6)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-02-2 | `Run InventoryModel for Walls` | category | Walls | — | — | resolved | PASS |
| VAL-02-1 | `Inventory doors` | category | Doors | — | — | resolved | PASS |
| VAL-020 | `Run InventoryModel for Levels` | category | Levels | — | — | resolved | PASS |
| VAL-021 | `Inventory rooms` | category | Rooms | — | — | resolved | PASS |
| VAL-022 | `Run InventoryModel for Mechanical Equipment` | category | Mechanical Equipment | — | — | resolved | PASS |
| VAL-023 | `Inventory parameters for windows` | category | Windows | — | — | resolved | PASS |

### 4. Level-only mode — PASS (4/4)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-040 | `Run InventoryModel on Level 1` | level | — | 1 | — | resolved | PASS |
| VAL-041 | `Run InventoryModel on Level Ground` | level | — | Ground | — | resolved | PASS |
| VAL-042 | `Run InventoryModel for Level 2` | level | — | 2 | — | resolved | PASS |
| VAL-043 | `Run InventoryModel at Level Basement` | level | — | Basement | — | resolved | PASS |

### 5. Category+level mode — PASS (4/4)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-050 | `Run InventoryModel for Walls on Level 1` | category_level | Walls | 1 | — | resolved | PASS |
| VAL-051 | `Run InventoryModel for Doors on Level 1` | category_level | Doors | 1 | — | resolved | PASS |
| VAL-052 | `Inventory doors on Level 2` | category_level | Doors | 2 | — | resolved | PASS |
| VAL-053 | `Run InventoryModel for Floors on Level Ground` | category_level | Floors | Ground | — | resolved | PASS |

### 6. Max threshold mode — PASS (5/5)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-060 | `Run InventoryModel for Walls max 500` | category | Walls | — | 500 | resolved | PASS |
| VAL-061 | `Run InventoryModel for Doors max 500` | category | Doors | — | 500 | resolved | PASS |
| VAL-062 | `Run InventoryModel on Level 1 limit 1000` | level | — | 1 | 1000 | resolved | PASS |
| VAL-063 | `Run InventoryModel for Walls on Level 1 max 200` | category_level | Walls | 1 | 200 | resolved | PASS |
| VAL-064 | `Run InventoryModel for Walls first 50` | category | Walls | — | 50 | resolved | PASS |

### 7. Full scan blocked — PASS (6/6)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-07-3 | `Run full InventoryModel` | — | — | — | — | blocked | PASS |
| VAL-07-2 | `full inventory` | — | — | — | — | blocked | PASS |
| VAL-07-1 | `Run full scan InventoryModel` | — | — | — | — | blocked | PASS |
| VAL-070 | `Run complete inventory` | — | — | — | — | blocked | PASS |
| VAL-071 | `full inventory scan of the model` | — | — | — | — | blocked | PASS |
| VAL-072 | `run full inventorymodel please` | — | — | — | — | blocked | PASS |

### 8. No unbounded extraction — PASS (13/13)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-08-3 | `Run InventoryModel` | summary | — | — | — | resolved | PASS |
| VAL-08-2 | `Run InventoryModel sample` | sample | — | — | 100 | resolved | PASS |
| VAL-08-1 | `Run InventoryModel for Walls` | category | Walls | — | — | resolved | PASS |
| VAL-080 | `Inventory doors` | category | Doors | — | — | resolved | PASS |
| VAL-081 | `Run InventoryModel on Level 1` | level | — | 1 | — | resolved | PASS |
| VAL-082 | `Run InventoryModel for Walls on Level 1` | category_level | Walls | 1 | — | resolved | PASS |
| VAL-083 | `Run InventoryModel for Walls max 500` | category | Walls | — | 500 | resolved | PASS |
| VAL-084 | `inventory plan` | (plan) | — | — | — | blocked | PASS |
| VAL-085 | `Create an extraction plan` | (plan) | — | — | — | blocked | PASS |
| VAL-086 | `model inventory` | summary | — | — | — | resolved | PASS |
| VAL-087 | `scan model parameters` | summary | — | — | — | resolved | PASS |
| VAL-088 | `extract model parameters` | summary | — | — | — | resolved | PASS |
| VAL-089 | `inventory parameters for walls` | category | Walls | — | — | resolved | PASS |

### Plan prompt — PASS (3/3)

| ID | Prompt | Mode | Category | Level | Max | Status | Result |
|-----|--------|------|----------|-------|-----|--------|--------|
| VAL-090 | `inventory plan` | (plan) | — | — | — | blocked | PASS |
| VAL-091 | `Create an extraction plan` | (plan) | — | — | — | blocked | PASS |
| VAL-092 | `Build an extraction plan for my model` | (plan) | — | — | — | blocked | PASS |

## Safety Summary

**No prompt path resolves to unbounded full extraction.**

**Full scan blocked:** 6/6 variants correctly blocked

## Live Revit 2027 Validation (2026-05-21)

**Model:** Snowdon Towers Sample Architectural
**Environment:** Revit 2027, Windows, Axiom add-in deployed to C:\Program Files\Autodesk\Revit\Addins\2027

| Mode | Result | Details |
|------|--------|---------|
| Summary | PASS | 42,881 instances, 2,276 types, 0 errors, 61ms |
| Category — Ceilings | PASS | 78 instances, 7 types, 1,599 parameters, 0 errors |
| Category — Plumbing Fixtures | PASS | 150 instances, 31 types, 4,119 parameters, 0 errors |
| inventory-import | PASS | Both category exports imported successfully |
| inventory-summary | PASS | Summary output works after import |
| Artifacts | PASS | elements.jsonl, elements.parquet, parameters.parquet, run_metadata.json, summary.md |
| Full scan | CRASH | Revit 2027 crashed — remains blocked |
| Deployment | PASS | deploy-revit-2027.ps1 succeeded, all DLLs verified |

## Remaining Validation (Pending)

- [x] Summary mode produces category_counts from real model — **PASS**
- [x] Category scan on real model — **PASS (Ceilings, Plumbing Fixtures)**
- [ ] Level scan actually filters elements by level in Revit
- [ ] Category+level scan produces correct subset
- [ ] Whole-model batched extraction (`Run InventoryModel batch 100`)
- [ ] Category-batched extraction (`Run InventoryModel for Walls batch 100`)
- [ ] `axiom inventory-plan` produces valid plan from real summary
- [ ] `axiom inventory-combine` on batch outputs
- [ ] Level filter performance acceptable (see architecture note above)
