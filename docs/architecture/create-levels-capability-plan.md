# CreateLevels Capability Plan

**Status:** Planned — do not implement until explicitly approved.
**Capability #:** 2 (after CreateGrids)
**Registry status:** `planned` (already registered in `capability_registry.py`)

---

## Purpose

Create building levels (floor planes) at specified elevations in a Revit model.
Levels are fundamental Revit elements that define vertical building organization —
every floor plan, ceiling plan, and structural plan references a level.

CreateLevels is the second Axiom capability, chosen because:

1. **Simple and deterministic** — `Level.Create(doc, elevation)` is a single Revit
   API call with predictable results, similar in complexity to grid line creation.
2. **Proves the framework** — validates that the capability registry, resolver,
   orchestrator, and testing harness support more than one capability without
   structural changes.
3. **High value** — levels are typically one of the first elements created in any
   Revit project, often before grids.

---

## Relationship to CreateGrids Pattern

CreateLevels follows the identical pattern established by CreateGrids:

| Layer | CreateGrids | CreateLevels |
|-------|-------------|--------------|
| Registry | `capability_registry.py` (validated) | `capability_registry.py` (planned) |
| Python resolver | `_is_grid_prompt()`, `_extract_counts()` | `_is_level_prompt()`, `_extract_level_params()` |
| C# dispatcher | `PromptDispatcher.ResolveCapability()` | Same file, add level keyword check |
| Mock execution | `pipe_client.py` → `_mock_execute` (CreateGrids branch) | Same file, add CreateLevels branch |
| C# model | `GridParameters.cs` | `LevelParameters.cs` |
| C# capability | `GridCapability.cs` | `LevelCapability.cs` |
| C# service | `GridCreationService.cs` | `LevelCreationService.cs` |
| Telemetry | Same `execution_log.py` pipeline | Same pipeline, no changes needed |
| Test harness | `axiom test-grids --mode simulate` | `axiom test-levels --mode simulate` |
| Test fixtures | `tests/fixtures/grid_test_cases/create_grids.yaml` | `tests/fixtures/level_test_cases/create_levels.yaml` |

Key differences from CreateGrids:

- **One dimension** — levels are vertical only (elevation), not a 2D grid system.
- **No orientation mapping** — no horizontal/vertical swapping complexity.
- **Named elements** — levels often have semantic names (Basement, Ground, Roof).
- **Negative elevations** — basements and sub-grade levels are common and valid.
- **No spacing ambiguity** — "floor-to-floor" is unambiguous (unlike "rows"/"columns").

---

## Capability Metadata

Already registered in `src/axiom_core/capability_registry.py`:

```python
CapabilityMetadata(
    name="CreateLevels",
    description="Creates building levels at specified elevations.",
    parameter_schema=_CREATE_LEVELS_SCHEMA,
    supports_simulate=True,
    requires_revit_document=True,
    status="planned",  # → "validated" after first successful real execution
)
```

---

## Parameter Model

### Python Schema (already in `capability_registry.py`)

```python
_CREATE_LEVELS_SCHEMA = {
    "type": "object",
    "properties": {
        "LevelCount": {
            "type": "integer",
            "description": "Number of levels to create.",
            "minimum": 1,
        },
        "FloorToFloorFeet": {
            "type": "number",
            "description": "Floor-to-floor height in feet.",
            "exclusiveMinimum": 0,
        },
        "StartElevationFeet": {
            "type": "number",
            "description": "Elevation of the first level in feet.",
            "default": 0,
        },
    },
    "required": ["LevelCount", "FloorToFloorFeet"],
}
```

### Full Parameter Table

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `LevelCount` | int | Yes | — | Number of levels to create (≥ 1) |
| `FloorToFloorFeet` | double | Yes* | — | Uniform floor-to-floor height in feet (> 0). *Not required if `VariableElevationsFeet` is provided. |
| `StartElevationFeet` | double | No | 0.0 | Elevation of the first level in feet. May be negative (basements). |
| `LevelNames` | string[] | No | null | Custom names for levels (e.g., `["Basement", "Ground", "Level 2"]`). If null, Revit assigns default names. |
| `VariableElevationsFeet` | double[] | No | null | Explicit elevation for each level. Overrides uniform `FloorToFloorFeet` calculation. |

### C# Model (to be created as `Axiom.Core/Models/LevelParameters.cs`)

```csharp
public class LevelParameters
{
    public int LevelCount { get; set; }
    public double FloorToFloorFeet { get; set; }
    public double StartElevationFeet { get; set; } = 0.0;
    public string[] LevelNames { get; set; }
    public double[] VariableElevationsFeet { get; set; }
}
```

---

## Prompt Examples

### Uniform floor-to-floor height

