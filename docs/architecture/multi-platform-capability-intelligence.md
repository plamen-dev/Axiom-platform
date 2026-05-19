# Multi-Platform Capability Intelligence

## Vision

Axiom is a **capability-learning platform** that discovers, models, and
automates operations across design/engineering software environments. Revit is
the first proving ground — not the permanent boundary.

The architecture separates three concerns:

1. **Axiom Core** — product-agnostic orchestration, learning, and storage
2. **Product Adapters** — thin bridges that connect Axiom to specific software
   (Revit, Inventor, SolidWorks, ArchiCAD, etc.)
3. **Capabilities** — executable operations that are registered, versioned,
   tested, and improved through structured learning loops

Agents coordinate. Capabilities execute. Adapters connect. Registries catalog.

---

## Core Concepts

### 1. ProductAdapter

A thin integration layer that connects Axiom Core to a specific external
software product. Each adapter is responsible for:

- Establishing a communication channel (pipe, API, COM, gRPC, etc.)
- Translating Axiom-generic operations into product-specific API calls
- Translating product-specific responses back into Axiom-generic structures
- Reporting product version and runtime information

A ProductAdapter does NOT contain capability logic. It provides the bridge that
capabilities use to reach the external software.

| Field | Type | Description |
|-------|------|-------------|
| `adapter_id` | string | Unique adapter identifier (e.g. `"revit"`, `"inventor"`) |
| `product_name` | string | Display name of the product |
| `vendor` | string | Software vendor (e.g. `"Autodesk"`, `"Graphisoft"`, `"Dassault"`) |
| `communication_protocol` | string | How Axiom talks to the product (`named_pipe`, `com`, `grpc`, `rest`, etc.) |
| `supported_versions` | list | Product versions this adapter supports |
| `status` | string | `active`, `planned`, `experimental`, `deprecated` |

**Revit example (Adapter 001):**

```
adapter_id: "revit"
product_name: "Autodesk Revit"
vendor: "Autodesk"
communication_protocol: "named_pipe"
supported_versions: ["2024", "2025", "2026", "2027"]
status: "active"
```

The Revit adapter currently consists of:

| Component | Location | Purpose |
|-----------|----------|---------|
| C# add-in | `src/axiom_revit/Axiom.RevitAddin/` | Hosts capabilities inside Revit process |
| Pipe bridge | `Axiom.RevitAddin/PipeBridge.cs` | Named pipe server for Python↔C# communication |
| Pipe client | `src/axiom_core/pipe_client.py` | Python-side pipe connection |
| Prompt dispatcher | `Axiom.RevitAddin/PromptDispatcher.cs` | C#-side prompt resolution (redundant with Python resolver) |

---

### 2. ProductObjectRegistry

Catalogs the object types available in a product. In Axiom-generic terms, a
**product object** is any discrete entity that the product manages — elements,
components, features, nodes, etc.

| Field | Type | Description |
|-------|------|-------------|
| `object_type` | string | Generic name (e.g. `"wall"`, `"grid"`, `"level"`, `"part"`, `"layer"`) |
| `product_type_name` | string | Product-specific type name (e.g. Revit's `"Wall"`, Inventor's `"Part"`) |
| `adapter_id` | string | Which adapter this object belongs to |
| `category` | string | Product-specific category grouping |
| `is_type` | bool | Whether this is a type definition (vs. instance) |
| `discoverable` | bool | Whether DiscoveryHarness can enumerate instances |

**Terminology mapping:**

| Axiom Generic | Revit | Inventor | SolidWorks | ArchiCAD |
|---------------|-------|----------|------------|----------|
| Object | Element | Component / Feature | Feature / Body | Element |
| Object Type | Family Type | Content Center item | Template | Library Part |
| Object Instance | Element instance | Occurrence | Instance | Placed element |
| Container | Document / Model | Assembly / Part | Assembly / Part | Project |
| Spatial Reference | Level | Work Plane | Reference Plane | Story |

