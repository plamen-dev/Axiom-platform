# InventoryModel Runbook

## Overview

InventoryModel is a **read-only** Revit capability that scans the active model and returns a structured inventory of elements and their parameters. It never modifies the model.

**Important:** Default scan mode is **summary-only** (counts and categories). Full parameter scanning of large models can crash Revit due to memory pressure. Always use the staged workflow below.

## Staged Scan Workflow (Recommended)

```
 1. Run InventoryModel                                → summary (counts + categories, no parameters)
 2. Run InventoryModel schema                         → object_schema (ElementId, Category, ClassName, Name, LevelName, IsType)
 3. Run InventoryModel parameter schema               → parameter_schema (ParameterName, StorageType, BuiltInParameterId, IsReadOnly, Instance/Type)
 4. Run InventoryModel parameter schema batch 500     → parameter_schema in bounded batches
 5. axiom inventory-plan --file <summary.json>        → build safe extraction plan
 6. Run InventoryModel for Walls                      → category value extraction (small categories)
 7. Run InventoryModel for Walls schema               → category_object_schema (elements only)
 8. Run InventoryModel for Walls parameter schema     → category_parameter_schema (parameter defs)
 9. Run InventoryModel sample values for Walls        → constrained value samples (max 25 elements)
10. Run InventoryModel sample values for Walls max 25 → explicit max cap
11. Run InventoryModel sample values on Level 1 max 25 → level-constrained samples
12. Run InventoryModel on Level 1                     → level scan (one level)
13. Run InventoryModel for Walls on Level 1           → category + level scan
14. Run InventoryModel sample                        → sample (first 100 elements)
15. Run full InventoryModel                          → DISABLED (returns blocked message)
16. Run InventoryModel batch 100                     → resolves to object_schema (NOT full values)
```

**Full value extraction is currently disabled.** It crashed Revit 2027 on real models (~43K instances), even with batching. The expensive operation is per-element parameter value extraction, not element enumeration.

**Whole-model value sampling is also disabled.** It crashed Revit 2027 due to expensive value accessors. Use category/level-constrained sample values instead.

### Four Extraction Tiers

| Tier | Mode | Cost | Safe for whole model? |
|------|------|------|-----------------------|
| **Object schema** | `object_schema`, `category_object_schema` | Low | Yes (validated Revit 2027) |
| **Parameter schema** | `category_parameter_schema` | Low | Only with category/level constraint (whole-model BLOCKED) |
| **Value sampling** | `category_sample_values` (constrained) | Medium | Only with category/level/max |
| **Whole-model value sampling** | `sample_values` | High | No — BLOCKED |
| **Full value export** | `full` | High | No — BLOCKED |

### Hard Caps for Value Sampling

| Parameter | Default |
|-----------|---------|
| MaxElements | 25 |
| SampleLimit (samples per parameter) | 5 |

These defaults apply unless overridden with `max N` in the prompt.

## Scan Modes

| Mode | Prompt | What it collects | Safety |
|------|--------|------------------|--------|
| **summary** (default) | `Run InventoryModel` | Instance/type counts, category breakdown | Safe for any model size |
| **object_schema** | `Run InventoryModel schema` | ElementId, Category, ClassName, Name, LevelName, IsType (no params) | Safe — validated Revit 2027 |
| **object_schema** (batched) | `Run InventoryModel schema batch 500` | Object schema in bounded batches | Safe |
| **parameter_schema** | `Run InventoryModel parameter schema` | BLOCKED — whole-model param schema crashed Revit 2027 | Blocked |
| **category_object_schema** | `Run InventoryModel for Walls schema` | Category element inventory (no parameters) | Safe |
| **category_parameter_schema** | `Run InventoryModel for Walls parameter schema` | Category parameter definitions only | Safe |
| **sample_values** | `Run InventoryModel sample values` | BLOCKED — whole-model sampling crashed Revit 2027 | Blocked |
| **category_sample_values** | `Run InventoryModel sample values for Walls` | Category value samples (max 25 elements, 5/param) | Safe (constrained) |
| **category** | `Run InventoryModel for Walls` | All elements in one category + parameters | Safe for small categories |
| **level** | `Run InventoryModel on Level 1` | All elements on one level + parameters | Safe for most levels |
| **category_level** | `Run InventoryModel for Walls on Level 1` | One category on one level | Safest value scan |
| **sample** | `Run InventoryModel sample` | First 100 elements + parameters | Always safe (capped) |
| **batch→object_schema** | `Run InventoryModel batch 100` | Resolves to object schema, not full values | Safe |
| **full** | `Run full InventoryModel` | DISABLED — returns blocked message | Blocked |

