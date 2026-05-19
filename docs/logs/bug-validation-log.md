# Bug Validation Log

Bugs discovered through the grid/level/inventory test harnesses and manual testing.

---

## Open Bugs (Pending Real Revit Validation)

### BUG-003: C# `ParameterGroup` not populated in ModelInventoryService

- **Discovered by:** InventoryModel schema hardening review
- **Impact:** Low — `parameter_group` field exists in schema and mock data but the C# `CollectParameters()` method does not extract `param.Definition?.ParameterGroup` from the Revit API. Python side stores empty string for real data.
- **Fix:** Add `pe.ParameterGroup = param.Definition?.ParameterGroup?.ToString() ?? "";` to `ModelInventoryService.CollectParameters()`. Add `public string ParameterGroup { get; set; }` to `ParameterEntry` DTO.
- **Status:** Waiting for real Revit validation — do not fix blindly
- **Risk:** Fix is isolated (2 lines in C#), but requires Revit to confirm `ParameterGroup` property path

### BUG-004: C# `LevelId` not populated in ElementEntry

- **Discovered by:** InventoryModel schema hardening review
- **Impact:** Low — `level_id` field exists in schema and mock data but the C# `BuildElementEntry()` method only stores `LevelName`, not the level's ElementId.
- **Fix:** Add `public int LevelId { get; set; }` to `ElementEntry` DTO and populate it alongside `LevelName` in `BuildElementEntry()`.
- **Status:** Waiting for real Revit validation — do not fix blindly
- **Risk:** Fix is isolated (2 lines in C#), but requires Revit to confirm level ElementId access pattern

### BUG-005: C# `source_model` not included in InventoryModel output

- **Discovered by:** InventoryModel schema hardening review
- **Impact:** Low — mock returns `source_model` but real C# `InventoryModelCapability.Execute()` does not include `doc.Title` in the output dictionary.
- **Fix:** Add `result.OutputData["source_model"] = doc.Title;` to the real execution path in `InventoryModelCapability.cs`.
- **Status:** Waiting for real Revit validation — do not fix blindly
- **Risk:** Fix is trivial (1 line), but requires confirming `doc.Title` is accessible in the capability execution context

---

## Pending Validation Items (Not Bugs)

### PENDING-001: Revit 2024 real execution — all capabilities

- **Scope:** CreateGrids, CreateLevels, InventoryModel
- **What:** All three capabilities pass Python simulation but have not been tested in a real Revit 2024 environment
- **Blocked on:** Windows machine with Revit 2024 installed
- **Expected result:** C# builds in Visual Studio, add-in loads in Revit, all three capabilities execute correctly via Prompt dialog

### PENDING-002: Revit 2027 compatibility validation

- **Scope:** Build validation only (no real execution yet)
- **What:** Revit 2027 uses .NET 10 (vs .NET Framework 4.8 for 2024). Parallel SDK-style .csproj files needed.
- **Blocked on:** Revit 2027 trial or developer license installed locally
- **Expected result:** C# compiles against Revit 2027 API DLLs, add-in loads in Revit 2027
- **Reference:** `docs/runbooks/revit-multi-version-runbook.md`

---

## Resolved Bugs

### BUG-001: `rows`/`columns` without `grid` keyword — clarification loop

- **Discovered by:** Grid test harness (`horiz_rows_no_grid_keyword`, `columns_rows_no_grid_keyword`)
- **Resolved in:** Commit `782333a`
- **Description:** Prompts like "Create 4 rows spaced 15 ft apart" now return a clarification question ("Did you mean Revit gridlines arranged as 4 horizontal rows?") instead of silently failing. Explicit prompts containing "grid", "grids", "gridline", or "gridlines" still execute normally.
- **Files changed:**
  - `src/axiom_core/prompt_resolver.py` — added `_check_grid_clarification()`, `status` and `clarification_message` fields on `ResolvedPrompt`
  - `src/axiom_core/agents/orchestrator_agent.py` — handles `clarification_needed` status
  - `src/axiom_cli/main.py` — CLI displays clarification question without executing
  - `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` — C# `CheckGridClarification()` and `NeedsClarification` result flag
  - `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` — Revit dialog shows clarification, no transaction started
- **Test coverage:** `clarify_columns_only`, `clarify_rows_only`, `horiz_rows_no_grid_keyword`, `columns_rows_no_grid_keyword`, `explicit_grid_rows`, `explicit_gridlines_columns_rows` + 7 pytest unit tests

### BUG-002: Mock execution allows both counts = 0

- **Discovered by:** Grid test harness (`count_0_both_valid_sim`)
- **Resolved in:** Commit `782333a`
- **Description:** `_mock_execute()` in `pipe_client.py` now fails with a clear error when both `HorizontalCount` and `VerticalCount` are 0, matching C# `GridCapability` validation. One orientation may be 0 as long as the other is > 0.
- **Files changed:**
  - `src/axiom_core/pipe_client.py` — added `if h_count <= 0 and v_count <= 0: return FAILED` check
- **Test coverage:** `count_0_both_invalid` (harness), `test_mock_execute_both_counts_zero_fails`, `test_mock_execute_single_orientation_zero_succeeds` (pytest)
