# SetParameterValue v0 Runbook

## Overview

Constrained text parameter editing with preview/apply and evidence export. Uses the discovered parameter registry to validate that the requested category, parameter, data type, and writability are safe before any modification.

## v0 Constraints

| Constraint | Rule |
|-----------|------|
| Parameter type | Text only (`DataTypeLabel == "Text"`) |
| Parameter scope | Instance only (`IsInstanceParam == True`) |
| Writability | Writable only (`IsReadOnly == False`) |
| Category | Must be specified (no whole-model edits) |
| Element count | Explicit count required |
| Hard cap | 5 elements maximum |
| Default mode | Preview (dry-run, model not modified) |
| Apply mode | Requires explicit "Apply" keyword in prompt |

## Prompt Format

### Preview (default)

```
Set <Parameter> to <Value> for <N> <Category>
Set <Parameter> to "<Value>" for <N> <Category>
```

### Apply (requires explicit keyword)

```
Apply Set <Parameter> to <Value> for <N> <Category>
Apply Set <Parameter> to "<Value>" for <N> <Category>
```

Both quoted and unquoted values are supported. Unquoted is recommended for CLI/PowerShell use since shells strip inner quotes.

### Examples

| Prompt | Mode | Parameter | Value | Count | Category |
|--------|------|-----------|-------|-------|----------|
| `Set Comments to Axiom test 001 for 3 Walls` | preview | Comments | Axiom test 001 | 3 | Walls |
| `Set Mark to AX-TEST for 2 Doors` | preview | Mark | AX-TEST | 2 | Doors |
| `Set Comments to Checked by Axiom for 5 Mechanical Equipment` | preview | Comments | Checked by Axiom | 5 | Mechanical Equipment |
| `Apply Set Comments to Axiom test 001 for 3 Walls` | apply | Comments | Axiom test 001 | 3 | Walls |
| `Apply Set Mark to AX-TEST for 2 Doors` | apply | Mark | AX-TEST | 2 | Doors |
| `Set Comments to "Axiom test 001" for 3 Walls` | preview | Comments | Axiom test 001 | 3 | Walls |

## CLI Usage

```bash
# Preview mode (default — no model modification)
poetry run axiom set-parameter-value "Set Comments to Axiom test 001 for 3 Walls"

# Apply mode (modifies model)
poetry run axiom set-parameter-value "Apply Set Mark to AX-TEST for 2 Doors"

# With explicit registry path
poetry run axiom set-parameter-value --registry artifacts/parameter_registry_candidates/reg_20260524/revit_property_registry.jsonl "Set Comments to test for 3 Walls"

# With registry directory
poetry run axiom set-parameter-value --registry-dir artifacts/parameter_registry_candidates/reg_20260524 "Set Comments to test for 3 Walls"
```

### Dry-Run Validation (No Live Revit)

Use the included sample registry to verify CLI evidence generation without Revit:

```bash
# Preview with sample registry — creates artifacts/parameter_edit_runs/<run_id>/
poetry run axiom set-parameter-value --registry tools/sample_data/sample_registry.jsonl "Set Comments to Axiom test 001 for 3 Walls"

# PowerShell equivalent
poetry run axiom set-parameter-value --registry ".\tools\sample_data\sample_registry.jsonl" "Set Comments to Axiom test 001 for 3 Walls"

# Verify evidence artifacts were created
ls artifacts/parameter_edit_runs/
# Should contain: request.json, preview.json, result_summary.md
```

Expected output:
- Mode: preview
- Category: Walls
- Parameter: Comments
- Model modified: False
- 3 elements shown in preview table

## Registry Validation

Before any preview or apply, the system validates against the parameter registry:

1. **Category exists** — the ObjectCategory must exist in the registry
2. **Parameter exists** — the ParameterName must exist for that category
3. **Writable** — `IsReadOnly` must be `False`
4. **Instance parameter** — `IsInstanceParam` must be `True` (type parameters rejected in v0)
5. **Text data type** — `DataTypeLabel` must be `"Text"` (non-text rejected in v0)
6. **No ambiguity** — single match required for both category and parameter

## Rejections

The system rejects and refuses to execute if:

| Condition | Rejection |
|-----------|-----------|
| Count missing or zero | "Element count is missing or zero." |
| Count > 5 | "Element count N exceeds hard cap of 5." |
| Read-only parameter | "Parameter 'X' is read-only." |
| Type parameter | "Parameter 'X' is not an instance parameter." |
| Non-text parameter | "Parameter 'X' has data type 'Y', but only Text parameters are supported in v0." |
| Category not found | "Category 'X' not found in registry." |
| Parameter not found | "Parameter 'X' not found for category 'Y' in registry." |
| Ambiguous category | "Ambiguous category match: [...]" |
| Ambiguous parameter | "Ambiguous parameter match: [...]" |
| Empty registry | "Registry is empty — cannot validate parameter." |

## Evidence Artifacts

Every run (preview, apply, or rejected) creates:

```
artifacts/parameter_edit_runs/<run_id>/
├── request.json         # Parsed prompt and request parameters
├── preview.json         # Full result including element previews
├── changes.json         # Apply mode only — actual changes made
└── result_summary.md    # Human-readable summary
```

### result_summary.md includes

- Raw prompt
- Resolved mode (preview/apply)
- Resolved category
- Resolved parameter
- Requested value
- Data type
- Instance/type parameter status
- Selected element count
- Old values / new values per element
- Per-element success/failure
- Whether model was modified
- Model name (if available)

## What Is Not Supported in v0

- Non-text parameters (Length, Area, Integer, etc.)
- Type parameters (only instance parameters)
- Read-only parameters
- Whole-model edits (category constraint required)
- More than 5 elements per operation
- Live Revit connection (simulation only until C# capability is implemented)
- Undo/rollback
- Batch operations across multiple categories

## Safety Model

- **Preview is always safe** — no model modification occurs
- **Apply requires explicit keyword** — cannot accidentally modify
- **Registry validation gates all operations** — unknown parameters rejected
- **Hard cap prevents large-scale changes** — max 5 elements
- **Evidence trail for every operation** — full audit artifacts

## Future v1+ Considerations

- Numeric/measurable parameters with unit validation
- Type parameters (with explicit opt-in)
- Active view filtering
- Higher element caps (with progressive validation: 10, 50, 100)
- Live Revit C# capability integration
- Undo support via transaction groups
- Batch operations