### Schema Discovery Mode

Two schema modes exist to separate concerns:

**1. Object Schema** (`object_schema`, `category_object_schema`):
- Collects: ElementId, Category, ClassName, Name, LevelName, IsType
- Does NOT collect parameters
- Output includes both instances and types (e.g. 42,881 + 2,276 = 45,157 total elements)
- Validated working on Revit 2027 Snowdon Towers
- This is what `Run InventoryModel schema` produces

**2. Parameter Schema** (`category_parameter_schema` — whole-model BLOCKED):
- Collects: ParameterName, StorageType, BuiltInParameterId, IsReadOnly, IsInstanceParam, IsTypeParam, ObservedCount, ObservedOnCategories, ObservedOnClasses
- Does NOT collect values (no AsString/AsValueString/AsDouble calls)
- Reads only `param.Definition` objects
- Uses `CollectSchema()` in C# service (separate from `CollectInventory()`)
- **Whole-model parameter schema crashed Revit 2027** (BUG-017). Must use category/level constraint.
- Allowed: `Run InventoryModel for Walls parameter schema`, `parameter schema on Level 1`
- Blocked: `Run InventoryModel parameter schema` (no constraint)

**Why whole-model parameter schema crashes:** Even though it only reads `param.Definition` objects (no value accessors), iterating all ~43K elements and enumerating their parameter definitions is still too expensive for live Revit on large models.

### Value Sampling Mode

**Whole-model value sampling is BLOCKED** — it crashed Revit 2027 due to expensive value accessors (AsString, AsValueString, AsDouble). Use constrained sample values with category/level/max constraints.

**Allowed patterns:**
- `Run InventoryModel sample values for Walls` — category-constrained
- `Run InventoryModel sample values for Plumbing Fixtures` — category-constrained
- `Run InventoryModel sample values for Walls max 25` — explicit max
- `Run InventoryModel sample values on Level 1 max 25` — level-constrained
- `Run InventoryModel sample values for Walls on Level 1 max 25` — both

**Blocked:**
- `Run InventoryModel sample values` — no category/level/max → blocked

**Hard caps:**
- MaxElements: 25 (default, overridable with `max N`)
- SampleLimit: 5 samples per parameter
- Never collect all values by default
- Avoid expensive string/value conversions unless needed

### Parameter Discovery Workflow (Validated)

Complete parameter intelligence gathering via plan execution queue. Validated on Revit 2027 (2026-05-23).

**Step 1: Object schema scan**
```
Run InventoryModel schema
```
Exports object_schema (ElementId, Category, ClassName, Name, IsType).

**Step 2: Import object schema and create object registry candidate**
```
axiom inventory-import --file "<object_schema_export.json>"
```

