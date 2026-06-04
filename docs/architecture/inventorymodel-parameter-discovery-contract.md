# InventoryModel → DiscoveryHarness Parameter Discovery Contract

**Status:** v1 (PR #21)
**Scope:** InventoryModel parameter export enrichment + the stable join contract
that lets DiscoveryHarness v1 perform complete parameter discovery.
**Read-only:** This contract covers discovery/export only. No mutation, no
candidate execution, no learning, promotion, or scoring.

---

## 1. Why this exists

PR #20 validated the DiscoveryHarness architecture but exposed a limitation in
the existing InventoryModel export:

```
Categories discovered: 204
Parameters discovered: 0
Candidate capabilities generated: 0
Parameter rows joined/total: 0/1
Discovery complete: NO
```

The historical artifact (`artifacts/model_inventory_runs/inv_20260523_170419`)
was produced by a summary/object scan: `elements.jsonl` carried 204 categories
but `parameters.parquet` held only a placeholder row with no real parameters and
no join key, so nothing joined.

This contract defines the **enriched per-element parameter export** and the
**stable elements↔parameters join key** so that, when InventoryModel runs a mode
that actually collects per-element parameters (category / sample / full scans),
DiscoveryHarness reaches:

```
Categories discovered  > 0
Parameters discovered  > 0
Candidates generated   > 0
Discovery complete: YES
```

> **Summary-mode note.** Per the InventoryModel safety rules, *summary mode does
> not dump parameters* and zero parameters in summary mode is valid (not an
> error). This contract does not change that: it enriches the export **when
> parameters are collected**. A summary run still produces categories only and is
> correctly reported by DiscoveryHarness as category-only / not complete.

---

## 2. Three-layer architecture (unchanged)

```
Revit Model
   ↓
InventoryModel        raw facts / exports  (owns all extraction + scan modes)
   ↓ elements + parameters exports (this contract)
DiscoveryHarness      interpreted facts    (pure interpreter; never scans)
   ↓
Registries + Evidence + Candidate Capabilities
```

InventoryModel owns extraction and the export schema (this document).
DiscoveryHarness only **reads** these artifacts; it does not re-scan or
re-implement extraction.

---

## 3. Run folder contract

A run folder (`artifacts/model_inventory_runs/<run_id>/`) contains:

| File | Produced by | Purpose |
| --- | --- | --- |
| `elements.jsonl` | `write_jsonl` | objects/categories, one element per line |
| `elements.parquet` | `write_elements_parquet` | objects/categories, columnar |
| `parameters.parquet` | `write_parameters_parquet` | **per-element parameters (enriched)** |
| `parameters.csv` | `write_parameters_csv` | same rows, human-reviewable |
| `parameters.jsonl` | `write_parameters_jsonl` | same rows, one parameter per line |
| `run_metadata.json` | inventory CLI | provenance (optional) |

DiscoveryHarness reads objects from `elements.jsonl` (or `elements.parquet`) and
parameters from `parameters.parquet`, joining by the stable key below.

---

## 4. Stable join contract

**Join key: `parameters.element_id` (int64) == `elements.element_id` (int64),
within the same `run_id`.**

Rules:

1. Both tables are produced by the same writer pass (`persist_inventory`) from
   the same in-memory element list, so `element_id` values are guaranteed
   consistent and same-typed (`int64`).
2. Every parameter row also denormalizes its parent element's `category` and
   `built_in_category`, so a parameter can be associated with a category even if
   an element row is missing.
3. DiscoveryHarness tolerates `int`/`str` `element_id` representation drift and,
   if a parameter table has rows but none join to `elements.jsonl`, it retries
   the join against `elements.parquet` (same writer ⇒ guaranteed match) before
   reporting a join mismatch.

This is what removes the PR #20 `0/1` failure: real parameter rows now carry the
same `element_id` as the elements export.

---

## 5. Enriched parameter export schema

`parameters.parquet` / `parameters.csv` / `parameters.jsonl` rows
(`PARAMETER_PARQUET_SCHEMA` in `src/axiom_core/inventory/storage.py`):

| Group | Field | Type | Notes |
| --- | --- | --- | --- |
| identity / join | `run_id` | string | run identifier |
| | `element_id` | int64 | **stable join key → elements** |
| | `category` | string | denormalized parent category name |
| | `built_in_category` | string | `OST_*` where available |
| | `param_name` | string | parameter name |
| | `built_in_parameter_id` | string | e.g. `ALL_MODEL_INSTANCE_COMMENTS` |
| ownership | `is_instance_param` | bool | instance-level parameter |
| | `is_type_param` | bool | type-level parameter (`= not is_instance_param`) |
| storage / access | `storage_type` | string | `String` / `Integer` / `Double` / `ElementId` |
| | `is_read_only` | bool | writability |
| value | `value_string` | string | display/string value |
| | `value_number` | double | numeric value (Double) |
| | `value_integer` | int64 | integer value |
| | `value_element_id` | int64 | referenced element id (ElementId) |
| value contract | `spec_type_id` | string | spec/data type (ForgeTypeId) |
| | `forge_type_id` | string | explicit ForgeTypeId when distinct |
| | `unit_type_id` | string | unit ForgeTypeId |
| | `display_unit` | string | human unit label |
| | `format_options` | string | serialized format options |
| | `parameter_group` | string | parameter group label |
| discovery metadata | `parameter_source` | string | `revit_inventory_model` |
| | `discovered_at` | string | ISO-8601 UTC timestamp |

All PR #20 columns are preserved; the new columns are additive (no removals), so
older readers keep working.

### Value contract rule (carried from PR #20)

`StorageType` alone is **not** sufficient to set a parameter. A `Double` may be a
length, area, volume, angle, airflow, slope, temperature, electrical load, etc.,
so DiscoveryHarness marks a `Double` `safely_settable_by_axiom` **only** when
semantic/unit metadata (`spec_type_id` / `unit_type_id` / `display_unit`) is
present. String / Integer / ElementId writable parameters are settable directly.

---

## 6. C#-emitted vs Python-derived field boundary

This boundary matters for future adapters: an adapter only has to emit the
**C#/adapter-emitted** fields; the Python export layer derives the rest.

| Field | Source | How |
| --- | --- | --- |
| `param_name` | **C# add-in** | `Parameter.Definition.Name` |
| `storage_type` | **C# add-in** | `Parameter.StorageType` |
| `is_read_only` | **C# add-in** | `Parameter.IsReadOnly` |
| `built_in_parameter_id` | **C# add-in** | `InternalDefinition.BuiltInParameter` |
| `value_string` | **C# add-in** | `AsString` / `AsValueString` |
| `value_number` | **C# add-in** | `AsDouble` |
| `value_integer` | **C# add-in** | `AsInteger` |
| `value_element_id` | **C# add-in** | `AsElementId` (version-safe via `RevitElementIdCompat`) |
| `spec_type_id` | **C# add-in** | `Definition.GetDataType().TypeId` |
| `unit_type_id` | **C# add-in** | `UnitUtils.GetValidUnits(spec)[0].TypeId` (measurable specs) |
| `display_unit` | **C# add-in** | `LabelUtils.GetLabelForUnit(unit)` |
| `parameter_group` | **C# add-in** | `LabelUtils.GetLabelForGroup(Definition.GetGroupTypeId())` |
| `element_id` | **C# add-in** (element) | `Element.Id` — the join key, set on the parent element |
| `category` | **Python** (derived) | denormalized from parent element `Category` |
| `built_in_category` | **Python** (derived) | denormalized from parent element `BuiltInCategory` |
| `is_instance_param` | **Python** (derived) | `not element.IsType` |
| `is_type_param` | **Python** (derived) | `element.IsType` |
| `forge_type_id` | **Python** (derived) | mirrors `spec_type_id` when a distinct value is absent |
| `run_id` | **Python** (derived) | run identifier from the inventory pipeline |
| `parameter_source` | **Python** (derived) | constant `revit_inventory_model` |
| `discovered_at` | **Python** (derived) | export timestamp |

The Python flattener (`_param_to_flat`) accepts both the add-in's PascalCase keys
(`SpecTypeId`, `UnitTypeId`, …) and pre-flattened snake_case keys, so a future
adapter can hand off either shape.

> **Adapter note.** `instance_parameter` vs `type_parameter` is derived in Python
> from the element's `IsType` flag, exactly as InventoryModel already classifies
> it (`is_instance_param = not element.IsType`). The adapter only needs to set
> `IsType` correctly on each element.

---

## 7. Compatibility expectations with DiscoveryHarness

* DiscoveryHarness reads `parameters.parquet` and maps these columns onto the
  parameter dict its interpreter consumes (`_param_row_to_export`).
* With the value contract columns populated, a writable `Double` with unit
  metadata becomes `safely_settable_by_axiom = true` and generates a
  `SetParameterValue` candidate labeled instance/type.
* A legacy export (PR #20 schema, no value-contract columns) still loads; a bare
  `Double` correctly stays not-settable. No breaking change.
* Candidates are generated for writable `String` / `Integer` / `Double` /
  `ElementId` parameters, both instance and type, labeled by kind. Candidates are
  **never executed** in this scope.

---

## 8. Validation

* **Devin side (this PR):** unit tests cover the enriched schema round-trip, the
  stable join, and an end-to-end DiscoveryHarness run against a synthetic
  enriched run folder reaching `Discovery complete: YES` with parameters and
  candidates > 0. `ruff` clean, full `pytest` green.
* **AXIOM-01 / live side (pending):** run InventoryModel inside Revit 2027 in a
  parameter-collecting mode, then DiscoveryHarness against the real export, and
  confirm Categories / Parameters / Candidates > 0 and `Discovery complete: YES`.
  The C# enrichment in `ModelInventoryService.CollectParameters` is **not built
  or run on Linux** and requires the Axiom-01 dotnet build + live Revit run.

---

## 9. Limitations

* Per-element parameter collection is gated by InventoryModel scan mode and the
  established safety staging (summary → category → level → sample → full). This
  contract does not change scan gating; it only enriches what is exported when
  parameters are collected.
* `format_options` is exported as a serialized string; structured format options
  are out of scope for v1.
* SQLite parameter rows are unchanged in this PR (the discovery join consumes the
  Parquet/JSONL/CSV exports); enriching the SQLite parameter table is future work.
