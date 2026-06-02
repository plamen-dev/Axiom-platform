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

## Revit Live Validation

SetParameterValue is now available in the Revit Axiom prompt dialog. The C# bridge routes prompts matching `[Apply] Set <Parameter> to <Value> for <N> <Category>` directly to the `SetParameterValueCapability`.

### Architecture

```
User Prompt → PromptDispatcher.ResolveCapability()
           → SetParameterValueCapability.Execute()
           → ParameterEditService.Preview() or .Apply()
           → Evidence artifacts → interactive TaskDialog (Apply / Open evidence / Close)
           → [Apply] PromptDispatcher.DispatchWithArgs() with previewed element IDs
           → ParameterEditService.Apply() in a transaction → apply evidence → result dialog
```

- **Capability:** `SetParameterValueCapability` (registered in `App.cs`)
- **Service:** `ParameterEditService` (element collection, parameter read/write, `CollectElementsByIds`)
- **Parameters model:** `SetParameterValueParameters` (category, parameterName, value, elementCount, mode, `elementIds`)

### Interactive Preview → Apply

On a successful preview, the previewed elements are **selected and zoomed/focused** in Revit (`UIDocument.Selection.SetElementIds` + `UIDocument.ShowElements`) so the user can confidently review what Apply will change. The dialog notes "Previewed element(s) selected in Revit for review." Selection is read-only and best-effort — it never modifies the model and never blocks the preview.

The preview result dialog is interactive. After a successful preview it offers:

- **Apply changes to N element(s)** — only shown when there is at least one editable previewed element.
- **Open evidence folder** — opens the preview run folder in Explorer (dialog re-shows afterward).
- **Close** — dismisses without modifying the model.

Apply behavior (preview-approval path):

- Re-executes `SetParameterValue` in apply mode with the **exact element IDs** captured during preview (`ElementIds`), so it never recollects a different set if the model/view changed.
- Runs inside the `Axiom SetParameterValue` transaction; rolled back on any failure.
- If any previewed element ID no longer resolves (deleted/changed since preview), Apply is **blocked** with an explanation telling the user to re-run the preview — the model is not modified.
- The prompt fallback `Apply Set <Parameter> to <Value> for <N> <Category>` is still supported; it recollects by category and is recorded in evidence as `initiated_from: prompt`.
- Preview-approval applies are recorded in evidence as `initiated_from: preview_approval` with `targeted_by_ids: true` and a `preview_evidence_path` pointer.
- Preview-approval applies also copy the preview run's `preview.json` into the apply run folder as `linked_preview.json` and write `linked_preview_metadata.json` (run-ID reconciliation + `target_ids_match`) — see [Revit Evidence Artifacts](#revit-evidence-artifacts). If `preview.json` is missing, the apply is **not** failed; the metadata records `copy_status: missing_preview_json` and a warning is added to `result_summary.md`.

### Revit Deployment

Deploy to `C:\Program Files\Autodesk\Revit\Addins\2027\`:
- `Axiom.RevitAddin.dll`
- `Axiom.Core.dll`
- `Newtonsoft.Json.dll`
- `Axiom.RevitAddin.addin`

### Live Validation Plan

1. Deploy to Revit 2027
2. Open a disposable/sample model
3. Run preview (no model modification):
   ```
   Set Comments to Axiom test 001 for 1 Walls
   ```
   Expected: interactive preview dialog shows old/new values with **Apply** and **Close**, evidence artifacts written, model NOT modified
4. Click **Close** — confirm the model is not modified.
5. Run the preview again, then click **Apply changes to 1 element(s)**.
   Expected: exactly the previewed wall's Comments parameter updated, apply evidence written (`initiated_from: preview_approval`)
6. Prompt fallback for apply (no dialog approval needed):
   ```
   Apply Set Comments to Axiom test 001 for 1 Walls
   ```
   Expected: exactly 1 wall's Comments parameter updated, evidence artifacts written
7. Verify by selecting the wall or running:
   ```
   Run InventoryModel sample values for Walls
   ```
8. Check evidence artifacts at `%LOCALAPPDATA%\Axiom\parameter_edit_runs\spv_<timestamp>\`

### Revit Evidence Artifacts

Live Revit runs write evidence to:

```
%LOCALAPPDATA%\Axiom\parameter_edit_runs\spv_<timestamp>\
├── request.json                  # Prompt, mode, category, parameter, value, document name, initiated_from, targeted_by_ids
├── preview.json                  # Preview mode: element previews with old/new values
├── changes.json                  # Apply mode: actual changes per element
├── linked_preview.json           # Apply-from-preview only: durable copy of the preview run's preview.json
├── linked_preview_metadata.json  # Apply-from-preview only: reconciliation metadata (see below)
└── result_summary.md             # Human-readable summary with element table
```

For apply runs initiated from preview approval, `linked_preview_metadata.json` records:

- `preview_evidence_path` — folder of the originating preview run
- `copied_at` — UTC timestamp of the link operation
- `source_preview_run_id` — preview run folder name (e.g. `spv_<timestamp>`)
- `apply_run_id` — apply run folder name
- `element_ids_previewed` — element IDs captured during preview
- `element_ids_applied` — element IDs successfully modified during apply
- `target_ids_match` — `true` when applied IDs exactly match previewed IDs
- `initiated_from` — `preview_approval`
- `copy_status` — `copied` | `missing_preview_json` | `copy_failed`

`result_summary.md` for apply-from-preview runs additionally lists the **Preview evidence path**, the **Linked preview snapshot** status (`linked_preview.json` if copied), and **Target IDs match preview** (`true`/`false`).

### Revit-Specific Behavior

- **Active view filtering:** By default, only elements visible in the active view are collected. This prevents editing elements in other views or hidden elements.
- **Category resolution:** Resolves the `Category` object directly from `doc.Settings.Categories` (with singular/plural normalization) and filters via `ElementCategoryFilter(category.Id)`. No `BuiltInCategory` enum cast — avoids the Int32/Int64 mismatch on Revit 2027 where `ElementId.Value` is `long`.
- **Apply targets exact IDs:** Preview-approval apply resolves the previewed elements by ID (`ParameterEditService.CollectElementsByIds` + `RevitElementIdCompat.FromLong`) and blocks if any no longer resolve.
- **Parameter search:** Case-insensitive name match on instance parameters. Type parameters are excluded.
- **Transaction safety:** Preview mode runs without a transaction (read-only). Apply mode runs within a named transaction ("Axiom SetParameterValue") — rolled back on failure.
- **Any view:** SetParameterValue can run from any view (not restricted to plan views like CreateGrids/CreateLevels).

## What Is Not Supported in v0

- Non-text parameters (Length, Area, Integer, etc.)
- Type parameters (only instance parameters)
- Read-only parameters
- Whole-model edits (category constraint required)
- More than 5 elements per operation
- Undo/rollback
- Batch operations across multiple categories

## Safety Model

- **Preview is always safe** — no model modification occurs
- **Apply requires explicit keyword** — cannot accidentally modify
- **Registry validation gates all operations** — CLI validates via JSONL registry
- **Live Revit validates at runtime** — parameter existence, read-only, storage type checked per element
- **Hard cap prevents large-scale changes** — max 5 elements
- **Evidence trail for every operation** — full audit artifacts
- **Transaction rollback on failure** — apply mode rolls back if any error occurs

## Future v1+ Considerations

- Numeric/measurable parameters with unit validation
- Type parameters (with explicit opt-in)
- Higher element caps (with progressive validation: 10, 50, 100)
- Undo support via transaction groups
- Batch operations
- Cross-category operations