**Step 3: Generate parameter schema plan**
```
axiom inventory-plan --file "<object_schema_summary.json>" --mode parameter-schema
```
Writes plan to both repo artifacts and `%LOCALAPPDATA%\Axiom\inventory_plans\latest\` for Revit pickup.
Priority categories first (20), then remaining sorted smallest-to-largest. Non-executable categories ((No Category), <Unnamed>) excluded.

**Step 4: Execute plan in Revit (automated queue)**
```
Run InventoryModel parameter schema plan max 10       → first 10 categories (validated)
Run InventoryModel parameter schema plan priority only → 20 priority categories (validated)
Run InventoryModel parameter schema plan max 50       → expand coverage progressively
Run InventoryModel parameter schema plan max 100      → stress test larger batch
Run InventoryModel parameter schema plan resume       → retry failed/remaining
Run InventoryModel parameter schema plan              → all categories (only after progressive validation)
```
Each category executes via structured dispatch (CategoryFilter + ScanMode) — no NLP parsing.
Writes per-category export JSON and manifest to `%LOCALAPPDATA%\Axiom\inventory_exports\`.

**Validated (2026-05-06):** Full plan execution validated — 278 successful exports, 1 skipped unsupported, 0 failed. Registry: 6,444 unique definitions, 1,878 parameter names, 1,748 runs, 5 source models (Snowdon Towers). 20/20 priority categories with definitions.

**Step 5: Batch import from manifest**
```
axiom inventory-import-batch --manifest "<manifest_path>"
axiom inventory-import-batch --dir "<exports_dir>" --scan-mode category_parameter_schema
```

**Step 6: Build parameter registry with coverage analysis**
```
axiom parameter-registry-build --from-inventory artifacts/model_inventory_runs --object-registry artifacts/object_registry_candidates/<run_id>
```
Deduplicates by 8-tuple key (Category, ClassName, ParameterName, BuiltInParameterId, DataTypeId, StorageType, IsInstanceParam, IsTypeParam).
Reports covered/missing categories including priority coverage breakdown.
Output: `artifacts/parameter_registry_candidates/<run_id>/`

**Step 7: Check plan and coverage status**
```
axiom inventory-plan-status
```

### Blocked Commands (do NOT use)

These commands are blocked because they crashed Revit 2027 on real models:

- `Run full InventoryModel` — full element+parameter dump
- `Run InventoryModel sample values` — whole-model value sampling
- `Run InventoryModel parameter schema` — whole-model parameter schema
- Any prompt that attempts whole-model value extraction

The plan execution queue only executes `category_parameter_schema` jobs. Unsafe commands remain blocked in both Python resolver and C# dispatcher.

### Priority Categories

Walls, Doors, Windows, Floors, Rooms, Views, Sheets, Levels, Grids, Ducts, Pipes, Mechanical Equipment, Plumbing Fixtures, Lighting Fixtures, Electrical Fixtures, Ceilings, Columns, Stairs, Railings, Furniture.

### Category/Level Value Extraction (unchanged)

**Category-batched:**
- `Run InventoryModel for Walls batch 100` → walls only, 100 per batch

**Level-batched:**
- `Run InventoryModel on Level 1 batch 100` → Level 1 elements, 100 per batch

**Category+level batched:**
- `Run InventoryModel for Walls on Level 1 batch 100`

**After extraction, merge batches:**
```
axiom inventory-combine --manifest "<manifest.json>"
axiom inventory-combine --batch-dir "<batch-folder>"
axiom inventory-combine --manifest "<manifest.json>" --chunk-by discipline
```

**Important distinction:**
- `Run full InventoryModel` = BLOCKED (unsafe in-memory dump)
- `Run InventoryModel batch N` = SAFE (incremental, crash-checkpointed)

Bare `Run InventoryModel` (no batch number, no category/level) = summary mode (counts only).

### Safety Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SummaryOnly` | `true` | Only collect counts and categories — no element details |
| `CategoryFilter` | `null` (all) | Limit to specific categories (e.g. `["Walls"]`) |
| `LevelFilter` | `null` (all) | Limit to specific levels (e.g. `["Level 1"]`) |
| `MaxElements` | `0` (no limit) | Hard cap on element count (used by sample mode) |
| `BatchSize` | `0` (no batching) | Elements per batch for continuation extraction |
| `SkipElements` | `0` | Offset for manual pagination/resume |
| `IncludeParameters` | `false` | Collect parameters on each element |
| `IncludeTypeParameters` | `false` | Collect type parameters |
| `IncludeInstanceParameters` | `false` | Collect instance parameters |

Per-element exceptions are caught silently — a crash on one element does not abort the entire scan. Error counts are reported in the dialog.