**Revit example:**

InventoryModel is the first ProductObject discovery capability. It enumerates
all elements and their metadata through generic enumeration
(`elem.Parameters`), producing structured outputs that populate this registry.

---

### 3. ProductPropertyRegistry

Catalogs the properties (attributes, parameters, fields) available on product
objects. This is the generalization of the Revit-specific
[ParameterAvailability](revit-parameter-versioning-strategy.md) concept.

| Field | Type | Description |
|-------|------|-------------|
| `property_name` | string | Generic property name |
| `product_property_name` | string | Product-specific name (e.g. Revit's `"CURVE_ELEM_LENGTH"`) |
| `adapter_id` | string | Which adapter this property belongs to |
| `object_types` | list[string] | Which object types expose this property |
| `data_type` | string | `string`, `number`, `integer`, `boolean`, `reference` |
| `is_read_only` | bool | Whether the property is writable |
| `available_versions` | list[string] | Product versions where this property exists |

**Terminology mapping:**

| Axiom Generic | Revit | Inventor | SolidWorks | ArchiCAD |
|---------------|-------|----------|------------|----------|
| Property | Parameter | iProperty / Attribute | Custom Property | Property |
| Property Group | Parameter Group | Property Set | Configuration | Classification |
| Built-in Property | Built-in Parameter | System iProperty | System Property | Built-in Property |
| User Property | Project/Shared Parameter | User iProperty | Custom Property | User Property |

**Revit example:**

The `parameter_availability_examples.yaml` fixture contains 12 built-in Revit
parameter examples mapped to the ProductPropertyRegistry format. InventoryModel
populates this registry empirically through generic enumeration — see
[Revit Parameter Versioning Strategy](revit-parameter-versioning-strategy.md).

---

### 4. ProductFunctionRegistry

Catalogs the atomic operations (API calls) available in a product. A
**product function** is a single API method that creates, modifies, reads,
or deletes a product object.

| Field | Type | Description |
|-------|------|-------------|
| `function_name` | string | Generic name (e.g. `"create_grid"`, `"create_level"`) |
| `product_api_method` | string | Product-specific API call (e.g. `"Grid.Create(Document, Line)"`) |
| `adapter_id` | string | Which adapter this function belongs to |
| `operation_type` | string | `create`, `read`, `update`, `delete`, `query` |
| `inputs` | list | Required input parameters |
| `outputs` | list | What the function returns |
| `is_transactional` | bool | Whether it requires a transaction/undo context |
| `available_versions` | list[string] | Product versions where this function exists |

**Revit examples:**

| Function | API Method | Operation | Transactional |
|----------|-----------|-----------|---------------|
| `create_grid` | `Grid.Create(Document, Line)` | create | Yes |
| `create_level` | `Level.Create(Document, double)` | create | Yes |
| `enumerate_elements` | `FilteredElementCollector` | query | No |
| `read_parameters` | `Element.Parameters` enumeration | read | No |

Capabilities compose product functions. A single capability may call multiple
product functions in sequence within a transaction.

---

### 5. CapabilityRegistry

The existing Axiom capability registry — already implemented in
`src/axiom_core/capability_registry.py`. This document elevates it to a
platform-level concept.

A **capability** is a named, parameterized, testable operation that Axiom can
execute against a product. Capabilities are:

- **Registered** with metadata (name, description, parameter schema, status)
- **Resolved** from natural language prompts by the prompt resolver
- **Executed** through the adapter's communication channel
- **Simulated** without the external product for testing
- **Versioned** against product versions via CapabilityCompatibility

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | PascalCase capability name |
| `adapter_id` | string | Which product adapter this capability targets |
| `description` | string | Human-readable one-liner |
| `parameter_schema` | dict | JSON Schema for capability parameters |
| `supports_simulate` | bool | Whether simulation mode is available |
| `requires_product` | bool | Whether an open product document is needed |
| `status` | string | `planned`, `validated`, `deprecated` |

**Current registered capabilities:**

| Capability | Adapter | Status | Harness |
|-----------|---------|--------|---------|
| CreateGrids | revit | validated | 31/31 simulate |
| CreateLevels | revit | validated | 18/18 simulate |
| InventoryModel | revit | validated | 58 pytest tests |

See [Capability Creation Checklist](capability-creation-checklist.md) for the
repeatable process of adding new capabilities.

See [Capability Design Pattern](capability-design-pattern.md) for the template
every capability should follow.

---

### 6. VersionCompatibilityRegistry

Tracks which capabilities work with which product versions, at what validation
stage. This is the generalization of the Revit-specific
[Version Compatibility Strategy](revit-version-compatibility-strategy.md).

| Field | Type | Description |
|-------|------|-------------|
| `capability` | string | Capability name |
| `adapter_id` | string | Product adapter |
| `product_version` | string | Product version |
| `status` | string | VersionValidationStatus (see below) |
| `last_tested` | string | ISO date |
| `notes` | string | Free-form context |

**VersionValidationStatus progression:**

```
planned → simulated → build_validated → startup_validated → real_validated
                                                              ↓ (if broken)
                                                           failed
```

| Status | Meaning |
|--------|---------|
| `planned` | Support intended, no work started |
| `simulated` | Python simulation passes |
| `build_validated` | Compiles against product version's API |
| `startup_validated` | Adapter loads in product without errors |
| `real_validated` | Capability executes correctly with real data |
| `failed` | Validation failed — see notes |
| `deprecated` | No longer targeting this version |

**Revit example:**

The `capability_compatibility.yaml` fixture tracks CreateGrids, CreateLevels,
and InventoryModel across Revit 2024–2027. See
[Revit Version Compatibility Strategy](revit-version-compatibility-strategy.md)
for the full Revit-specific details.

---

### 7. CodeRecipeRegistry

Catalogs reusable patterns of product function composition. A **code recipe**
is a proven sequence of API calls that accomplishes a specific outcome.

Code recipes sit between raw product functions and high-level capabilities:

```
ProductFunction  →  CodeRecipe  →  Capability
(atomic API call)   (proven pattern)  (parameterized operation)
```

| Field | Type | Description |
|-------|------|-------------|
| `recipe_name` | string | Descriptive name |
| `adapter_id` | string | Product adapter |
| `functions_used` | list[string] | ProductFunctions composed in this recipe |
| `pattern` | string | Pseudocode or description of the composition |
| `source` | string | How discovered: `manual`, `inventory_derived`, `documentation` |
| `validated` | bool | Whether tested against a real product |

**Revit examples:**

| Recipe | Functions | Pattern |
|--------|-----------|---------|
| Create uniform grid system | `create_grid` × N | Loop: create vertical grids at uniform X offsets, then horizontal grids at uniform Y offsets |
| Create levels at uniform height | `create_level` × N | Loop: create level at `start + i * spacing` for each index |
| Full model inventory | `enumerate_elements` + `read_parameters` | Collect all elements via FilteredElementCollector, iterate Parameters on each |

Code recipes are discovered through:

1. Manual implementation (current: CreateGrids, CreateLevels)
2. InventoryModel output analysis (future: identify common parameter patterns)
3. Documentation mining (future: extract patterns from product API docs)

---

### 8. DiscoveryHarness

A structured process for enumerating what a product can do and what data it
contains. The DiscoveryHarness drives the population of ProductObject,
ProductProperty, and ProductFunction registries.

| Field | Type | Description |
|-------|------|-------------|
| `harness_name` | string | Descriptive name |
| `adapter_id` | string | Product adapter |
| `discovery_type` | string | `object_scan`, `property_scan`, `function_probe`, `version_diff` |
| `outputs` | list[string] | What registries this harness populates |
| `requires_product` | bool | Whether the product must be running |

**Revit example:**

InventoryModel is the first DiscoveryHarness implementation:

| Aspect | Detail |
|--------|--------|
| Harness | `InventoryModel` capability |
| Discovery type | `object_scan` + `property_scan` |
| Outputs | ProductObjectRegistry (elements), ProductPropertyRegistry (parameters) |
| Storage | JSONL + SQLite + Parquet per run |
| Version diff | Compare Parquet outputs across Revit versions to identify API changes |

The DiscoveryHarness concept generalizes to other products:

- **Inventor:** Enumerate parts/assemblies and their iProperties
- **SolidWorks:** Enumerate features/bodies and their custom properties
- **ArchiCAD:** Enumerate elements and their GDL parameters

---

### 9. CapabilityLearningLoop

A deterministic test/discovery cycle that repeatedly exercises capabilities,
logs structured results, and makes regressions/improvements measurable.

The learning loop is NOT AI/ML-based. It is a structured testing pipeline:

```
┌──────────────────────────────────────────────┐
│                                              │
│   Test Cases  →  Execute  →  Log Results     │
│       ↑                          ↓           │
│       │                    Store Artifacts    │
│       │                    (JSONL/Parquet)    │
│       │                          ↓           │
│       │                  Compare to Baseline  │
│       │                          ↓           │
│       └──────── Update Cases ◄── Report      │
│                                              │
└──────────────────────────────────────────────┘
```

| Component | Description |
|-----------|-------------|
| Test cases | Structured YAML/JSON fixtures with prompt, expected params, expected result |
| Execution modes | `simulate` (no product) and `real` (product required) |
| Storage | JSONL (append-only events), Parquet (structured datasets), SQLite (queryable history) |
| Summary report | Pass/fail counts, failure categories, regression comparison |
| Regression comparison | Diff current run against previous Parquet to identify newly passing/failing tests |

**Revit examples:**

| Loop | Test Cases | Harness CLI |
|------|-----------|-------------|
| Grid learning loop | 31 cases | `axiom test-grids --mode simulate` |
| Level learning loop | 18 cases | `axiom test-levels --mode simulate` |
| Inventory review | 58 pytest tests | `axiom inventory-summary --latest` |

See [Grid Learning Loop Runbook](../runbooks/grid-learning-loop-runbook.md)
for the reference implementation.

---

## Revit as Adapter 001

Revit is Axiom's first and most mature product adapter. It serves as the
proving ground for every platform concept:

| Platform Concept | Revit Implementation | Status |
|------------------|---------------------|--------|
| ProductAdapter | C# add-in + named pipe bridge | Active |
| ProductObjectRegistry | InventoryModel element scan | Simulated |
| ProductPropertyRegistry | InventoryModel parameter enumeration | Simulated |
| ProductFunctionRegistry | Grid.Create, Level.Create, FilteredElementCollector | Documented |
| CapabilityRegistry | CreateGrids, CreateLevels, InventoryModel | Validated (simulation) |
| VersionCompatibilityRegistry | 2024 baseline, 2025–2027 planned | Fixture metadata exists |
| CodeRecipeRegistry | Uniform grid, uniform levels, full inventory patterns | Documented |
| DiscoveryHarness | InventoryModel | Simulated, pending real Revit |
| CapabilityLearningLoop | test-grids (31/31), test-levels (18/18) | Active |

### What Revit Has Proven

1. **Shared capability system works.** Three capabilities (CreateGrids,
   CreateLevels, InventoryModel) share one registry, one resolver, one
   execution pipeline, and one telemetry system.

2. **Simulation enables development without the product.** All capabilities
   can be tested in `simulate` mode on any OS, without Revit installed.

3. **Structured learning loops catch regressions.** The grid and level
   harnesses identified BUG-001 (ambiguous row/column prompts) and BUG-002
   (mock validation gap) before any real Revit testing.

4. **Generic enumeration discovers the unknown.** InventoryModel captures
   all parameters without hardcoding names — this pattern generalizes to
   any product with an enumerable object/property model.

5. **Version metadata is separable from capability logic.** The compatibility
   fixtures track version status without polluting capability source code.

### What Revit Has Not Yet Proven

1. **Real Revit execution** — pending Windows validation environment
2. **Multi-version builds** — 2027 .csproj files not yet created
3. **Cross-version parameter diffing** — requires two real InventoryModel scans
4. **BUG-003/004/005** — C# DTO gaps pending real Revit validation

---

## Placeholder: Inventor Adapter

**Status:** Placeholder only. No implementation.

| Aspect | Notes |
|--------|-------|
| Product | Autodesk Inventor |
| Vendor | Autodesk |
| Communication | COM Automation / Inventor API (in-process or out-of-process) |
| Runtime | .NET (version depends on Inventor release) |
| Object model | Parts, Assemblies, Features, Sketches, Parameters |
| Property model | iProperties (system + custom), Model Parameters |
| Discovery | Enumerate parts in assembly, enumerate features in part, enumerate iProperties |
| Potential first capabilities | `InventoryAssembly` (read-only scan), `CreateSketch`, `AddExtrusion` |
| Relationship to Revit adapter | Same vendor (Autodesk), different API. Potential for shared Autodesk adapter patterns. |

**Key differences from Revit:**

- Inventor is parametric solid modeling, not BIM
- No concept of "levels" — uses work planes instead
- Parameters are deeply tied to feature history
- Assembly/part hierarchy is more nested than Revit's flat element model

---

## Placeholder: SolidWorks Adapter

**Status:** Placeholder only. No implementation.

| Aspect | Notes |
|--------|-------|
| Product | Dassault SolidWorks |
| Vendor | Dassault Systèmes |
| Communication | COM Automation / SolidWorks API |
| Runtime | .NET Framework or .NET (version-dependent) |
| Object model | Parts, Assemblies, Features, Bodies, Sketches |
| Property model | Custom Properties, Configuration-specific Properties |
| Discovery | Traverse FeatureManager tree, enumerate custom properties |
| Potential first capabilities | `InventoryPart` (read-only scan), `CreateSketchProfile`, `AddBoss` |
| Relationship to Revit adapter | Different vendor, similar COM-based communication pattern. |

**Key differences from Revit:**

- Feature tree is the primary organizational structure (vs. Revit's element categories)
- Configurations create variants of the same part (no direct Revit equivalent)
- BOMs (Bill of Materials) are a key output, similar to Revit schedules
- No concept of "elements" — uses features, bodies, and faces

---

## Placeholder: ArchiCAD Adapter

**Status:** Placeholder only. No implementation.

| Aspect | Notes |
|--------|-------|
| Product | Graphisoft ArchiCAD |
| Vendor | Graphisoft (Nemetschek Group) |
| Communication | JSON-based API / GDL scripting / Python API |
| Runtime | Python (ArchiCAD Python API), C++ (add-ons) |
| Object model | Elements (Walls, Slabs, Columns, Beams, Objects), Library Parts |
| Property model | Built-in Properties, User-defined Properties, GDL Parameters |
| Discovery | Enumerate elements by type, enumerate properties per element |
| Potential first capabilities | `InventoryModel` (read-only scan), `CreateStory`, `PlaceObject` |
| Relationship to Revit adapter | Competing BIM platform — similar concepts (stories ≈ levels, library parts ≈ families) with different API patterns. |

**Key differences from Revit:**

- Stories (≈ levels) and layers are the primary organizational concepts
- Library parts (≈ families) use GDL scripting, not family editor
- JSON-based API is more modern than Revit's COM-style API
- Python API is native — no need for a C# bridge layer
- IFC interoperability is deeper than Revit's

---

## Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Axiom Core                         │
│  (Python — product-agnostic)                            │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Capability   │  │ Prompt       │  │ Learning     │  │
│  │ Registry     │  │ Resolver     │  │ Loop Engine  │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Agent Layer  │  │ Telemetry    │  │ Storage      │  │
│  │ (coord only) │  │              │  │ (JSONL/SQL/  │  │
│  │              │  │              │  │  Parquet)    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└───────────────┬─────────────┬─────────────┬─────────────┘
                │             │             │
        ┌───────▼───────┐ ┌──▼──┐ ┌────────▼────────┐
        │ Revit Adapter │ │ ... │ │ Future Adapters  │
        │ (C# + pipe)   │ │     │ │                  │
        │               │ │     │ │ Inventor         │
        │ CreateGrids   │ │     │ │ SolidWorks       │
        │ CreateLevels  │ │     │ │ ArchiCAD         │
        │ InventoryModel│ │     │ │                  │
        └───────┬───────┘ └──┬──┘ └────────┬────────┘
                │            │             │
        ┌───────▼───────┐    │    ┌────────▼────────┐
        │ Revit 2024    │    │    │ Product         │
        │ Revit 2025    │    │    │ Instances       │
        │ Revit 2027    │    │    │                 │
        └───────────────┘    │    └─────────────────┘
                             │
                     (future adapters)
```

### Axiom Core (Product-Agnostic)

The core layer must never contain product-specific logic. Current core modules:

| Module | Purpose | Product-Specific? |
|--------|---------|-------------------|
| `capability_registry.py` | Catalogs capabilities | No — capability metadata is generic |
| `prompt_resolver.py` | Resolves prompts to capabilities | No — keyword matching is generic |
| `pipe_client.py` | Communication bridge | **Partially** — pipe protocol is generic, but mock execution contains Revit-specific simulation |
| `execution_log.py` | Telemetry persistence | No |
| `testing/grid_harness.py` | Grid learning loop | **Yes** — grid-specific |
| `testing/level_harness.py` | Level learning loop | **Yes** — level-specific |
| `inventory/` | Inventory storage/review | **Partially** — storage is generic, schema fields are Revit-named |

**Refactoring guidance (future, not now):**

- Move Revit-specific mock execution from `pipe_client.py` into a Revit
  adapter module
- Rename Revit-named schema fields to generic terms where they cross the
  core boundary (e.g. `element_id` → `object_id` in core schemas)
- Keep learning loop harnesses as capability-specific (they should be, but
  the infrastructure for running them can be generic)

### Product Adapter Layer

Each adapter is responsible for:

1. **Connection management** — establish and maintain communication with the
   product (pipe, COM, REST, etc.)
2. **Capability hosting** — run capability logic inside the product process
   (for in-process adapters like Revit) or proxy to it
3. **Object/property translation** — convert product-specific types to
   Axiom-generic structures
4. **Version detection** — report which product version is running

Adapters do NOT:

- Contain orchestration logic (that's the agent layer)
- Own the capability registry (that's Axiom Core)
- Make decisions about which capability to execute (that's the resolver)

---

## Naming Discipline

To prevent Revit-specific terminology from becoming baked into the platform:

| Do NOT use in Axiom Core | Use instead | Why |
|--------------------------|-------------|-----|
| Element | Object | "Element" is Revit-specific |
| Parameter | Property | "Parameter" is Revit's term for object attributes |
| Family | Object Type Definition | Revit-specific concept |
| Level | Spatial Reference | Other products use stories, work planes, etc. |
| Workset | Collaboration Partition | Revit-specific worksharing concept |
| Document | Container / Model | More general |
| FilteredElementCollector | Object Query | Revit API class name |
| Transaction | Change Context | Not all products use explicit transactions |

**Exception:** Within the Revit adapter and Revit-specific capabilities, using
Revit terminology is correct and expected. The naming discipline applies only
to Axiom Core and cross-adapter interfaces.

**Current state:** Some Revit-named fields exist in core schemas (e.g.
`element_id` in Parquet schemas). These are acceptable for now — they were
introduced before the multi-platform architecture was defined. They can be
aliased or renamed when a second adapter is implemented.

---

## Implementation Roadmap

### Phase 1: Revit Baseline (Current)

- [x] Revit adapter (C# add-in + pipe bridge)
- [x] CreateGrids capability + learning loop
- [x] CreateLevels capability + learning loop
- [x] InventoryModel capability (discovery harness)
- [x] Version compatibility metadata fixtures
- [ ] Real Revit validation (pending Windows environment)

### Phase 2: Revit Maturity

- [ ] Real Revit 2024 validation for all capabilities
- [ ] Revit 2027 build validation (parallel .csproj)
- [ ] Cross-version InventoryModel diff
- [ ] BUG-003/004/005 resolution
- [ ] Additional Revit capabilities (ReadParameterValue, SetParameterValue, etc.)

### Phase 3: Core Generalization

- [ ] Refactor Axiom Core to use generic terminology
- [ ] Define ProductAdapter interface/protocol
- [ ] Extract Revit-specific mock logic from pipe_client.py
- [ ] Create adapter registration mechanism

### Phase 4: Second Adapter

- [ ] Select second product (Inventor, SolidWorks, or ArchiCAD)
- [ ] Implement ProductAdapter for selected product
- [ ] Implement InventoryModel equivalent (DiscoveryHarness)
- [ ] Validate shared capability registry works across adapters
- [ ] Cross-product learning loop infrastructure

---

## Relationship to Existing Architecture Docs

This document is the umbrella architecture document. It references and
contextualizes the following existing documents:

| Document | Scope | Relationship |
|----------|-------|-------------|
| [Agent Responsibility Spec](agent-responsibility-spec.md) | Agent roles and coordination rules | Defines the agent layer that sits above capabilities. Rule "Agents coordinate. Capabilities execute." originates here. |
| [Capability Design Pattern](capability-design-pattern.md) | Template for individual capabilities | Defines what every capability must include. This is the per-capability counterpart to the platform-level CapabilityRegistry concept. |
| [Capability Creation Checklist](capability-creation-checklist.md) | Step-by-step process for adding capabilities | Operational checklist. Uses CreateGrids as reference, maps CreateLevels. Applies to any adapter's capabilities. |
| [Revit Version Compatibility Strategy](revit-version-compatibility-strategy.md) | Revit-specific multi-version support | Revit-specific instantiation of the VersionCompatibilityRegistry concept. Defines RuntimeFamily, SupportedRevitVersion, thin adapter strategy. |
| [Revit Parameter Versioning Strategy](revit-parameter-versioning-strategy.md) | Revit-specific parameter availability tracking | Revit-specific instantiation of the ProductPropertyRegistry concept. Defines ParameterAvailability, discovery workflow. |
| [CreateLevels Capability Plan](create-levels-capability-plan.md) | CreateLevels implementation plan | Example of capability planning using the checklist. |

No documents are obsolete. Each covers a specific scope that this document
references but does not duplicate.

---

## Anti-Patterns

1. **Do NOT let Revit names leak into Axiom Core interfaces.** Use generic
   terms at the core boundary. Revit names are fine inside the Revit adapter.

2. **Do NOT create one monolithic adapter.** Each product gets its own adapter.
   Shared Autodesk patterns (if any) should be extracted into a shared utility,
   not baked into a single adapter.

3. **Do NOT duplicate capability logic across adapters.** If two products can
   both "create a grid," the capability metadata and test structure should be
   shared. Only the adapter-specific execution differs.

4. **Do NOT build adapters speculatively.** Each adapter should be driven by a
   real use case with a real product installation for validation.

5. **Do NOT conflate agents with adapters.** Agents coordinate workflows.
   Adapters connect to products. A MechanicalAgent might use capabilities
   from multiple adapters (e.g. Revit for placement, Inventor for sizing).
