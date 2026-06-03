# Discovery Harness v1 - Design Packet (PR #20)

> Status: **DESIGN / PROPOSAL** - no implementation in this packet. Implementation
> begins only after PR #19 (Automation Bridge v0) is merged. This document is the
> agreed design surface to review before code is written.

## 1. Objective

Build the first autonomous **Discovery Harness** for Axiom - the knowledge-acquisition
step of the Verification Factory. It autonomously **discovers, catalogs, validates the
shape of, and persists** knowledge about the Revit world, using **InventoryModel** as the
initial discovery substrate.

This is **discovery only**. The goal is not workflow generation, learning, scoring,
promotion, retry, or autonomous modification. It produces the durable foundation that
future Capability-Learning, Promotion, and Workflow-Discovery loops build on.

### Layering principle (non-negotiable)

DiscoveryHarness **sits above InventoryModel and never duplicates extraction logic.**
InventoryModel is the single source of truth for raw category / element / parameter
extraction. DiscoveryHarness is a **pure transformer** that consumes InventoryModel's
already-exported artifacts and converts them into ProductObjectRegistry,
ProductPropertyRegistry, DiscoveryEvidence, discovery run reports, and candidate capability
definitions. It re-uses those artifacts **directly**; it only adds a field if a registry or
evidence record genuinely requires one InventoryModel does not already export, and even then
the missing field is derived from existing InventoryModel output (e.g. a timestamp or the
`adapter` constant), never by re-scanning the model.