### Architecture Note: Level Filtering

**Level filter is post-collector / pre-extraction.** The C# `ModelInventoryService` uses `FilteredElementCollector(doc).WhereElementIsNotElementType()` which iterates all elements. Level filtering is applied inside the foreach loop — after the element is retrieved but before parameter extraction (`CollectParameters()`). This means:
- The Revit collector still enumerates all elements
- Level lookup (`GetElementLevelName`) runs per element (lightweight — reads one parameter)
- **Parameter extraction is skipped for filtered-out elements** — this is the expensive operation

For future optimization: use `ElementLevelFilter` for true pre-collector filtering.

## Entry Points

### CLI

```bash
python -m poetry run axiom inventory-model
python -m poetry run axiom inventory-model --output-dir artifacts/model_inventory_runs --run-id my_run
```

### Revit Prompt Dialog

Summary scan prompts (safe default):
- `Run InventoryModel`
- `inventory model`
- `List all model elements`
- `Scan model parameters`

Category scan prompts:
- `Run InventoryModel for Walls`
- `Inventory doors`
- `Inventory parameters for windows`

Sample scan prompts:
- `Run InventoryModel sample`

Full scan prompts (use with caution):
- `Run full InventoryModel`
- `full inventory`

InventoryModel can run from **any view** (floor plan, section, elevation, 3D). It is not restricted to plan views like CreateGrids/CreateLevels.

The dialog shows scan mode, element/type counts, and (for non-summary scans) parameter counts. After a summary scan, it also shows next-step suggestions.

### Revit → Python Artifact Pipeline

When InventoryModel runs from the Revit Prompt dialog, it writes a JSON export to:
```
%LOCALAPPDATA%\Axiom\inventory_exports\inv_YYYYMMDD_HHmmss_fff_NNN_category_slug.json
```
Where `fff` = milliseconds, `NNN` = atomic sequence counter, `category_slug` = sanitized category name. This format prevents filename collisions when multiple categories are processed within the same second (BUG-018 fix).

To persist this into the standard Parquet/SQLite artifact pipeline:
```bash
python -m poetry run axiom inventory-import --latest
python -m poetry run axiom inventory-import --file path/to/inv_20260506_120000.json
```

This creates the same artifacts as a CLI-initiated run. After importing, use `inventory-summary --latest` to inspect.

**Note:** `%LOCALAPPDATA%` exports are temporary handoff files, not durable artifacts. The Parquet/SQLite artifacts in `artifacts/model_inventory_runs/` are the durable storage.

## Output Artifacts

Each run creates a directory under `artifacts/model_inventory_runs/<run_id>/`:

| File | Format | Purpose |
|------|--------|---------|
| `elements.jsonl` | JSONL | Raw append-only element data |
| `elements.parquet` | Parquet | Structured element dataset |
| `parameters.parquet` | Parquet | Structured parameter dataset |
| `summary.md` | Markdown | Human-readable run summary |

## Parameter Collection: Generic Enumeration

The C# `ModelInventoryService.CollectParameters()` uses **generic enumeration** over `elem.Parameters` — it does **not** hardcode parameter names. Every readable parameter exposed by the Revit API on each element is captured, including:

- **Built-in parameters** (e.g. `CURVE_ELEM_LENGTH`, `HOST_AREA_COMPUTED`)
- **Project parameters** (user-defined, project-scoped)
- **Family parameters** (defined in the family editor)
- **Shared parameters** (GUID-based, cross-project)

The `BuiltInParameterId` field is populated only for built-in parameters (via `InternalDefinition.BuiltInParameter`). For project, family, and shared parameters this field is empty — this is expected behavior, not a gap.

**Null/unreadable value handling:** Parameters with `null` definitions or no value (`!param.HasValue`) are silently skipped. All value extraction uses null-coalescing (`?? ""`) to prevent runtime errors.

