# Revit Parameter Versioning Strategy

## Overview

Axiom uses **one canonical ParameterAvailability registry** rather than
maintaining separate parameter models per Revit version. Each parameter records
which Revit versions it applies to — version-specific parameters are flagged,
not forked into separate models.

---

## Concepts

### ParameterAvailability

Describes a known Revit parameter and its availability across versions.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Parameter name as exposed by the Revit API |
| `built_in_id` | string | Built-in parameter enum value (e.g. `CURVE_ELEM_LENGTH`) |
| `category` | string | Primary element category this parameter appears on |
| `storage_type` | string | `String`, `Double`, `Integer`, `ElementId` |
| `is_read_only` | bool | Whether the parameter is read-only |
| `parameter_group` | string | Revit parameter group (e.g. `PG_CONSTRAINTS`) |
| `available_versions` | list[string] | Revit versions where this parameter is confirmed present |
| `deprecated_versions` | list[string] | Revit versions where this parameter was removed or renamed |
| `replacement` | string | Replacement parameter name if deprecated |
| `source` | string | How availability was determined: `documented`, `inventory_scan`, `manual_test` |
| `notes` | string | Free-form context |

### Why One Registry, Not Per-Version Forks

1. **Most parameters are stable.** The vast majority of Revit parameters
   (built-in, project, family, shared) are identical across versions 2024–2027.
   Maintaining separate models for each version would be 95%+ duplication.

2. **InventoryModel populates availability.** When InventoryModel runs against
   a real model in a specific Revit version, it captures every parameter on
   every element. Comparing InventoryModel outputs across versions reveals
   which parameters differ — this is empirical, not speculative.

3. **Flagging is simpler than forking.** When a parameter only exists in
   certain versions, it gets an `available_versions` list. Consuming code
   can check version compatibility at query time rather than loading a
   version-specific model.

4. **Shared parameters are inherently version-agnostic.** Shared parameters
   (GUID-based) are defined in the project or family, not by the Revit API
   version. They will appear in any Revit version that opens the document.

---

## Parameter Categories

### 1. Built-In Parameters (API-Defined)

These are defined by `Autodesk.Revit.DB.BuiltInParameter` — a large enum of
parameters that Revit creates automatically for elements of each category.

**Versioning risk:** Low for established parameters. Autodesk rarely removes
built-in parameters but may add new ones in each release.

**Strategy:** Record `built_in_id` in the availability registry. After an
InventoryModel scan in a new Revit version, diff the built-in parameter set
against the baseline.

### 2. Project Parameters (User-Defined, Document-Scoped)

Defined by the user in the Revit project. Not tied to any API version.

**Versioning risk:** None — these are document data, not API surface.

**Strategy:** No version tracking needed. InventoryModel captures them through
generic enumeration.

### 3. Family Parameters (Family-Defined)

Defined in the family editor. Exposed on instances and types of that family.

**Versioning risk:** None — family-defined, not API-version-dependent.

**Strategy:** No version tracking needed.

### 4. Shared Parameters (GUID-Based, Cross-Project)

GUID-based parameters that can be shared across projects and families. Defined
in a shared parameter file.

**Versioning risk:** None — GUID-based identity is version-independent.

**Strategy:** No version tracking needed.

### 5. New/Experimental API Parameters

Parameters introduced in newer Revit versions (e.g. energy analysis, carbon
tracking, digital twin metadata). These may not exist in Revit 2024.

**Versioning risk:** High — only available in specific versions.

**Strategy:** Flag with `available_versions` in the registry. Do not assume
availability. If a capability needs these parameters, it should check the
registry before attempting access.

---

## Discovery Workflow

### Step 1: Baseline InventoryModel Scan (Revit 2024)

Run InventoryModel against a reference model in Revit 2024. This produces:

- `elements.parquet` — all elements with category, family, type, level
- `parameters.parquet` — all parameters with name, storage type, value, built-in ID

This establishes the baseline parameter set for version 2024.

### Step 2: New-Version InventoryModel Scan

Run InventoryModel against the **same reference model** in a new Revit version
(e.g. 2027). This produces an equivalent set of Parquet files.

### Step 3: Diff

Compare the two `parameters.parquet` files:

```python
import pandas as pd

baseline = pd.read_parquet("artifacts/.../2024/parameters.parquet")
new_ver = pd.read_parquet("artifacts/.../2027/parameters.parquet")

# Parameters in 2027 but not 2024
added = set(new_ver["param_name"]) - set(baseline["param_name"])

# Parameters in 2024 but not 2027
removed = set(baseline["param_name"]) - set(new_ver["param_name"])

# Parameters in both
shared = set(baseline["param_name"]) & set(new_ver["param_name"])
```

### Step 4: Update Registry

Based on the diff, update `parameter_availability_examples.yaml`:

- Newly discovered parameters → add with `available_versions: ["2027"]`
- Removed parameters → add to `deprecated_versions`
- Shared parameters → expand `available_versions` list

---

## Capability Impact

### CreateGrids

Uses `Grid.Create(Document, Line)`. The parameters involved (`HorizontalCount`,
`VerticalCount`, `SpacingFeet`) are Axiom-defined, not Revit-defined. No
version-specific parameter concerns.

The grid elements created will have standard built-in parameters
(`CURVE_ELEM_LENGTH`, etc.) that are stable across versions.

### CreateLevels

Uses `Level.Create(Document, double)`. Similar to CreateGrids — Axiom-defined
parameters (`LevelCount`, `FloorToFloorFeet`, `StartElevationFeet`) are
version-independent.

Level elements will have `LEVEL_ELEV` and similar built-in parameters that are
stable across versions.

### InventoryModel

This is the version-sensitivity probe. It reads all parameters on all elements.
If a Revit version introduces new built-in parameters or changes storage types,
InventoryModel will capture the difference automatically through generic
enumeration (`foreach (Parameter param in elem.Parameters)`).

InventoryModel does not assume which parameters exist — it discovers them. This
makes it inherently resilient to version differences.

---

## Schema Impact

### Parquet Schemas (Version-Agnostic)

The Parquet schemas (`ELEMENT_PARQUET_SCHEMA`, `PARAMETER_PARQUET_SCHEMA`) are
designed to be version-agnostic. They capture parameter metadata (name, storage
type, value, built-in ID) without encoding version-specific expectations.

No schema changes are needed for new Revit versions. The same schema accommodates
parameters from any version.

### SQLite Tables (Version-Agnostic)

The SQLite tables (`inventory_elements`, `inventory_parameters`) include a
`run_id` column that can be used to compare across versions. Each InventoryModel
run records its context (source model, timestamp) — version information can be
added to the run metadata without changing the table schema.

---

## Metadata Fixtures

Parameter availability examples are stored in:

```
tests/fixtures/compatibility/parameter_availability_examples.yaml
```

This file contains representative examples of parameters across categories and
versions. It is not exhaustive — the complete registry will be built
incrementally through InventoryModel scans.

### Fixture Structure

```yaml
parameters:
  - name: "CURVE_ELEM_LENGTH"
    built_in_id: "CURVE_ELEM_LENGTH"
    category: "Grids"
    storage_type: "Double"
    is_read_only: true
    parameter_group: "PG_GEOMETRY"
    available_versions: ["2024", "2025", "2026", "2027"]
    deprecated_versions: []
    source: "documented"
    notes: "Stable built-in parameter for linear elements."
```

---

## Anti-Patterns

1. **Do NOT create separate parameter models per Revit version.** One
   `ParameterAvailability` registry handles all versions. Fork only if a
   parameter's *type* or *meaning* changes (not just its availability).

2. **Do NOT hardcode parameter names in capability logic.** Capabilities use
   generic enumeration. Parameter names are metadata for the availability
   registry, not constants in execution code.

3. **Do NOT speculate about version differences.** Only record availability
   data that has been confirmed through `inventory_scan`, `documented`
   (Autodesk release notes), or `manual_test`.

4. **Do NOT block on parameter availability.** If a parameter is not in the
   registry for a given version, it does not prevent capability execution.
   InventoryModel will discover it at runtime and the registry can be updated.

---

## Related Documents

- [Multi-Platform Capability Intelligence](multi-platform-capability-intelligence.md) — this document is the Revit-specific instantiation of the ProductPropertyRegistry concept
- [Revit Version Compatibility Strategy](revit-version-compatibility-strategy.md)
- [Model Inventory Runbook](../runbooks/model-inventory-runbook.md)
- [Capability Creation Checklist](capability-creation-checklist.md)
