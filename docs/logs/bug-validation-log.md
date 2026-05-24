# Bug Validation Log

Bugs discovered through the grid/level/inventory test harnesses and manual testing.

For behavior change history (before/after per prompt), see `docs/logs/behavior-change-ledger.md`.
For regression fixture files, see `tests/fixtures/behavior_regressions/`.

---

## Live Revit 2027 Validation Results (2026-05-23)

Plan execution queue validated with structured dispatch:

| Test | Result | Details |
|------|--------|---------|
| `Run InventoryModel parameter schema plan max 10` | PASS | 10/10 completed, 0 failed, 0 skipped |
| `Run InventoryModel parameter schema plan priority only` | PASS | 16/16 completed, 0 failed, 0 skipped |
| `inventory-import-batch --manifest` | PASS | Successful exports imported |
| `parameter-registry-build` | PASS | 1,030 unique definitions, 21 source runs |
| Manifest creation | PASS | Written to `%LOCALAPPDATA%\Axiom\inventory_exports\` |
| Revit stability | PASS | No crashes during queue execution |
| Structured dispatch | PASS | All categories dispatched directly (no NLP fallback) |

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

### BUG-009: InventoryModel persistence gap — Revit Prompt runs produce no artifacts

- **Discovered by:** Revit 2027 real testing
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** Running InventoryModel from the Revit Prompt dialog collected data (returning SUCCESS) but did not persist JSONL/Parquet/SQLite artifacts. The Python `inventory-summary --latest` command found no runs.
- **Fix:** C# `PromptCommand` now writes inventory JSON to `%LOCALAPPDATA%\Axiom\inventory_exports\`. New Python CLI command `axiom inventory-import --latest` reads these JSON exports and persists them through the standard artifact pipeline.
- **Files changed:**
  - `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` — added `PersistInventoryJson()` method
  - `src/axiom_cli/main.py` — added `inventory-import` CLI command
  - `docs/runbooks/model-inventory-runbook.md` — documented Revit → Python pipeline
- **Test coverage:** 4 new pytest tests in `TestInventoryImport`

### BUG-010: Plan-view restriction blocks InventoryModel from non-plan views

- **Discovered by:** Revit 2027 real testing
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** `PromptCommand` enforced a global `ViewPlan` check before showing the prompt dialog. This blocked InventoryModel (read-only, no model changes) from running in section, elevation, and 3D views.
- **Fix:** View restriction now only applies to model-modifying capabilities (CreateGrids, CreateLevels). InventoryModel can run from any view.
- **Files changed:**
  - `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` — conditional view check based on resolved capability

### BUG-011: InventoryModel dialog shows "Created: 0" instead of inventory counts

- **Discovered by:** Revit 2027 real testing
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** The Revit Prompt success dialog used `result.CreatedIds.Count` for all capabilities. InventoryModel doesn't create elements, so it always showed "Created: 0 element(s)".
- **Fix:** PromptDispatcher and PromptCommand now detect InventoryModel and show "Elements inventoried: X instances, Y types" and "Parameters inventoried: Z".
- **Files changed:**
  - `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` — inventory-specific success message
  - `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` — inventory-specific dialog

### BUG-012: InventoryModel full scan crashes Revit on large models

- **Discovered by:** Revit 2027 live testing on a real project (~6K instances, ~1.3K types, ~59K parameters)
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** Running `Run InventoryModel` collected all elements and serialized all parameters into a single in-memory dictionary and then a huge JSON string. On a second run, Revit crashed due to memory pressure. The default behavior was too aggressive for real-world models.
- **Fix:** Made InventoryModel staged/safe:
  - Default = summary-only scan (counts + categories, no parameter dump)
  - Category scan: `Run InventoryModel for Walls` (parameters for one category)
  - Sample scan: `Run InventoryModel sample` (first 100 elements)
  - Full scan: `Run full InventoryModel` (explicit opt-in with warning)
  - Per-element exception handling prevents one bad element from aborting the scan
  - JSON export uses streaming serialization (JsonTextWriter) instead of building in-memory string
  - Dialog output kept compact (counts + path only)
- **Behavior change:** See `docs/logs/behavior-change-ledger.md` BHV-009
- **Files changed:**
  - `src/axiom_revit/Axiom.Core/Models/InventoryParameters.cs` — added SummaryOnly, MaxElements, IncludeParameters, ScanMode
  - `src/axiom_revit/Axiom.RevitAddin/Services/ModelInventoryService.cs` — per-element try/catch, MaxElements cap, summary-only mode
  - `src/axiom_revit/Axiom.RevitAddin/Capabilities/InventoryModelCapability.cs` — respects summary mode
  - `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` — BuildInventoryArgsJson parses prompt variants
  - `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` — compact dialog, streaming JSON write
  - `src/axiom_core/prompt_resolver.py` — staged inventory prompt parsing
- **Test coverage:** 7 new pytest tests for staged prompt variants
- **Validation:** Summary mode validated on Snowdon Towers 2.0 sample model (42,881 instances, 2,276 types, 560ms, no crash). Category/sample/full scans pending validation.

### BUG-014: Full InventoryModel crashes Revit 2027 on real model (second occurrence)

- **Discovered by:** Revit 2027 live testing — full-detail scan on Snowdon Towers (~43K instances)
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** Despite staged scan modes from BUG-012, running `Run full InventoryModel` still crashed Revit 2027 on the Snowdon Towers model. The full element+parameter dump is too aggressive for live Revit even with streaming JSON and per-element try/catch. Root cause: Revit API cannot sustain deep parameter enumeration across tens of thousands of elements in a single operation.
- **Fix:** Full InventoryModel is now **disabled** from the Revit prompt. The Python prompt resolver returns `clarification_needed` instead of executing. The Revit dialog no longer suggests "Run full InventoryModel" as a next step. Safe alternatives: summary, category, level, category+level, sample.
- **Behavior change:** See `docs/logs/behavior-change-ledger.md` BHV-010, BHV-011
- **Files changed:**
  - `src/axiom_core/prompt_resolver.py` — `_resolve_inventory_prompt()` returns `clarification_needed` for full scan; added level, category+level, max threshold, plan prompt support
  - `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` — blocks full scan before execution; added level/category+level parsing
  - `src/axiom_revit/Axiom.Core/Models/InventoryParameters.cs` — added `LevelFilter` property
  - `src/axiom_revit/Axiom.RevitAddin/Services/ModelInventoryService.cs` — added level filtering logic
  - `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` — removed "Run full InventoryModel" from dialog hints
  - `docs/runbooks/model-inventory-runbook.md` — full scan marked as DISABLED; level/category+level/max modes documented
- **Test coverage:** 16 new tests including `test_full_inventory_blocked`, `test_inventory_on_level`, `test_inventory_category_on_level`, `test_inventory_category_with_max`, `test_no_prompt_executes_unbounded`, `test_planner_output_gives_safe_commands`, `test_summary_feeds_planner`
- **Re-enablement:** Full scan remains blocked. Safe chunked modes (category, level, category+level, max threshold) are now the replacement path. Use `axiom inventory-plan` to build extraction plans from summary data.
- **Validation run (2026-05-21):** 46/46 prompt resolution tests passed. All modes resolve correctly: summary (3), sample (2), category (6), level (4), category+level (4), max threshold (5), full scan blocked (6), no unbounded path (13), plan prompt (3). See `artifacts/validation_runs/safe_inventory_modes/validation_report.md`.
- **Architecture flag:** Level filter is post-collector / pre-extraction — enumerates all elements but skips parameter extraction for non-matching levels. Recommendation: optimize with `ElementLevelFilter` in future for true pre-collector filtering.
- **Live Revit 2027 validation (2026-05-21):**
  - **Summary mode:** PASS — Snowdon Towers Sample Architectural, 42,881 instances, 2,276 types, 0 errors, 61ms
  - **Category mode — Ceilings:** PASS — 78 instances, 7 types, 1,599 parameters, 0 errors
  - **Category mode — Plumbing Fixtures:** PASS — 150 instances, 31 types, 4,119 parameters, 0 errors
  - **inventory-import:** PASS — both category exports imported successfully
  - **inventory-summary:** PASS — summary output after import works
  - **Artifacts persist:** PASS — elements.jsonl, elements.parquet, parameters.parquet, run_metadata.json, summary.md
  - **Full scan:** CONFIRMED CRASH — Revit 2027 crashed during full-detail inventory (remains blocked)
  - **Whole-model batched mode:** CONFIRMED CRASH — `Run InventoryModel batch 100` crashed Revit 2027 because each batch still extracted full parameter values. Root cause: per-element value extraction (AsString/AsValueString/AsDouble) is the expensive Revit API operation, not element enumeration. **Fix (BHV-013):** `batch N` now resolves to schema discovery (metadata only, no values).
  - **Schema discovery mode:** Added as safe replacement. `Run InventoryModel schema` collects parameter definitions without value extraction.
  - **Deployment:** PASS — deploy-revit-2027.ps1 succeeded, all DLLs verified in C:\Program Files\Autodesk\Revit\Addins\2027

### BUG-015: Whole-model batched InventoryModel crashes Revit 2027 — value extraction too expensive

- **Discovered by:** Live Revit 2027 testing — `Run InventoryModel batch 100` on Snowdon Towers (~43K instances)
- **Description:** Batching alone does not prevent crashes. Each batch still performs full parameter value extraction per element (AsString, AsValueString, AsDouble, AsInteger). This is the expensive Revit API operation that causes memory pressure and crashes, regardless of batch size.
- **Root cause:** The expensive operation is parameter value extraction, not element enumeration. Even batch 100 crashed because 100 elements with 20+ parameters each still triggers thousands of expensive string/value conversions.
- **Fix:** Redesigned InventoryModel into three tiers: (1) schema discovery — metadata only, safe for whole model; (2) value sampling — limited samples per parameter; (3) full value export — blocked. `Run InventoryModel batch N` now defaults to schema discovery mode (`SchemaOnly=true`, `IncludeParameters=false`).
- **Files changed:**
  - `src/axiom_core/prompt_resolver.py` — new schema/sample_values modes, batch→schema default
  - `src/axiom_revit/Axiom.Core/Models/InventoryParameters.cs` — added SchemaOnly, SampleValues, SampleLimit
  - `src/axiom_revit/Axiom.RevitAddin/Services/ModelInventoryService.cs` — added CollectSchema(), ParameterSchemaEntry, SchemaOutput
  - `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` — schema/sample_values parsing, batch→schema
  - `src/axiom_core/inventory/extraction_planner.py` — recommends schema first
- **Test coverage:** `test_whole_model_batch_defaults_to_schema`, `test_schema_mode_whole_model`, `test_schema_mode_with_batch`, `test_schema_mode_category`, `test_sample_values_whole_model`, `test_sample_values_category`, `test_full_values_blocked`, `test_blocked_message_mentions_schema`
- **Status:** Schema mode validated PASS on Revit 2027 (Snowdon Towers). Sample values crashed — see BUG-016.

### BUG-016: Whole-model sample values crashes Revit 2027 — value accessors too expensive

- **Discovered by:** Live Revit 2027 testing — `Run InventoryModel sample values` on Snowdon Towers (~43K instances)
- **Description:** Schema mode works (metadata only). But whole-model value sampling still crashes because it invokes AsString/AsValueString/AsDouble on elements. Even with SampleLimit=10, iterating 43K elements and calling value accessors on each causes memory pressure.
- **Root cause:** Value accessor calls (AsString, AsValueString, AsDouble, AsInteger) are expensive Revit API operations even in small quantities when applied across many elements.
- **Fix:** Block whole-model `sample values` at prompt level. Require category, level, or max constraint. Hard caps: MaxElements=25, SampleLimit=5. C# defense-in-depth falls back to summary mode.
- **Files changed:**
  - `src/axiom_core/prompt_resolver.py` — whole-model sample_values returns clarification_needed
  - `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` — whole-model sample values blocked
  - `src/axiom_core/inventory/extraction_planner.py` — never recommends whole-model sample values
- **Test coverage:** `test_sample_values_whole_model_blocked`, `test_whole_model_sample_values_always_blocked`, `test_sample_values_for_category_alternate_syntax`, `test_sample_values_with_max`, `test_sample_values_on_level`, `test_sample_values_category_and_level`, `test_sample_values_plumbing_fixtures`
- **Status:** Fixed. Constrained sample values pending live Revit 2027 validation.

### BUG-017: Whole-model parameter schema crashes Revit 2027

- **Discovered by:** Live Revit 2027 validation after schema split (BHV-015)
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** `Run InventoryModel parameter schema` crashed Revit 2027 on Snowdon Towers (~43K instances). Although `CollectSchema()` only reads `param.Definition` objects (no value accessors), iterating all elements' parameter definitions is still too expensive for whole-model scans in live Revit.
- **Fix:** Block whole-model parameter schema at both Python and C# layers. Require category, level, or category+level constraint. Same pattern as BUG-016 (whole-model sample values).
- **Files changed:**
  - `src/axiom_core/prompt_resolver.py` — whole-model `parameter_schema` returns `clarification_needed`
  - `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` — returns `BLOCKED_UNSAFE` for unconstrained parameter schema
  - `src/axiom_core/inventory/extraction_planner.py` — recommends category-constrained parameter schema only
- **Allowed prompts:**
  - `Run InventoryModel for Walls parameter schema`
  - `Run InventoryModel for Ceilings parameter schema`
  - `Run InventoryModel parameter schema on Level 1`
  - `Run InventoryModel for Walls on Level 1 parameter schema`
- **Test coverage:** `test_parameter_schema_whole_model_blocked`, `test_parameter_schema_with_batch_blocked`, `test_param_schema_alias_blocked`, `test_whole_model_parameter_schema_always_blocked`, `test_parameter_schema_category`, `test_parameter_schema_ceilings`, `test_parameter_schema_plumbing`, `test_parameter_schema_on_level`, `test_parameter_schema_category_and_level`
- **Status:** Fixed. Category parameter schema pending live Revit 2027 validation.

### BUG-013: inventory-import fails on UTF-8 BOM JSON from Revit/C#

- **Discovered by:** Revit 2027 live testing — `axiom inventory-import --file` after successful summary scan
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** C# `StreamWriter` with `System.Text.Encoding.UTF8` writes a UTF-8 BOM (byte order mark, `\xEF\xBB\xBF`) at the start of the file. Python's `json.load()` with `encoding="utf-8"` raises `JSONDecodeError: Unexpected UTF-8 BOM`.
- **Fix:** Changed `inventory-import` to open JSON files with `encoding="utf-8-sig"`, which transparently strips the BOM if present while still reading normal UTF-8 correctly.
- **Files changed:**
  - `src/axiom_cli/main.py` — `encoding="utf-8"` → `encoding="utf-8-sig"`
- **Test coverage:** `TestInventoryImport::test_import_utf8_bom_json` (pytest)

### BUG-008: Revit 2027 — `ElementId.IntegerValue` removed

- **Discovered by:** Revit 2027 build validation (`deploy-revit-2027.ps1 -BuildOnly`)
- **Resolved in:** `revit-2027-compatibility` branch
- **Description:** Revit 2027 (.NET 10) removed `ElementId.IntegerValue`. The property is replaced by `ElementId.Value` (returns `long`). Three call sites in `ModelInventoryService.cs` failed to compile.
- **Fix:** Added `Axiom.Core.Compat.RevitElementIdCompat` — a static helper using `#if REVIT_2027` conditional compilation. Revit 2024 builds use `IntegerValue`, Revit 2027 builds use `Value`. `ModelInventoryService.cs` updated to call `RevitElementIdCompat.GetIntValue()` / `RevitElementIdCompat.GetValue()`.
- **Files changed:**
  - `src/axiom_revit/Axiom.Core/Compat/RevitElementIdCompat.cs` — new compat helper
  - `src/axiom_revit/Axiom.RevitAddin/Services/ModelInventoryService.cs` — 3 call sites updated
  - `Axiom.Core.csproj` — added `Compat\RevitElementIdCompat.cs` to compile items
  - `Axiom.Core.2027.csproj` — added `Compat\*.cs` glob + `REVIT_2027` define constant
  - `Axiom.RevitAddin.2027.csproj` — added `REVIT_2027` define constant
- **Test coverage:** Revit 2027 build must succeed (`dotnet build Axiom.Revit.2027.sln`). Revit 2024 build must remain unchanged.

### BUG-002: Mock execution allows both counts = 0

- **Discovered by:** Grid test harness (`count_0_both_valid_sim`)
- **Resolved in:** Commit `782333a`
- **Description:** `_mock_execute()` in `pipe_client.py` now fails with a clear error when both `HorizontalCount` and `VerticalCount` are 0, matching C# `GridCapability` validation. One orientation may be 0 as long as the other is > 0.
- **Files changed:**
  - `src/axiom_core/pipe_client.py` — added `if h_count <= 0 and v_count <= 0: return FAILED` check
- **Test coverage:** `count_0_both_invalid` (harness), `test_mock_execute_both_counts_zero_fails`, `test_mock_execute_single_orientation_zero_succeeds` (pytest)