**Type parameters** are collected when `IncludeTypeParameters` is `true` (default: `false`). Instance parameters are collected when `IncludeInstanceParameters` is `true` (default: `false`). Both use the same generic `CollectParameters()` method. Set `IncludeParameters` to `true` as a shorthand to enable both.

**Schema fields are metadata, not collection limits.** Fields like `parameter_group`, `level_id`, and `source_model` in the Parquet/SQLite schema are output columns for analysis. They do not filter or restrict which parameters are collected. The examples in tests/fixtures are representative samples — real Revit execution captures all available parameters.

## Schema

### Elements (Parquet / SQLite)

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | string | Unique identifier for this inventory run |
| `source_model` | string | Document title / model name |
| `element_id` | int64 | Revit ElementId |
| `unique_id` | string | Revit UniqueId (GUID) |
| `category` | string | Revit category (Walls, Doors, Levels, etc.) |
| `class_name` | string | .NET class name (Wall, FamilyInstance, Level, etc.) |
| `name` | string | Element name |
| `family_name` | string | Family name if available |
| `type_name` | string | Type name if available |
| `level_name` | string | Associated level name if available |
| `level_id` | int64 | Associated level ElementId (0 if none) |
| `workset_name` | string | Workset name if workshared |
| `is_type` | bool | True for ElementType, False for instance |
| `parameter_count` | int32 | Number of parameters on this element |

### Parameters (Parquet / SQLite)

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | string | Links to the inventory run |
| `element_id` | int64 | Parent element's ElementId |
| `param_name` | string | Parameter name |
| `storage_type` | string | Revit storage type (String, Double, Integer, ElementId) |
| `value_string` | string | Value as display string |
| `value_number` | float64 | Numeric value (Double params) |
| `value_integer` | int64 | Integer value (Integer/ElementId params) |
| `built_in_parameter_id` | string | BuiltInParameter enum name if available |
| `is_read_only` | bool | Whether the parameter is read-only |
| `is_instance_param` | bool | True if on an instance element, False if on a type |
| `parameter_group` | string | Parameter group (Dimensions, Identity Data, etc.) |

## SQLite Queries

The inventory data is also persisted to `~/.axiom/axiom.db`. Common queries:

```sql
-- All parameters for a specific element
SELECT * FROM inventory_parameters
WHERE element_id = 100001 AND run_id = 'inv_20260101_120000';

-- All elements with a specific parameter name
SELECT DISTINCT ie.element_id, ie.name, ie.category
FROM inventory_elements ie
JOIN inventory_parameters ip ON ie.element_id = ip.element_id AND ie.run_id = ip.run_id
WHERE ip.param_name = 'Width';

-- Instance vs type parameter counts
SELECT is_instance_param, COUNT(*) as param_count
FROM inventory_parameters
WHERE run_id = 'inv_20260101_120000'
GROUP BY is_instance_param;

-- Compare two runs: elements added/removed
SELECT 'added' as change, b.element_id, b.category, b.name
FROM inventory_elements b
LEFT JOIN inventory_elements a ON a.element_id = b.element_id AND a.run_id = 'run_1'
WHERE b.run_id = 'run_2' AND a.element_id IS NULL
UNION ALL
SELECT 'removed', a.element_id, a.category, a.name
FROM inventory_elements a
LEFT JOIN inventory_elements b ON b.element_id = a.element_id AND b.run_id = 'run_2'
WHERE a.run_id = 'run_1' AND b.element_id IS NULL;

-- Category counts per run
SELECT run_id, category, COUNT(*) as count
FROM inventory_elements
GROUP BY run_id, category
ORDER BY run_id, count DESC;

-- Writable parameters only
SELECT * FROM inventory_parameters
WHERE is_read_only = 0 AND run_id = 'inv_20260101_120000';
```

## Summary Report

The generated `summary.md` includes:

- **Run metadata**: run_id, source model, timestamp, duration
- **Totals**: element instances, types, parameters, read-only vs writable counts
- **Category breakdown**: count per Revit category
- **Top parameters**: most frequently occurring parameter names
- **Missing level count**: instances without an associated level

## Reviewing Inventory Runs