The next bottleneck is no longer execution (proven by PR #19's bridge). The next
bottleneck is **knowledge acquisition** - Axiom building its own model of the Revit world.

## 2. Strategic placement

```
[Verification Factory]
  1. DISCOVERY          <-- this PR (v1): categories, parameters, candidates
  2. Primitive Validation   (future: validate candidates via Validation Loop + Bridge)
  3. Failure Classification (future)
  4. Bounded Retry          (future)
  5. Evidence               (this PR produces discovery evidence; reused downstream)
  6. Promotion Score        (future)
  7. Trusted Pattern Registry (future)
```

This PR stops at **candidate capability generation**. No autonomous execution beyond
read-only discovery.

## 3. Scope

Clean architecture (fixed):
```
Revit Model
   |
   v
InventoryModel        <- raw facts / exports (single source of extraction)
   |
   v
DiscoveryHarness      <- interpreted facts (pure interpreter; no extraction)
   |
   v
Registries + Evidence + Candidate Capabilities
```

In scope (v1):
- **Interpret** InventoryModel's existing exports into **Category** and **Parameter**
  discoveries (read-only; no model modification; no workflow execution).
- Persist discoveries into two registries + durable evidence + human-reviewable reports.
- Generate (but never execute/validate/promote) **candidate capability** definitions.

Explicitly **NOT** in scope (DiscoveryHarness is a pure interpreter, not an extractor):
- **No new category scanner.**
- **No new parameter scanner.**
- **No duplicate export format** - reuse InventoryModel's existing exported artifacts.
- **No second inventory pipeline** - obtaining inventory remains InventoryModel's job
  (invoked separately or over the PR #19 bridge); the harness only reads what InventoryModel
  already produced.

Out of scope (future PRs): capability scoring, promotion engine, learning engine,
workflow generation, autonomous execution, retries, human escalation, external adapters,
Autodesk Assistant integration, MCP integration, multi-product support.

## 4. Architecture & data flow

```
                         (read-only)
  InventoryModel  ----------------------------->  DiscoveryHarness
  (summary / category / parameter-schema scans)        |
                                                        | enumerate categories
                                                        | enumerate parameters
                                                        | classify parameters
                                                        v
                       +--------------------+   +---------------------+
                       | ProductObjectReg.  |   | ProductPropertyReg. |
                       | (categories)       |   | (parameters)        |
                       +--------------------+   +---------------------+
                                                        |
                                                        v
                              CandidateCapabilityGenerator (definitions only)
                                                        |
            +-------------------------+-----------------+
            v                         v                 v
     DiscoveryEvidence          Discovery Reports   summary metrics
  (per-discovery records)   artifacts/discovery_runs/<run_id>/
```

Two input sources for the InventoryModel exports the harness reads (it always reads, never
scans):
- **simulate** - reads a sample/fixture InventoryModel export (off-Windows, deterministic,
  used in CI). No Revit needed.
- **live** - reads the export that InventoryModel produced on Axiom-01 (InventoryModel run
  directly or over the **Automation Bridge** PR #19: `axiom bridge-execute --capability
  InventoryModel ...`). DiscoveryHarness consumes the resulting export; it does not invoke
  the scan itself, and no new transport is introduced.

### Discovery substrate (why InventoryModel is sufficient - reuse, do not re-extract)

InventoryModel already emits exactly the data discovery needs, and the inventory storage
layer (`src/axiom_core/inventory/storage.py`) already persists it in three formats
(JSONL / SQLite / Parquet). DiscoveryHarness **reads these existing exports** rather than
re-deriving anything from the live model:

| registry / output | consumed InventoryModel artifact | mapping |
|-------------------|----------------------------------|---------|
| ProductObjectRegistry | summary / element dataset (`ELEMENT_PARQUET_SCHEMA` + summary counts) | distinct `category` + per-category element counts |
| ProductPropertyRegistry | parameter-schema dataset (`PARAMETER_SCHEMA_PARQUET_SCHEMA`) | one row per `(category, parameter_name)` |

The **parameter-schema** dataset (`PARAMETER_SCHEMA_PARQUET_SCHEMA`) carries, per category:
`parameter_name, storage_type, built_in_parameter_id, is_read_only, is_instance_param,
category, class_name, scan_mode, source_model`. That is the direct source for
ProductPropertyRegistry - **no hardcoded parameter definitions and no re-extraction**.
DiscoveryHarness imports an existing inventory run by path/run-id. It **never invokes a
scan**; if no inventory output exists, that is an input error surfaced to the caller, who
runs InventoryModel first (directly or over the PR #19 bridge).

### Safety staging (reuse InventoryModel's proven gates)

The InventoryModel runs that **feed** discovery use the existing **staged, read-only** scan
path (owned by InventoryModel, not the harness) and never trigger an unguarded full scan:
1. summary scan (counts + category breakdown) -> feeds ProductObjectRegistry
2. category scan -> per-category element counts
3. **parameter-schema scan** (`ParameterSchemaOnly=true`) -> feeds ProductPropertyRegistry
   without dumping every element's parameter values (avoids the Revit 2027 full-scan crash).
Full/sample scans remain explicit/high-risk and are **not** required by v1. DiscoveryHarness
consumes whichever of these exports already exist; it does not select or trigger scan modes.

## 5. Component design

### 5.1 ProductObjectRegistry (Deliverable 1)
Persist discovered Revit object categories (table `product_objects`).

| field | type | source |
|-------|------|--------|
| `adapter` | str | constant `"revit"` |
| `category_name` | str | InventoryModel category name (e.g. `"Walls"`) |
| `built_in_category` | str | InventoryModel `BuiltInCategory` (e.g. `OST_Walls`), when available |
| `category_id` | int\|null | InventoryModel numeric category id (e.g. `-2000011`), optional |
| `element_count` | int | instance count only (excludes type definitions) |
| `type_count` | int | type-definition count (tracked separately) |
| `last_run_id` | str | run that last touched this row |
| `discovered_at` | datetime | discovery run timestamp |

Keyed by `(adapter, category_name)`; upsert on re-discovery (latest counts + run id).

### 5.2 ProductPropertyRegistry (Deliverable 2)
Persist discovered parameters (table `product_properties`). **Source: InventoryModel
export only** (no hardcoded parameter definitions).

| field | type | source |
|-------|------|--------|
| `adapter` | str | constant `"revit"` |
| `category` | str | InventoryModel `Category` |
| `parameter_name` | str | InventoryModel parameter `Name` |
| `storage_type` | str | `StorageType` (`String`/`Integer`/`Double`/`ElementId`) |
| `read_only` | bool | parameter `IsReadOnly` |
| `instance_parameter` | bool | derived as `not element.IsType` (true=instance, false=type) |
| `built_in_parameter_id` | str | parameter `BuiltInParameterId` |
| **value contract** | | |
| `spec_type_id` | str | `SpecTypeId` / `ForgeTypeId` / `DataTypeId`, when available |
| `unit_type_id` | str | `UnitTypeId`, when available |
| `display_unit` | str | `DisplayUnit` / `UnitLabel`, when available |
| `format_options_json` | str | `FormatOptions` (JSON), when available |
| `has_value` | bool | any observed value present on the parameter |
| `sample_values_json` | str | up to 5 distinct observed string values |
| `expected_input_format` | str | computed SetParameterValue input hint |
| `safely_settable_by_axiom` | bool | computed safety gate (see §5.6) |
| `last_run_id` | str | run that last touched this row |
| `discovered_at` | datetime | discovery run timestamp |

Keyed by `(adapter, category, parameter_name, instance_parameter)` so a parameter
observed as **both** an instance and a type parameter is recorded as two correctly
labeled rows. Upsert on re-discovery.

### 5.3 DiscoveryHarness (Deliverable 3)
Read-only **interpreter** service (does not extract/scan):
1. load an existing InventoryModel export (simulate: fixture; live: the export produced by
   an InventoryModel run / bridge call),
2. interpret categories -> ProductObjectRegistry,
3. interpret parameters -> classify (storage type, read-only, instance/type) ->
   ProductPropertyRegistry,
4. emit DiscoveryEvidence per discovery event,
5. generate candidate capabilities,
6. write reports + metrics.

No extraction, no new scanner, no mutations, no `SetParameterValue` execution, no retries.
Pure interpret -> persist.

### 5.4 DiscoveryEvidence (Deliverable 4)
One record per discovery event (append-only, JSONL, consistent with existing evidence ledgers):

```json
{
  "run_id": "drun_20260603_101500",
  "discovery_type": "parameter",        // "category" | "parameter" | "candidate"
  "adapter": "revit",
  "object": "Walls",                     // category name
  "property": "Comments",                // parameter name (null for category events)
  "result": "discovered:instance",       // labeled with parameter_kind where applicable
  "timestamp": "2026-06-03T10:15:02Z"
}
```

### 5.5 CandidateCapabilityGenerator (Deliverable 6)
From writable parameters, generate **candidate** capability definitions (table
`candidate_capabilities`). **Stored, never executed, validated, or promoted.**
Candidates seed future validation loops.

v1 rule: a writable (non-read-only) parameter whose storage type is in
`{String, Integer, Double, ElementId}` produces one `SetParameterValue` candidate.
Candidates are generated for **both instance and type parameters**, each labeled with
its `parameter_kind` (`instance`/`type`). Read-only or unsupported-type parameters are
cataloged in the property registry but do not produce candidates. Each candidate carries
the value contract (`spec_type_id`, `unit_type_id`, `expected_input_format`,
`safely_settable_by_axiom`) so the future validation loop can gate on safety.

Example: discovery `{Walls, Comments, writable, String, instance}` ->
```json
{
  "candidate_id": "cand_revit_walls_comments_instance_setparametervalue",
  "capability": "SetParameterValue",
  "adapter": "revit",
  "category": "Walls",
  "parameter_name": "Comments",
  "parameter_kind": "instance",
  "storage_type": "String",
  "expected_input_format": "text",
  "safely_settable_by_axiom": true,
  "status": "candidate"
}
```

### 5.6 Parameter value contract (safety gate)
**StorageType alone is NOT sufficient.** A `Double` may represent length, area, volume,
angle, airflow, slope, temperature, electrical load, etc. The interpreter therefore
computes `safely_settable_by_axiom` as:

- `false` if the parameter is read-only;
- `false` if the storage type is not in `{String, Integer, Double, ElementId}`;
- for `Double` specifically: `false` unless semantic/unit metadata
  (`spec_type_id` **or** `unit_type_id` **or** `display_unit`) is present;
- otherwise `true`.

These fields are read from the InventoryModel export where present (no new scanner).
Where the current export does not yet emit unit/spec metadata, the field is recorded as
empty and `Double` parameters correctly fall to `safely_settable_by_axiom = false` until
InventoryModel surfaces that metadata.

## 6. Reports & metrics (Deliverables 5 + 7)

Outputs under `artifacts/discovery_runs/<run_id>/`:
- `summary.json` - machine-readable run summary + metrics (below)
- `summary.md` - human-reviewable summary (ASCII, PowerShell-safe per prior ledger fixes)
- `categories.csv` - one row per discovered category (registry projection)
- `parameters.csv` - one row per discovered parameter, incl. value-contract columns
- `candidate_capabilities.csv` - one row per generated candidate (labeled instance/type)
- `discovery_evidence.jsonl` - append-only evidence records

Metrics (in `summary.json` and `summary.md`):
`categories_discovered, parameters_discovered, writable_parameters, read_only_parameters,
instance_parameters, type_parameters, safely_settable_parameters,
candidate_capabilities_generated`.

## 7. Reuse of existing infrastructure

- **InventoryModel** (PR #5) + inventory storage (`src/axiom_core/inventory/storage.py`) -
  discovery substrate and persistence patterns (JSONL/SQLite/Parquet). DiscoveryHarness
  **reads InventoryModel's exported artifacts directly and never re-implements extraction**
  (see §1 layering principle). Inventory exports are imported by path/run-id; the harness
  never triggers a scan and never defines a new export format.
- **Automation Bridge** (PR #19) - the live read-only execution path; no new transport.
- **CapabilityRegistry** patterns (`src/axiom_core/capability_registry.py`) - dataclass +
  in-memory registry + persistence conventions for the two new registries.
- **Evidence/ledger conventions** (`docs/logs/`, `artifacts/`) - durable, separate from
  runtime logic.
- Persistence: prefer the existing SQLite/Parquet approach already used by inventory rather
  than introducing new infrastructure.

## 8. CLI surface (implemented)

```
axiom discovery-run --adapter revit [--simulate]
                    [--inventory-export-path <export.json>] [--run-id <id>]
                    [--output-dir artifacts/discovery_runs] [--db-path <discovery.db>]
```
- `--simulate` interprets a built-in deterministic export (CI/off-Windows); live mode
  requires `--inventory-export-path` pointing at an export InventoryModel already produced
  (via a run or the PR #19 bridge).
- `--db-path` is optional: when supplied the interpreted facts are persisted into the
  shared SQLite schema; when omitted the run produces file artifacts only.
- Non-interactive; exit 0 on a successful discovery run, exit 2 on bad args / missing
  export (mirrors `bridge-execute` / `validation-run`).

### Supported `--inventory-export-path` inputs

A real InventoryModel run folder **splits** the data across files: elements/categories
live in `elements.jsonl` / `elements.parquet`, while per-element **parameters** live in
`parameters.parquet`. Pointing at `elements.jsonl` alone therefore discovers categories
but **zero parameters** (and zero candidates). To get full discovery, point
`--inventory-export-path` at the **run folder** so the harness can join the parameter
table back onto the elements.

| Input | Shape | Result |
| --- | --- | --- |
| **run FOLDER** (`artifacts/model_inventory_runs/<run_id>/`) | auto-detects `elements.jsonl`/`elements.parquet` (objects) + `parameters.parquet` (parameters) + `run_metadata.json` (provenance) | **supported (recommended)** - full discovery |
| handoff `.json` | a JSON object with an `elements` list (parameters embedded) | supported |
| `.json` array | a JSON array of element records | supported |
| `elements.jsonl` (file) | one element record per line; **no parameters** | supported, but **category-only** (incomplete) |
| `parameters.jsonl` / `parameter_schema.jsonl` | parameter-**schema** rows (no per-element `Parameters`) | **rejected** with guidance |

**Folder contract.** When given a folder the loader reads objects from `elements.jsonl`
(or `elements.parquet`), reads `parameters.parquet`, and joins parameters onto their
elements by `element_id`. `run_metadata.json` supplies provenance (`source_model`,
scan/chunk mode). `parameters.parquet` carries no unit/spec metadata, so a `Double`
parameter correctly stays `safely_settable_by_axiom = false` (value contract preserved).

**Completeness.** `discovery_complete` keys off **parameters actually discovered**, not
merely whether a parameter file was detected. Any run with zero parameters is reported as
`discovery_complete: false` (also `discovery_parameter_complete: false`) with a precise
reason in `warnings`, and `summary.json` exposes `parameter_rows_total` /
`parameter_rows_joined` so the cause is explicit:

| Situation | Reported reason |
| --- | --- |
| no parameter source (e.g. `elements.jsonl` alone) | "Parameter source missing/not provided ... category-only" |
| `parameters.parquet` present but 0 rows (summary/schema-only) | "contained no usable parameter rows (empty or schema-only) ... re-run InventoryModel in full-detail mode" |
| `parameters.parquet` has rows but none match elements | "had N rows but none matched elements by element_id (join key mismatch)" |

When the join produces nothing but rows exist, the loader retries against
`elements.parquet` (same writer => guaranteed `element_id` match) before reporting a
mismatch, and id matching tolerates int/str differences. `summary.md` shows
`Parameter Source`, `Parameter Rows (joined/total)`, `Discovery Complete`, and a
**Warnings** section; the CLI prints the same. Category-only / empty-source discovery is
**never** silently reported as complete.

**Robustness.** `parameters.jsonl` / `parameter_schema.jsonl` are rejected early with a
clear, human-readable error rather than silently misinterpreted; malformed JSONL produces
a line-numbered error, never a raw parser traceback. This is purely input-reading - the
read-only / no-mutation scope is unchanged.

## 9. Acceptance criteria

A successful discovery run must:
1. execute against a running Revit model (live) or sample substrate (simulate),
2. discover categories, 3. discover parameters, 4. populate both registries,
5. generate evidence, 6. generate reports, 7. generate candidate capabilities,
8. produce summary metrics - all under `artifacts/discovery_runs/<run_id>/`.

## 10. Limitations (v1)

- Discovery quality is bounded by InventoryModel's staged scans; no full-scan dump.
- Candidates are heuristic definitions only - **unvalidated, unscored, unpromoted**.
- Single adapter (`revit`); registries carry an `adapter` field for future generalization
  but multi-product is out of scope.
- No deduplication/merge policy beyond simple upsert-by-key in v1.

## 11. Definition of done (for the implementation PR)

- ProductObjectRegistry, ProductPropertyRegistry, DiscoveryHarness, DiscoveryEvidence,
  CandidateCapabilityGenerator implemented.
- Tests added (deterministic, simulate path against sample inventory); existing tests pass;
  ruff clean.
- Discovery artifacts generated; registries populated; evidence + candidates + metrics
  generated; docs updated.
- Live discovery proven on Axiom-01 / Revit 2027 via the Bridge (read-only), no human
  interaction after dispatch.

## 12. Design decisions (resolved)

1. **Registry persistence** - reuse the PR #1 SQLite persistence stack
   (`axiom_core.database` + the shared SQLAlchemy `Base`/`axiom_core.models`). No new
   database or storage layer is introduced; three tables are added: `product_objects`,
   `product_properties`, `candidate_capabilities`.
2. **Candidate scope** - generate `SetParameterValue` candidates where InventoryModel
   evidence shows the parameter is writable and the storage type is in
   `{String, Integer, Double, ElementId}`. Candidates cover **both instance and type**
   parameters, each labeled with `parameter_kind`. Candidates are stored, never executed
   in PR #20.
3. **CLI name** - `axiom discovery-run`.
4. **CSV outputs** - per-run `categories.csv`, `parameters.csv`, and
   `candidate_capabilities.csv`, plus `summary.json` and `summary.md`, under
   `artifacts/discovery_runs/<run_id>/`.
5. **Value contract** - every discovered parameter captures semantic/unit metadata where
   available and a computed `safely_settable_by_axiom` gate (see §5.6). StorageType alone
   is not treated as sufficient; `Double` requires unit/spec metadata to be settable.