```
Create 5 levels at 12 ft floor-to-floor
Create 3 levels spaced 10 feet apart
Create 8 levels with 14 ft floor height
```

### With start elevation

```
Create 3 levels starting at -10 ft, 12 ft floor-to-floor
Create 5 levels from elevation 0 ft, 12 ft apart
```

### Variable elevations (comma list)

```
Create levels at elevations 0, 12, 24, 36
Create levels at 0, 14, 28, 40, 52 feet
```

### Named levels (table format)

```
Create levels:
  Basement = -10'
  Ground = 0'
  Level 2 = 12'
  Level 3 = 24'
  Roof = 36'
```

### Single level

```
Create 1 level at 0 feet
```

### Ambiguous prompts (should trigger clarification or fail)

```
Create 5 floors 12 ft apart          → clarification: "Did you mean building levels?"
Create stories at 0, 12, 24          → clarification: "Did you mean Revit levels?"
```

---

## Validation Rules

| # | Rule | Error Message |
|---|------|---------------|
| 1 | `LevelCount > 0` | "LevelCount must be greater than 0." |
| 2 | `FloorToFloorFeet > 0` (when no variable elevations) | "FloorToFloorFeet must be positive." |
| 3 | `VariableElevationsFeet.Length == LevelCount` (if provided) | "VariableElevationsFeet has {n} values but LevelCount is {m}." |
| 4 | All elevations are finite (no NaN/Inf) | "Elevation values must be finite numbers." |
| 5 | No duplicate elevations | "Duplicate elevation at {x} ft. Each level must have a unique elevation." |
| 6 | `LevelNames.Length == LevelCount` (if provided) | "LevelNames has {n} names but LevelCount is {m}." |
| 7 | No empty level names (if provided) | "Level names must not be empty." |

### Validation Parity

Both C# (`LevelCapability.cs`) and Python mock (`_mock_execute`) must enforce
the same rules. This was a lesson from CreateGrids BUG-002 where the mock
allowed invalid inputs that C# rejected.

---

## Simulation Behavior

Add to `_mock_execute()` in `src/axiom_core/pipe_client.py`:

```python
if tool_name == "CreateLevels":
    count = args.get("LevelCount", 0)
    ftf = args.get("FloorToFloorFeet", 0)
    start = args.get("StartElevationFeet", 0.0)
    var_elevations = args.get("VariableElevationsFeet")
    level_names = args.get("LevelNames")

    # Validation (must match C# LevelCapability)
    if count <= 0:
        return FAILED("LevelCount must be greater than 0.")
    if var_elevations is None and ftf <= 0:
        return FAILED("FloorToFloorFeet must be positive.")
    if var_elevations is not None and len(var_elevations) != count:
        return FAILED(f"VariableElevationsFeet has {len(var_elevations)} "
                      f"values but LevelCount is {count}.")
    if level_names is not None and len(level_names) != count:
        return FAILED(f"LevelNames has {len(level_names)} names "
                      f"but LevelCount is {count}.")

    # Compute elevations
    if var_elevations:
        elevations = var_elevations
    else:
        elevations = [start + i * ftf for i in range(count)]

    # Check for duplicates
    if len(set(elevations)) != len(elevations):
        return FAILED("Duplicate elevation detected.")

    # Generate mock IDs
    if level_names:
        created_ids = [f"level_{name}" for name in level_names]
    else:
        created_ids = [f"level_{i+1}" for i in range(count)]

    return ToolResult(SUCCESS, created_ids, output_data={
        "elevations_feet": elevations,
        "simulated": True,
    })
```

---

## Revit Execution Behavior

### C# Files to Create

| File | Purpose |
|------|---------|
| `Axiom.Core/Models/LevelParameters.cs` | Parameter model (deserialized from JSON args) |
| `Axiom.RevitAddin/Capabilities/LevelCapability.cs` | Validate parameters, delegate to service |
| `Axiom.RevitAddin/Services/LevelCreationService.cs` | Create levels via Revit API |

### Revit API

```csharp
// Core API call — straightforward and deterministic
Level newLevel = Level.Create(doc, elevationInFeet);
newLevel.Name = customName;  // Optional — only if LevelNames provided
```

### Service Pseudocode

```csharp
public class LevelCreationService
{
    public CapabilityResult Execute(Document doc, LevelParameters p)
    {
        var elevations = p.VariableElevationsFeet != null
            ? p.VariableElevationsFeet
            : Enumerable.Range(0, p.LevelCount)
                .Select(i => p.StartElevationFeet + i * p.FloorToFloorFeet)
                .ToArray();

        var createdIds = new List<string>();
        for (int i = 0; i < elevations.Length; i++)
        {
            Level level = Level.Create(doc, elevations[i]);
            if (p.LevelNames != null && i < p.LevelNames.Length)
                level.Name = p.LevelNames[i];
            createdIds.Add(level.UniqueId);
        }

        return new CapabilityResult("SUCCESS", createdIds);
    }
}
```