Use `inventory-summary` to inspect generated artifacts without re-running the inventory:

```bash
# Inspect the most recent run
python -m poetry run axiom inventory-summary --latest

# Inspect a specific run
python -m poetry run axiom inventory-summary --run-id inv_20260101_120000

# Filter by category
python -m poetry run axiom inventory-summary --latest --category Walls

# Filter by parameter name
python -m poetry run axiom inventory-summary --latest --param-name Width

# Show only writable parameters
python -m poetry run axiom inventory-summary --latest --writable-only

# Combine filters
python -m poetry run axiom inventory-summary --latest --category Doors --writable-only

# Custom artifact directory
python -m poetry run axiom inventory-summary --latest --base-dir artifacts/model_inventory_runs
```

The command reads from Parquet artifacts — no Revit connection required.

**Output includes:**
- Run metadata (run_id, source_model)
- Totals (instances, types, parameters, read-only/writable, instance/type, missing level)
- Category counts
- Top 15 parameter names by frequency

## Simulation / Mock Mode

When running on a non-Windows machine or without Revit, the system uses mock data with 5 representative elements:
- Wall instance (with Length, Area, Volume, Comments)
- Door instance (with Width, Height, Mark)
- Level 1 instance (with Elevation, Name)
- Level 2 instance (with Elevation, Name)
- Wall type (with Width, Function)

## Testing

```bash
# Run all inventory tests
python -m poetry run pytest tests/test_inventory.py -v

# Run test cases from fixture file
# (test harness integration planned for future phase)
```

### Test Categories

| Category | Count | Covers |
|----------|-------|--------|
| Prompt resolver | 12 | keyword matching, unrelated prompts, regression guards |
| Mock execution | 6 | success, schema validation, types/instances, source model, read-only/writable |
| Registry | 2 | registration, metadata |
| Storage | 15 | JSONL, Parquet, SQLite, empty model, large inventory, duplicates, missing levels |
| Summary | 7 | report generation, totals, categories, edge cases |
| Schema | 2 | field completeness |

## Pending Real Revit Validation

The following require Revit open on Windows:

- [x] Real `Run InventoryModel` via pipe produces output — **validated Revit 2027**
- [x] Elements from real model match expected schema — **validated Revit 2027**
- [x] Large model performance (>10,000 elements) — **validated:** Snowdon Towers 2.0, 42,881 instances / 2,276 types, summary scan 560ms
- [ ] Workshared model with workset names populated
- [ ] Category filter parameter works as expected
- [ ] Sample scan (MaxElements) works as expected
- [ ] Full scan with streaming write on large model
- [ ] Parameters extracted from all storage types (String, Double, Integer, ElementId)
- [ ] ParameterGroup populated for built-in parameters
- [x] JSON export path shown in dialog — **validated Revit 2027**
- [x] `inventory-import --file` with UTF-8 BOM JSON — **validated** (BUG-013 fix)

## Known Gaps

1. **ParameterGroup not populated in C#**: The `ModelInventoryService.cs` does not yet extract `ParameterGroup` from the Revit API. The field exists in the schema and mock data but will need a C# update: `param.Definition?.ParameterGroup?.ToString() ?? ""`.

2. **LevelId not populated in C#**: The `ElementEntry` DTO does not yet have a `LevelId` field. The level ElementId is available during `BuildElementEntry` but not stored. Need to add `public int LevelId { get; set; }` to `ElementEntry` and populate it.

3. **Source model title**: The C# `InventoryModelCapability` does not yet include `doc.Title` in the output. Need to add `result.OutputData["source_model"] = doc.Title;` to the real execution path.

These are small C# changes to be made when the Revit real execution is validated.

## Full Registry Coverage Workflow

Complete parameter discovery across all Revit object categories. **Validated end-to-end on Revit 2027 (2026-05-06).**

