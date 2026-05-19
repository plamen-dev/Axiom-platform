# InventoryModel Runbook

## Overview

InventoryModel is a **read-only** Revit capability that scans the active model and returns a structured inventory of all elements and their parameters. It never modifies the model.

## Entry Points

### CLI

```bash
python -m poetry run axiom inventory-model
python -m poetry run axiom inventory-model --output-dir artifacts/model_inventory_runs --run-id my_run
```

### Revit Prompt Dialog

Type any of these prompts:
- `Run InventoryModel`
- `inventory model`
- `List all model elements`
- `Scan model parameters`
- `Extract model parameters`
- `Extract all parameters`
- `Show writable parameters`

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

**Type parameters** are collected when `IncludeTypeParameters` is `true` (default). Instance parameters are collected when `IncludeInstanceParameters` is `true` (default). Both use the same generic `CollectParameters()` method.

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

- [ ] Real `Run InventoryModel` via pipe produces output
- [ ] Elements from real model match expected schema
- [ ] Large model performance (>10,000 elements)
- [ ] Workshared model with workset names populated
- [ ] Category filter parameter works as expected
- [ ] Parameters extracted from all storage types (String, Double, Integer, ElementId)
- [ ] ParameterGroup populated for built-in parameters

## Known Gaps

1. **ParameterGroup not populated in C#**: The `ModelInventoryService.cs` does not yet extract `ParameterGroup` from the Revit API. The field exists in the schema and mock data but will need a C# update: `param.Definition?.ParameterGroup?.ToString() ?? ""`.

2. **LevelId not populated in C#**: The `ElementEntry` DTO does not yet have a `LevelId` field. The level ElementId is available during `BuildElementEntry` but not stored. Need to add `public int LevelId { get; set; }` to `ElementEntry` and populate it.

3. **Source model title**: The C# `InventoryModelCapability` does not yet include `doc.Title` in the output. Need to add `result.OutputData["source_model"] = doc.Title;` to the real execution path.

These are small C# changes to be made when the Revit real execution is validated.