### Origin Convention

- Level 1 (or the first named level) defaults to elevation 0'-0" unless
  `StartElevationFeet` is specified.
- This mirrors the CreateGrids convention where Grid A1 intersects at the
  project origin (0,0,0).

---

## Telemetry Fields

Uses the existing `execution_log.py` pipeline — no changes needed. Each run
persists:

| Field | Source |
|-------|--------|
| `prompt` | Raw user input |
| `capability` | `"CreateLevels"` |
| `parameters` | `{LevelCount, FloorToFloorFeet, StartElevationFeet, ...}` |
| `assumptions` | e.g., `["StartElevationFeet defaulted to 0.0"]` |
| `status` | `SUCCESS`, `FAILED`, `CLARIFICATION_NEEDED` |
| `created_count` | Number of levels created |
| `created_ids` | Revit element UniqueIds or mock IDs |
| `errors` | Validation or execution errors |
| `warnings` | e.g., "Level name 'Level 1' already exists in model" |
| `duration_ms` | Execution time |
| `mode` | `simulation` or `execution` |

Storage layers (same as CreateGrids):

- **JSONL** → `logs/execution.jsonl`
- **SQLite** → `prompt_executions` table
- **Parquet** → `artifacts/level_test_runs/<run_id>/results.parquet`

---

## Failure and Clarification Cases

### Validation Failures

| Input | Expected Result |
|-------|----------------|
| `LevelCount = 0` | FAILED: "LevelCount must be greater than 0." |
| `FloorToFloorFeet = -5` | FAILED: "FloorToFloorFeet must be positive." |
| `FloorToFloorFeet = 0` | FAILED: "FloorToFloorFeet must be positive." |
| 4 elevations but `LevelCount = 3` | FAILED: mismatch error |
| Duplicate elevations `[0, 12, 12, 24]` | FAILED: duplicate elevation |
| 3 names but `LevelCount = 5` | FAILED: name count mismatch |

### Clarification Cases (following BUG-001 pattern)

| Prompt | Behavior |
|--------|----------|
| `Create 5 floors 12 ft apart` | CLARIFICATION_NEEDED: "Did you mean Revit building levels spaced 12 ft apart?" |
| `Create stories at 0, 12, 24` | CLARIFICATION_NEEDED: "Did you mean Revit levels at elevations 0, 12, 24 ft?" |
| `Create 5 levels at 12 ft floor-to-floor` | Executes normally (explicit "levels" keyword) |

### Unsupported / No-Match

| Prompt | Behavior |
|--------|----------|
| `Create 10 vertical gridlines` | Resolves to CreateGrids (not CreateLevels) |
| `Place diffusers in every room` | UNRESOLVED |

---

## Acceptance Criteria

Before changing status from `planned` to `validated`:

- [ ] Python resolver recognizes level prompts with explicit "level" keyword
- [ ] Ambiguous prompts ("floors", "stories") trigger clarification
- [ ] Mock execution matches C# validation rules
- [ ] CLI `axiom prompt "Create 5 levels at 12 ft floor-to-floor" --simulate` succeeds
- [ ] CLI `axiom test-levels --mode simulate` runs full test suite
- [ ] All existing CreateGrids tests still pass (no regression)
- [ ] C# `LevelCapability.cs` and `LevelCreationService.cs` built and loaded in Revit
- [ ] Real Revit execution creates levels at correct elevations
- [ ] At least one real-execution test case passes on Windows with Revit open
- [ ] Registry status changed to `"validated"` only after real execution succeeds
- [ ] Execution log (JSONL + SQLite) captures CreateLevels runs correctly
- [ ] Runbook updated with level-specific test instructions

---

## Implementation Order

When implementation is approved:

1. Add `_is_level_prompt()` and `_extract_level_params()` to `prompt_resolver.py`
2. Add clarification check for "floors"/"stories" (same pattern as grid rows/columns)
3. Add CreateLevels branch to `_mock_execute()` in `pipe_client.py`
4. Add unit tests to `tests/test_prompt_resolver.py`
5. Create learning-loop test fixtures (`tests/fixtures/level_test_cases/create_levels.yaml`)
6. Add `axiom test-levels` CLI command
7. Create C# files: `LevelParameters.cs`, `LevelCapability.cs`, `LevelCreationService.cs`
8. Add level keyword check to `PromptDispatcher.cs`
9. Test on Windows with Revit
10. Change registry status from `"planned"` to `"validated"`
11. Update runbook and bug validation log