```
1. Run InventoryModel schema                             → object_schema (45K elements)
2. axiom inventory-import --file <object_schema.json>    → creates object registry candidate
3. axiom inventory-plan --file <summary.json> --mode parameter-schema
                                                         → generates all-category plan (278 categories)
4. Run InventoryModel parameter schema plan              → 278 exports via structured dispatch
5. axiom inventory-import-batch --manifest <manifest>    → batch import all exports
6. axiom parameter-registry-build --from-inventory artifacts/model_inventory_runs
     --object-registry artifacts/object_registry_candidates/<run_id>
                                                         → build property registry (6,444 definitions)
```

### Artifacts produced:
- `artifacts/object_registry_candidates/<run_id>/` — JSONL + Parquet + summary
- `artifacts/inventory_plans/<plan_id>/` — parameter_schema_plan.json + .md
- `artifacts/parameter_registry_candidates/<timestamp>/` — revit_property_registry.jsonl + .parquet + summary.md

### Registry deduplication key:
ObjectCategory, ClassName, ParameterName, BuiltInParameterId, DataTypeId, StorageType, IsInstanceParam, IsTypeParam

### Plan execution queue (validated):

Automatic multi-category execution via structured dispatch:

```
Run InventoryModel parameter schema plan              → executes all categories from plan
Run InventoryModel parameter schema plan max 10       → first 10 categories only
Run InventoryModel parameter schema plan priority only → priority categories only (20 categories)
Run InventoryModel parameter schema plan resume        → skip already-completed, continue remaining
```

**Behavior:**
1. Reads latest `parameter_schema_plan.json` from `%LOCALAPPDATA%\Axiom\inventory_plans\` or repo `artifacts/inventory_plans/`
2. Executes `category_parameter_schema` one category at a time
3. Writes one JSON export per category to `%LOCALAPPDATA%\Axiom\inventory_exports\`
4. Writes manifest: `parameter_schema_manifest_<timestamp>.json`
5. Dialog shows completed/failed/skipped counts and next CLI command

**Manifest import:**
```
axiom inventory-import-batch --manifest "<manifest_path>"
axiom inventory-import-batch --dir "<exports_dir>" --scan-mode category_parameter_schema
```

**Plan handoff:** `inventory-plan --mode parameter-schema` writes plan JSON to both repo artifacts AND `%LOCALAPPDATA%\Axiom\inventory_plans\latest\` for Revit pickup. Revit searches LocalAppData first, falls back to repo artifacts. Use `axiom inventory-plan-status` to check plan locations and existence.

**Safety:** Only executes `category_parameter_schema` jobs. Whole-model parameter schema, sample values, and full inventory remain blocked.

### Complete safe workflow (end-to-end):

```bash
# 1. Object schema discovery (in Revit)
Run InventoryModel schema

# 2. Import object schema
axiom inventory-import --file <export.json>

# 3. Plan parameter schema extraction
axiom inventory-plan --file <summary.json> --mode parameter-schema

# 4. Check plan status
axiom inventory-plan-status

# 5. Execute plan (in Revit — pick one)
Run InventoryModel parameter schema plan max 10         # validate first
Run InventoryModel parameter schema plan priority only  # priority categories
Run InventoryModel parameter schema plan resume         # continue after interruption
Run InventoryModel parameter schema plan                # all categories

# 6. Import results from manifest
axiom inventory-import-batch --manifest "<manifest_path>"

# 7. Build property registry
axiom parameter-registry-build --from-inventory artifacts/model_inventory_runs \
  --object-registry artifacts/object_registry_candidates/<run_id>

# 8. Review coverage
axiom inventory-plan-status
```

### Registry Milestone Results (2026-05-06)

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

**Known next gaps:**
1. Non-Snowdon models — need broader parameter diversity
2. Family/library coverage — family-level and shared parameter definitions
3. Resume validation — `plan resume` on large partial manifests

### BLOCKED commands (never recommended by planner):
- `Run InventoryModel parameter schema` (whole-model — crashed Revit 2027)
- `Run InventoryModel sample values` (whole-model — crashed Revit 2027)
- `Run full InventoryModel` (crashed Revit 2027 on large models)
- Whole-model value extraction (any form)
