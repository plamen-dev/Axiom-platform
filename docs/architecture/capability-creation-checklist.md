# Capability Creation Checklist v1

The repeatable process for adding any new Axiom capability.
Uses `CreateGrids` as the reference implementation.

> **Context:** This checklist applies to capabilities for any product adapter,
> not only Revit. See [Multi-Platform Capability Intelligence](multi-platform-capability-intelligence.md)
> for how capabilities fit into the broader platform architecture.

---

## Checklist Summary

| # | Step | Files / Artifacts |
|---|------|-------------------|
| 1 | [Capability Metadata](#1-capability-metadata) | `capability_registry.py` |
| 2 | [Parameter Model](#2-parameter-model) | `Models/*.cs`, `capability_registry.py` (schema) |
| 3 | [Prompt Examples](#3-prompt-examples) | `tests/fixtures/<cap>_test_cases/*.yaml` |
| 4 | [Resolver Patterns](#4-resolver-patterns) | `prompt_resolver.py`, `PromptDispatcher.cs` |
| 5 | [Validation Rules](#5-validation-rules) | `Capabilities/<Cap>Capability.cs`, `pipe_client.py` |
| 6 | [Simulation Behavior](#6-simulation-behavior) | `pipe_client.py` (`_mock_execute`) |
| 7 | [Real Revit Execution](#7-real-revit-execution) | `Services/<Cap>Service.cs`, `Capabilities/<Cap>Capability.cs` |
| 8 | [Telemetry Fields](#8-telemetry-fields) | `execution_log.py`, `models.py` |
| 9 | [Test Cases](#9-test-cases) | `tests/test_prompt_resolver.py`, `tests/fixtures/` |
| 10 | [Learning-Loop Coverage](#10-learning-loop-coverage) | `tests/fixtures/<cap>_test_cases/*.yaml`, `axiom_core/testing/` |
| 11 | [Expected Artifacts](#11-expected-artifacts) | `artifacts/<cap>_test_runs/` |
| 12 | [Runbook Updates](#12-runbook-updates) | `docs/runbooks/` |
| 13 | [Merge / Acceptance Gates](#13-merge--acceptance-gates) | PR checklist |

---

## 1. Capability Metadata

Register the capability in `src/axiom_core/capability_registry.py`:

```python
registry.register(
    CapabilityMetadata(
        name="<CapabilityName>",
        description="<One-line description>",
        parameter_schema=_SCHEMA_DICT,
        supports_simulate=True,      # Can it run without Revit?
        requires_revit_document=True, # Does it need an open Revit doc?
        status="planned",            # planned → validated after first real execution
    )
)
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | PascalCase identifier matching the C# capability class name |
| `description` | Yes | Human-readable one-liner |
| `parameter_schema` | Yes | JSON Schema dict defining all parameters |
| `supports_simulate` | Yes | Whether `--simulate` mode is supported |
| `requires_revit_document` | Yes | Whether an open Revit document is needed |
| `status` | Yes | `"planned"` (blocked from execution) or `"validated"` (executable) |

**CreateGrids reference:**

```python
name="CreateGrids"
description="Creates a grid system with vertical (numeric) and horizontal (alphabetic) grid lines."
status="validated"
```

---

## 2. Parameter Model

### Python side

Define the JSON Schema in `capability_registry.py` under a `_<CAP>_SCHEMA` dict. This schema is the contract between Python and C#.

### C# side

Create a parameter class in `Axiom.Core/Models/<Cap>Parameters.cs`:

```csharp
public class <Cap>Parameters
{
    // Required parameters
    public int SomeCount { get; set; }
    public double SomeMeasurement { get; set; }

    // Optional parameters
    public double[] OptionalArray { get; set; }
}
```

**CreateGrids reference:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `HorizontalCount` | int | 5 | Number of vertical (numeric) grid lines |
| `VerticalCount` | int | 5 | Number of horizontal (alphabetic) grid lines |
| `SpacingFeet` | double | 30.0 | Uniform spacing between grid lines |
| `Length` | double | 0 | Explicit line length (0 = derived) |
| `HorizontalSpacingsFeet` | double[] | null | Optional per-bay vertical spacing |
| `VerticalSpacingsFeet` | double[] | null | Optional per-bay horizontal spacing |

**Python defaults** (in `prompt_resolver.py`):

```python
_GRID_DEFAULTS = {
    "HorizontalCount": 5,
    "VerticalCount": 5,
    "SpacingFeet": 30.0,
    "Length": 0,
    "Naming": "Default",
}
```

---

## 3. Prompt Examples

Document supported prompt formats in the test fixture file and in the runbook. At minimum:

- One simple prompt per orientation/mode
- One complex prompt with optional parameters
- One prompt that should fail gracefully
- One prompt that tests edge cases

**CreateGrids reference prompts:**

```
Create 10 vertical gridlines, 50 ft long, spaced 10 ft apart
Create 5 horizontal grids spaced 20 ft apart
Create a 4 by 6 grid spaced 20 ft apart
Create vertical grids with spacings 10, 5, 20, 10
Create grids:
  Vertical:
  1-2 = 10'
  2-3 = 5'
  Horizontal:
  A-B = 15'
  B-C = 12'
```

---

## 4. Resolver Patterns

### Python (`prompt_resolver.py`)

1. Add an `_is_<cap>_prompt(lower)` function that checks for trigger keywords
2. Add parameter extraction functions (counts, measurements, optional arrays)
3. Return a `ResolvedPrompt(capability_name="<Name>", params={...}, assumptions=[...])`
4. When the prompt doesn't match → return `None` (unresolved)

### C# (`PromptDispatcher.cs`)

Mirror the Python logic for the Revit dialog path. The C# dispatcher must produce identical parameter dicts for the same prompt.

**CreateGrids reference:**

- Trigger keywords: `grid`, `grids`, `gridline`, `gridlines`
- Extraction: `_extract_counts()`, `_extract_spacing()`, `_extract_length()`, `_extract_variable_spacings()`
- Three variable spacing parsers: comma list, table with sections, unsectioned table

**Known gap (BUG-001):** `rows`/`columns` without `grid` keyword are not recognized as grid-prompt triggers. See [Known Gaps](#known-gaps).

---

## 5. Validation Rules

### C# (`Capabilities/<Cap>Capability.cs`)

The capability's `Execute()` method must validate parameters before calling the service:

1. Check required parameters are within bounds
2. Validate optional arrays (length, positive values)
3. Return `CapabilityResult` with `Status = "FAILED"` and clear error messages on validation failure
4. Never throw exceptions — always return structured error results

### Python (`pipe_client.py` → `_mock_execute`)

Mirror all C# validation in the mock so simulation mode catches the same errors.

**CreateGrids reference validation:**

| Rule | C# | Mock |
|------|-----|------|
| At least one count > 0 | Yes | **No (BUG-002)** |
| Spacing > 0 | Yes | Yes (implicit — no validation, but defaults positive) |
| Variable spacing array length = count - 1 | Yes | Yes |
| All variable spacing values > 0 | Yes | Yes |

**Known gap (BUG-002):** Mock execution allows both counts = 0 and returns SUCCESS. C# GridCapability correctly rejects this. See [Known Gaps](#known-gaps).

---

## 6. Simulation Behavior

Add a mock execution branch in `pipe_client.py` → `_mock_execute()`:

```python
if tool_name == "<CapabilityName>":
    # Validate parameters (mirror C# validation)
    # Compute expected output (counts, IDs, spans)
    # Return ToolResult with simulated created_ids
```

Simulation must:
- Return realistic `created_ids` (e.g., `grid_1`, `grid_A`, `level_1`)
- Compute correct output metrics (counts, spans, elevations)
- Mirror all C# validation rules
- Set `output_data.simulated = True`

**CreateGrids reference:** Returns `grid_1..N` for vertical + `grid_A..Z` for horizontal. Computes `span_x_feet` and `span_y_feet`.

---

## 7. Real Revit Execution

### C# Capability (`Capabilities/<Cap>Capability.cs`)

Implements `IAxiomCapability`:

```csharp
public class <Cap>Capability : IAxiomCapability
{
    public CapabilityResult Execute(Document doc, string argsJson)
    {
        // 1. Deserialize parameters
        // 2. Validate
        // 3. Call service
        // 4. Return CapabilityResult with created element IDs
    }
}
```

### C# Service (`Services/<Cap>Service.cs`)

Deterministic Revit API calls:

```csharp
public class <Cap>Service
{
    public List<ElementId> Create<Elements>(Document doc, <Cap>Parameters parameters)
    {
        // Revit API: doc.Create.NewGrid(line), doc.Create.NewLevel(elevation), etc.
    }
}
```

### Registration

Register the capability in `ToolRegistry` (C# side) and wire it in `App.cs`:

```csharp
registry.Register("CreateGrids", new GridCapability());
```

### Pipe Bridge

The capability receives JSON-RPC requests via `AxiomPipeServer`. Property names must use `[JsonProperty("snake_case")]` to match Python's naming convention.

**CreateGrids reference:**

- `GridCapability.cs` validates and delegates to `GridCreationService.cs`
- `GridCreationService.cs` creates `Grid` elements via `Grid.Create(doc, line)`
- Grid origin at (0,0,0), vertical lines grow +X, horizontal lines grow −Y
- Grid heads (bubbles) at top for vertical, left for horizontal

---

## 8. Telemetry Fields

Every capability execution is logged via:

1. **JSONL** (`logs/execution.jsonl`) — raw append-only record
2. **SQLite** (`~/.axiom/axiom.db` → `prompt_executions` table) — queryable history
3. **Parquet** (via test harness) — structured regression datasets

Minimum fields per execution:

| Field | Source |
|-------|--------|
| timestamp | auto |
| prompt | user input |
| mode | simulate / execution / test_simulate / test_real |
| capability | resolved capability name |
| parameters | resolved parameter dict (JSON) |
| assumptions | list of assumptions made during resolution |
| status | SUCCESS / FAILED / UNRESOLVED |
| created_count | number of elements created |
| created_ids | list of element IDs |
| errors | list of error messages |
| warnings | list of warning messages |
| duration_ms | execution time |

**CreateGrids reference:** All fields populated. Variable spacing arrays are stored in the parameters JSON. Telemetry events from `TelemetryAgent` include `prompt_received`, `prompt_resolved`, `plan_completed`.

---

## 9. Test Cases

### Unit tests (`tests/test_prompt_resolver.py`)

- Prompt resolves to correct capability name
- Parameters extracted correctly for each prompt variant
- Defaults applied when parameters are missing
- `None` returned for unsupported prompts
- Edge cases (count=1, count=0, word numbers, decimal values)

### Integration tests

- Full pipeline: prompt → resolver → orchestrator → execution agent → pipe client (mock)
- Status correctly set to SUCCESS/FAILED
- Telemetry events emitted

**CreateGrids reference:** 22 tests in `test_prompt_resolver.py`, covering uniform spacing, variable spacing (comma, table, both orientations), mismatch validation, and backward compatibility.

---

## 10. Learning-Loop Coverage

### Test fixture file (`tests/fixtures/<cap>_test_cases/<cap>.yaml`)

Each test case:

```yaml
- test_id: <unique_id>
  prompt: "<natural language prompt>"
  expected_capability: <CapabilityName>
  expected_parameters:
    <key>: <value>
  expected_created_count: <N>
  expected_success: true|false
  expected_failure_reason: "<reason if false>"
  mode: simulate|real
  notes: "<description>"
```

### Required categories

| Category | Description |
|----------|-------------|
| Happy path per mode | Each parameter combination that should succeed |
| Edge cases | Min/max values, single element, zero counts |
| Error cases | Invalid values, mismatched arrays, missing required params |
| Unsupported prompts | Prompts for other capabilities (should fail gracefully) |
| Keyword discovery | Alternative phrasings that may or may not be recognized |
| Regression anchors | Prompts that previously failed and were fixed |
| Real execution | Cases that require Revit (skipped when pipe unavailable) |

### CLI command

```bash
python -m poetry run axiom test-<cap> --mode simulate
```

**CreateGrids reference:** 27 test cases in `create_grids.yaml`, CLI command `axiom test-grids`.

---

## 11. Expected Artifacts

Each test run produces:

```
artifacts/<cap>_test_runs/<run_id>/
├── results.jsonl      # Raw event log
├── results.parquet    # Structured dataset
└── summary.md         # Human-readable report
```

The summary includes:
- Total / passed / failed / skipped counts
- Expected vs unexpected failures
- Failure category breakdown
- Regression comparison (if previous run exists)
- Recommended next fixes

---

## 12. Runbook Updates

Create or update `docs/runbooks/<cap>-learning-loop-runbook.md` with:

- Quick start commands
- CLI option reference
- Test case categories and counts
- Output file descriptions
- Parquet schema
- Regression workflow
- How to add new test cases
- Known bugs discovered by the harness

**CreateGrids reference:** `docs/runbooks/grid-learning-loop-runbook.md`

---

## 13. Merge / Acceptance Gates

Before merging a new capability:

- [ ] Capability metadata registered with correct status
- [ ] Parameter schema defined in Python and C#
- [ ] Prompt resolver returns correct `ResolvedPrompt` for all supported formats
- [ ] C# capability validates and returns structured errors (never throws)
- [ ] Mock execution mirrors C# validation
- [ ] Simulation mode works without Revit
- [ ] Real execution creates correct Revit elements (tested on Windows)
- [ ] Telemetry persists to JSONL + SQLite
- [ ] Unit tests pass for resolver, validation, and execution
- [ ] Learning-loop test suite passes at 100% (simulate mode)
- [ ] Parquet + JSONL + summary artifacts generated
- [ ] Regression comparison shows no unexpected regressions
- [ ] Runbook exists and is accurate
- [ ] Bug discovery log updated with any new findings
- [ ] ruff lint clean, existing pytest suite still passes
- [ ] PR reviewed and tested on Windows with Revit

---

## CreateGrids: Full Mapping

How `CreateGrids` satisfies every step of this checklist.

### Registry metadata

```
name: CreateGrids
description: Creates a grid system with vertical (numeric) and horizontal (alphabetic) grid lines.
supports_simulate: true
requires_revit_document: true
status: validated
```

File: `src/axiom_core/capability_registry.py` (lines 117–126)

### Parameter model

- Python schema: `_CREATE_GRIDS_SCHEMA` in `capability_registry.py` (lines 59–88)
- Python defaults: `_GRID_DEFAULTS` in `prompt_resolver.py` (lines 31–37)
- C# model: `src/axiom_revit/Axiom.Core/Models/GridParameters.cs`

### Resolver

- Python: `prompt_resolver.py` — `resolve_prompt()`, `_is_grid_prompt()`, `_extract_counts()`, `_extract_spacing()`, `_extract_length()`, `_extract_variable_spacings()`
- C#: `PromptDispatcher.cs` — mirrors Python parsing for the Revit dialog path

### C# capability

- `src/axiom_revit/Axiom.RevitAddin/Capabilities/GridCapability.cs`
- Validates counts, spacing, variable spacing arrays
- Delegates to `GridCreationService`

### Revit service

- `src/axiom_revit/Axiom.RevitAddin/Services/GridCreationService.cs`
- Creates `Grid` elements via `Grid.Create(doc, line)`
- `BuildOffsets()` computes cumulative positions for variable spacing
- Origin at (0,0,0), vertical lines +X, horizontal lines −Y

### CLI path

- `src/axiom_cli/main.py` → `prompt` command
- Calls `OrchestratorAgent.handle_prompt()` → `ExecutionAgent` → `PipeClient`
- Display: user-friendly parameter names, spacing arrays as comma lists

### Revit prompt path

- `PromptCommand.cs` → `AxiomPromptDialog` (multiline text input)
- `PromptDispatcher.BuildArgsJson()` parses the prompt
- Runs within a Revit transaction via `ExternalCommand`

### Telemetry / logging

- `TelemetryAgent` emits `prompt_received`, `prompt_resolved`, `plan_completed`
- `execution_log.py` persists to JSONL + SQLite
- CLI shows log path and event count

### Grid test harness

- CLI: `axiom test-grids --mode simulate|real`
- 27 test cases in `tests/fixtures/grid_test_cases/create_grids.yaml`
- Harness code: `src/axiom_core/testing/` (loader, runner, storage, report, models)
- Regression comparison against previous Parquet runs

### Run outputs

- `artifacts/grid_test_runs/<run_id>/results.jsonl`
- `artifacts/grid_test_runs/<run_id>/results.parquet`
- `artifacts/grid_test_runs/<run_id>/summary.md`
- SQLite: `~/.axiom/axiom.db` → `prompt_executions` table

---

## Known Gaps (Resolved)

Bugs discovered by the grid test harness. Both resolved. Full details in `docs/logs/bug-validation-log.md`.

### BUG-001: `rows`/`columns` without `grid` keyword — RESOLVED

- **Resolution:** Added `CLARIFICATION_NEEDED` status. Ambiguous prompts (rows/columns without "grid") now return a clarification question instead of silently failing. Explicit prompts with "grid"/"gridlines" still execute normally.
- **Test cases:** `horiz_rows_no_grid_keyword`, `columns_rows_no_grid_keyword`, `clarify_columns_only`, `clarify_rows_only`, `explicit_grid_rows`, `explicit_gridlines_columns_rows`

### BUG-002: Mock execution allows both counts = 0 — RESOLVED

- **Resolution:** Added `if h_count <= 0 and v_count <= 0: return FAILED` to `_mock_execute()`, matching C# validation.
- **Test cases:** `count_0_both_invalid`, `test_mock_execute_both_counts_zero_fails`, `test_mock_execute_single_orientation_zero_succeeds`

---

## Applying the Checklist to CreateLevels

CreateLevels is the second planned capability. This section maps each checklist
step to the CreateLevels plan, showing what exists today and what must be built.

Full plan details: [`docs/architecture/create-levels-capability-plan.md`](create-levels-capability-plan.md)
Test fixtures: [`tests/fixtures/level_test_cases/create_levels_test_cases.json`](../../tests/fixtures/level_test_cases/create_levels_test_cases.json)

| # | Step | CreateLevels Status | Notes |
|---|------|--------------------|---------|
| 1 | Capability Metadata | Done | Already registered in `capability_registry.py` with `status="planned"` |
| 2 | Parameter Model | Planned | Schema in registry. C# `LevelParameters.cs` to be created |
| 3 | Prompt Examples | Planned | 6 prompt styles documented in plan |
| 4 | Resolver Patterns | Not started | `_is_level_prompt()` + `_extract_level_params()` to add |
| 5 | Validation Rules | Planned | 7 rules defined (count>0, positive spacing, array lengths, no duplicates) |
| 6 | Simulation Behavior | Not started | Mock pseudocode in plan, add to `_mock_execute()` |
| 7 | Real Revit Execution | Not started | `LevelCapability.cs` + `LevelCreationService.cs` to create |
| 8 | Telemetry Fields | Done | Uses existing `execution_log.py` pipeline, no changes needed |
| 9 | Test Cases | Planned | 25 test cases in `create_levels_test_cases.json` |
| 10 | Learning-Loop Coverage | Planned | `axiom test-levels --mode simulate` CLI to add |
| 11 | Expected Artifacts | Planned | `artifacts/level_test_runs/<run_id>/` |
| 12 | Runbook Updates | Not started | `docs/runbooks/level-learning-loop-runbook.md` to create |
| 13 | Merge / Acceptance Gates | Planned | 12 acceptance criteria defined in plan |

### Lessons from CreateGrids applied to CreateLevels

1. **Validation parity** (BUG-002 lesson): mock and C# must enforce identical
   rules from day one. The plan includes matching validation pseudocode for both.
2. **Clarification loop** (BUG-001 lesson): ambiguous keywords ("floors",
   "stories") should trigger `CLARIFICATION_NEEDED`, not silent execution.
   Only the explicit keyword "levels" should resolve directly.
3. **Origin convention**: Level 1 defaults to elevation 0'-0" (matching the
   grid A1-at-origin convention).
4. **Named elements**: unlike grids (auto-numbered 1,2,3 / A,B,C), levels
   often have semantic names. The parameter model includes optional `LevelNames`.

---

## CreateLevels Implementation Plan

**Status:** Planned. Do not implement until this task is explicitly approved.

### Capability Metadata

```python
CapabilityMetadata(
    name="CreateLevels",
    description="Creates building levels at specified elevations.",
    parameter_schema=_CREATE_LEVELS_SCHEMA,
    supports_simulate=True,
    requires_revit_document=True,
    status="planned",  # Change to "validated" after first real execution
)
```

Already registered in `capability_registry.py` with `status="planned"`.

### Proposed Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `LevelCount` | int | Yes | — | Number of levels to create |
| `FloorToFloorFeet` | double | Yes | — | Uniform floor-to-floor height in feet |
| `StartElevationFeet` | double | No | 0.0 | Elevation of the first level |
| `LevelNames` | string[] | No | null | Custom level names (e.g., ["Basement", "Ground", "Level 2"]) |
| `VariableElevationsFeet` | double[] | No | null | Per-level elevations (overrides uniform height) |

### Prompt Examples

```
Create 5 levels at 12 ft floor-to-floor
Create 3 levels starting at -10 ft, 12 ft floor-to-floor
Create levels at elevations 0, 12, 24, 36
Create levels:
  Basement = -10'
  Ground = 0'
  Level 2 = 12'
  Level 3 = 24'
  Roof = 36'
```

### Validation Rules

| Rule | Description |
|------|-------------|
| LevelCount > 0 | At least one level required |
| FloorToFloorFeet > 0 | Positive height (unless variable elevations provided) |
| VariableElevationsFeet length = LevelCount | If provided, must match count |
| All elevations finite | No NaN/Inf values |
| LevelNames length = LevelCount | If provided, must match count |
| No duplicate elevations | Each level at a unique elevation |

### Simulation Behavior

Add to `_mock_execute()`:

```python
if tool_name == "CreateLevels":
    count = args.get("LevelCount", 0)
    ftf = args.get("FloorToFloorFeet", 12.0)
    start = args.get("StartElevationFeet", 0.0)
    var_elevations = args.get("VariableElevationsFeet")

    if count <= 0:
        return FAILED("LevelCount must be > 0")

    if var_elevations:
        elevations = var_elevations
    else:
        elevations = [start + i * ftf for i in range(count)]

    created_ids = [f"level_{i+1}" for i in range(count)]
    return ToolResult(SUCCESS, created_ids, output_data={
        "elevations_feet": elevations,
        "simulated": True,
    })
```

### Real Revit Execution

**C# files to create:**

| File | Purpose |
|------|---------|
| `Axiom.Core/Models/LevelParameters.cs` | Parameter model |
| `Axiom.RevitAddin/Capabilities/LevelCapability.cs` | Validation + delegation |
| `Axiom.RevitAddin/Services/LevelCreationService.cs` | `Level.Create(doc, elevation)` |

**Revit API:** `Level.Create(Document, double elevation)` — straightforward, deterministic.

### Required Tests

**Unit tests (`test_prompt_resolver.py`):**

- "Create 5 levels at 12 ft floor-to-floor" → LevelCount=5, FloorToFloorFeet=12.0
- "Create 3 levels starting at -10 ft" → StartElevationFeet=-10.0
- "Create levels at elevations 0, 12, 24, 36" → VariableElevationsFeet=[0, 12, 24, 36]
- Named levels prompt → LevelNames parsed
- "Create grids" → still resolves to CreateGrids (no regression)

**Integration tests:**

- Full pipeline simulation with mock
- LevelCount=0 → FAILED
- Mismatched array lengths → FAILED

### Learning-Loop Test Cases

Create `tests/fixtures/level_test_cases/create_levels.yaml` with:

| Category | Count | Examples |
|----------|-------|---------|
| Uniform height | 3 | 5 levels at 12 ft, 3 levels at 10 ft, 1 level |
| Variable elevations (comma) | 2 | "elevations 0, 12, 24" |
| Variable elevations (table) | 2 | Named level table format |
| Custom names | 1 | Named levels |
| Start elevation | 2 | Negative start, non-zero start |
| Edge cases | 3 | count=1, large count, decimal heights |
| Error cases | 3 | count=0, mismatched arrays, duplicate elevations |
| Unsupported | 1 | Grid prompt should NOT resolve to levels |

CLI command: `axiom test-levels --mode simulate`

### Implementation Order

When approved:

1. Add `_is_level_prompt()` and `resolve_level_prompt()` to `prompt_resolver.py`
2. Add mock execution to `pipe_client.py`
3. Add unit tests
4. Add learning-loop test cases + CLI command
5. Create C# parameter model, capability, and service
6. Change registry status from `"planned"` to `"validated"`
7. Test on Windows with Revit
8. Update runbook and bug validation log
