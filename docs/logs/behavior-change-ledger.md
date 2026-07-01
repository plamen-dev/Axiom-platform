# Behavior Change Ledger

Records meaningful prompt-resolution and capability behavior changes over time.
Each entry captures before/after behavior, related bugs, and regression test coverage.

This ledger is the historical record. Operational code should represent **current behavior only**.
See `docs/runbooks/behavior-regression-runbook.md` for philosophy and process.

---

## BHV-001: Arithmetic/progressive grid spacing returns CLARIFICATION_NEEDED

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-001 |
| **date** | 2026-05-06 |
| **capability** | CreateGrids |
| **observed_prompt** | `create 10 vertical grids spaced 5', 10', 15' and so on apart` |
| **previous_behavior** | Silently used uniform 5 ft spacing, ignoring the progressive pattern |
| **expected_behavior** | Detect arithmetic sequence and return CLARIFICATION_NEEDED |
| **current_behavior** | Returns CLARIFICATION_NEEDED asking whether user means spacing increases by 5 ft each interval |
| **status** | fixed |
| **related_bug_id** | (discovered in Revit 2027 real testing, pre-BUG numbering) |
| **related_test_case** | `arithmetic_spacing_and_so_on`, `arithmetic_spacing_etc` (grid harness); `TestGridVariableSpacingClarification::test_arithmetic_spacing_and_so_on`, `test_arithmetic_spacing_etc` (pytest) |
| **related_artifact_path** | `tests/fixtures/grid_test_cases/create_grids.yaml`, `tests/fixtures/behavior_regressions/create_grids_behavior_cases.yaml` |
| **notes** | Arithmetic detection uses context-aware number extraction from spacing phrases only, avoiding false positives from grid count numbers. |

---

## BHV-002: Generic grids with mismatched spacing count returns CLARIFICATION_NEEDED

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-002 |
| **date** | 2026-05-06 |
| **capability** | CreateGrids |
| **observed_prompt** | `create 3 grids spaced 5, 6, and 20 feet apart` |
| **previous_behavior** | Created 6 elements (3 vertical + 3 horizontal) silently, ignoring count/spacing mismatch |
| **expected_behavior** | Return CLARIFICATION_NEEDED: orientation missing, 3 grids need 2 spacings but 3 provided |
| **current_behavior** | Returns CLARIFICATION_NEEDED with options: 3 vertical, 3 horizontal, 3x3 layout, or 4 grids |
| **status** | fixed |
| **related_bug_id** | (discovered in Revit 2027 real testing, pre-BUG numbering) |
| **related_test_case** | `generic_grids_variable_spacing_no_orientation` (grid harness); `TestGridVariableSpacingClarification::test_generic_grids_variable_spacing_no_orientation` (pytest) |
| **related_artifact_path** | `tests/fixtures/grid_test_cases/create_grids.yaml`, `tests/fixtures/behavior_regressions/create_grids_behavior_cases.yaml` |
| **notes** | Mismatch validation compares `len(spacings)` against `grid_count - 1`. Missing orientation keyword with variable spacing is also flagged. |

---

## BHV-003: Grid/level keyword collision prioritizes grid intent

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-003 |
| **date** | 2026-05-05 |
| **capability** | CreateGrids / CreateLevels |
| **observed_prompt** | `Create grids at level 2` |
| **previous_behavior** | Resolved to CreateLevels because "level" keyword was detected |
| **expected_behavior** | Resolve to CreateGrids because "grid" keyword takes priority when both are present |
| **current_behavior** | Resolves to CreateGrids — grid keywords guard against level hijack |
| **status** | fixed |
| **related_bug_id** | (Devin Review finding, fixed in PR #2) |
| **related_test_case** | `cross_capability_levels` (grid harness); `test_grid_prompt_not_hijacked_by_level` (pytest) |
| **related_artifact_path** | `tests/fixtures/grid_test_cases/create_grids.yaml`, `tests/fixtures/behavior_regressions/create_levels_behavior_cases.yaml` |
| **notes** | Both Python and C# resolvers now check for grid keywords before allowing level resolution. |

---

## BHV-004: Rows/columns without "grid" keyword returns CLARIFICATION_NEEDED

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-004 |
| **date** | 2026-05-04 |
| **capability** | CreateGrids |
| **observed_prompt** | `Create 4 rows spaced 15 ft apart` |
| **previous_behavior** | Silently failed or created unexpected output |
| **expected_behavior** | Return CLARIFICATION_NEEDED asking if user means Revit gridlines |
| **current_behavior** | Returns CLARIFICATION_NEEDED: "Did you mean Revit gridlines arranged as 4 horizontal rows?" |
| **status** | fixed |
| **related_bug_id** | BUG-001 |
| **related_test_case** | `horiz_rows_no_grid_keyword`, `columns_rows_no_grid_keyword`, `clarify_columns_only`, `clarify_rows_only` (grid harness); `test_rows_only_clarification`, `test_columns_only_clarification` (pytest) |
| **related_artifact_path** | `tests/fixtures/grid_test_cases/create_grids.yaml`, `tests/fixtures/behavior_regressions/create_grids_behavior_cases.yaml` |
| **notes** | Explicit prompts containing "grid", "grids", "gridline", or "gridlines" still execute normally without clarification. |

---

## BHV-005: InventoryModel reports inventory counts, not "Created: 0"

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-005 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel` |
| **previous_behavior** | Dialog showed "Created: 0 element(s)" |
| **expected_behavior** | Show "Elements inventoried: X instances, Y types" and "Parameters inventoried: Z" |
| **current_behavior** | Dialog shows inventory-specific counts and full JSON export path |
| **status** | fixed |
| **related_bug_id** | BUG-011 |
| **related_test_case** | (Revit 2027 manual validation) |
| **related_artifact_path** | `tests/fixtures/behavior_regressions/inventory_model_behavior_cases.yaml` |
| **notes** | PromptDispatcher and PromptCommand both detect InventoryModel and use custom success message format. |

---

## BHV-006: InventoryModel runs from any view (not plan-only)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-006 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel` (from a 3D view) |
| **previous_behavior** | Blocked with "Prompt execution requires a plan view" |
| **expected_behavior** | InventoryModel is read-only and should run from any view |
| **current_behavior** | InventoryModel runs from floor plan, section, elevation, and 3D views |
| **status** | fixed |
| **related_bug_id** | BUG-010 |
| **related_test_case** | (Revit 2027 manual validation) |
| **related_artifact_path** | `tests/fixtures/behavior_regressions/inventory_model_behavior_cases.yaml` |
| **notes** | Plan-view restriction now only applies to model-modifying capabilities (CreateGrids, CreateLevels). |

---

## BHV-007: InventoryModel Revit Prompt persists JSON for Python import

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-007 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel` |
| **previous_behavior** | Inventory collected but no artifacts persisted; `inventory-summary --latest` found nothing |
| **expected_behavior** | Revit writes JSON export; Python CLI imports to Parquet/SQLite artifacts |
| **current_behavior** | C# writes to `%LOCALAPPDATA%\Axiom\inventory_exports\`; `axiom inventory-import --file <path>` persists to standard artifacts |
| **status** | fixed |
| **related_bug_id** | BUG-009 |
| **related_test_case** | `TestInventoryImport::test_import_from_json_file`, `test_import_preserves_parameter_details` (pytest) |
| **related_artifact_path** | `tests/fixtures/behavior_regressions/inventory_model_behavior_cases.yaml` |
| **notes** | Dialog now shows full export path. `--file` argument handles cross-user-profile scenarios where `%LOCALAPPDATA%` differs between Revit and PowerShell. |

---

## BHV-008: Spacing count vs grid count mismatch returns CLARIFICATION_NEEDED

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-008 |
| **date** | 2026-05-06 |
| **capability** | CreateGrids |
| **observed_prompt** | `create 3 vertical grids with spacings 10, 5, 20, 10` |
| **previous_behavior** | Silently adjusted count from 3 to 5 to match 4 spacings |
| **expected_behavior** | Return CLARIFICATION_NEEDED: 3 grids need 2 spacings, but 4 provided |
| **current_behavior** | Returns CLARIFICATION_NEEDED with two options: adjust count or trim spacings |
| **status** | fixed |
| **related_bug_id** | (related to BHV-002 validation logic) |
| **related_test_case** | `mismatch_count_spacing` (grid harness); `TestGridVariableSpacingClarification::test_count_3_with_3_spacings_clarification` (pytest) |
| **related_artifact_path** | `tests/fixtures/grid_test_cases/create_grids.yaml`, `tests/fixtures/behavior_regressions/create_grids_behavior_cases.yaml` |
| **notes** | Previously the YAML test case expected the resolver to silently adjust. Now expects CLARIFICATION_NEEDED. |

---

## BHV-009: InventoryModel default is summary-only (crash prevention)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-009 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel` |
| **previous_behavior** | Collected ALL elements and ALL parameters into memory, serialized to a single huge JSON string. Crashed Revit on a real project with ~6K instances and ~59K parameters. |
| **expected_behavior** | Default scan should be safe for any model size. Full parameter dump should require explicit opt-in. |
| **current_behavior** | Default = summary-only (counts + category breakdown, no parameter dump). Category scan, sample scan (100 elements), and full scan available via explicit prompts. Per-element exception handling prevents individual element errors from aborting the scan. Streaming JSON write avoids huge in-memory strings. |
| **status** | fixed |
| **related_bug_id** | BUG-012 |
| **related_test_case** | `TestInventoryPromptResolver::test_default_is_summary_safe`, `test_full_inventory_scan`, `test_inventory_sample`, `test_inventory_category_walls`, `test_inventory_category_doors` (pytest) |
| **related_artifact_path** | `tests/fixtures/behavior_regressions/inventory_model_behavior_cases.yaml` |
| **notes** | Staged workflow: summary → category → sample → full. See `docs/runbooks/model-inventory-runbook.md`. |

## BHV-010: Full InventoryModel disabled — returns CLARIFICATION_NEEDED

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-010 |
| **date** | 2026-05-20 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run full InventoryModel` |
| **previous_behavior** | Executed full element+parameter scan. Crashed Revit 2027 twice on Snowdon Towers model (~43K instances). |
| **expected_behavior** | Full scan should not execute from normal Revit prompt until chunked extraction is implemented. |
| **current_behavior** | Returns `clarification_needed` with message: "Full inventory is currently disabled for live Revit sessions." Suggests summary, sample, or category scans instead. |
| **status** | fixed |
| **related_bug_id** | BUG-014 |
| **related_test_case** | `TestInventoryPromptResolver::test_full_inventory_blocked` (pytest) |
| **related_artifact_path** | `tests/fixtures/behavior_regressions/inventory_model_behavior_cases.yaml` |
| **notes** | Full scan will be re-enabled when chunked category+level extraction is implemented. Use `axiom inventory-plan` with summary JSON to plan safe extraction. |

## BHV-011: Chunked inventory extraction — level, category+level, max threshold, plan prompt

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-011 |
| **date** | 2026-05-20 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel for Walls on Level 1`, `Run InventoryModel on Level 1`, `inventory plan`, `max 500` |
| **previous_behavior** | Only summary, category, and sample modes supported. No level filtering, no max threshold, no plan prompt. |
| **expected_behavior** | Safe chunked extraction by category, level, category+level, and max element threshold. Plan prompt guides user to CLI planner. |
| **current_behavior** | New scan modes: `level` (LevelFilter), `category_level` (CategoryFilter+LevelFilter), `max N`/`limit N` (MaxElements cap on any mode). `inventory plan` / `extraction plan` returns guidance to use `axiom inventory-plan` CLI. Full scan remains blocked. |
| **status** | fixed |
| **related_bug_id** | BUG-014 |
| **related_test_case** | `TestInventoryPromptResolver::test_inventory_on_level`, `test_inventory_category_on_level`, `test_inventory_category_with_max`, `test_inventory_plan_prompt`, `test_no_prompt_executes_unbounded` (pytest) |
| **related_artifact_path** | `src/axiom_core/prompt_resolver.py`, `src/axiom_revit/Axiom.Core/Models/InventoryParameters.cs`, `src/axiom_revit/Axiom.RevitAddin/Services/ModelInventoryService.cs` |
| **notes** | C# ModelInventoryService now supports LevelFilter. PromptDispatcher parses "on Level X" and "for Category on Level X" prompts. Python prompt_resolver mirrors all modes. No prompt path leads to unbounded full extraction. **Validation (2026-05-21):** 46/46 prompt resolution tests passed. Level filter is post-collector / pre-extraction (safe but not optimal — see architecture note in runbook). |

## BHV-012: Batched/continuation extraction — limit/max/batch → BatchSize (not hard cap)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-012 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel for Walls batch 10000`, `limit 10000`, `max 5000` |
| **previous_behavior** | `max N` / `limit N` set `MaxElements` — a hard cap that took only the first N elements and stopped. |
| **expected_behavior** | `batch N` / `limit N` / `max N` sets `BatchSize` — continuation extraction that processes ALL matching elements in batches of N. Each batch saved independently so partial results survive crashes. |
| **current_behavior** | `BatchSize` param added to `InventoryParameters`. C# `CollectInventoryBatched()` yields batches via `IEnumerable<InventoryBatchOutput>`. Python resolver emits `BatchSize` instead of `MaxElements`. `MaxElements` still used only by sample mode (hard cap of 100). CLI `inventory-combine` merges batch outputs. |
| **status** | fixed |
| **related_bug_id** | BUG-014 |
| **related_test_case** | `TestBatchedExtraction::test_batch_keyword_sets_batch_size`, `test_limit_keyword_sets_batch_size`, `test_batch_with_level_filter`, `test_batch_with_category_level`, `test_no_batch_unbounded`, `TestInventoryCombineCLI::test_combine_batch_files`, `test_combine_with_manifest` |
| **related_artifact_path** | `src/axiom_core/prompt_resolver.py`, `src/axiom_revit/Axiom.Core/Models/InventoryParameters.cs`, `src/axiom_revit/Axiom.RevitAddin/Services/ModelInventoryService.cs`, `src/axiom_cli/main.py` |
| **notes** | Semantic change: limit/max/batch keywords now set `BatchSize` for paginated continuation, not `MaxElements` for hard cap. Sample mode still uses `MaxElements=100`. C# `PromptDispatcher` and `PromptCommand` updated to handle batched output with per-batch JSON files and manifest. **Update (2026-05-21):** Whole-model batching added \u2014 `Run InventoryModel batch N` (no category/level) resolves to `ScanMode=batched` with `SummaryOnly=false`, processing entire model in bounded batches. This is distinct from blocked full scan. Bare `Run InventoryModel` (no batch number) still defaults to summary mode. Planner now recommends whole-model batching as alternative. **Update (2026-05-06, schema pivot):** Whole-model batch crashed Revit 2027 even at batch 100 — `batch N` now resolves to `ScanMode=schema` with `SchemaOnly=true`. See BHV-013. |

## BHV-013: Schema-centric inventory — schema discovery vs value sampling vs full export

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-013 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel schema`, `Run InventoryModel sample values`, `Run InventoryModel batch 100` |
| **previous_behavior** | `Run InventoryModel batch 100` resolved to `ScanMode=batched` with `IncludeParameters=true` — full value extraction in batches. Crashed Revit 2027 even at batch 100 because per-element parameter value extraction (AsString/AsValueString/AsDouble) is the expensive operation, not element enumeration. |
| **expected_behavior** | Separate inventory into three tiers: (1) schema discovery — metadata only, safe for whole model; (2) value sampling — limited samples per parameter, safe with caps; (3) full value export — blocked. `batch N` without category/level defaults to schema, not full values. |
| **current_behavior** | New modes: `schema`, `category_schema`, `sample_values`, `category_sample_values`. `batch N` alone resolves to schema discovery. `SchemaOnly` and `SampleValues`/`SampleLimit` added to InventoryParameters. C# `CollectSchema()` iterates elements but only reads Definition objects. `full values` keyword added to blocked list. Planner recommends schema discovery first. |
| **status** | fixed |
| **related_bug_id** | BUG-015 |
| **related_test_case** | `test_whole_model_batch_defaults_to_schema`, `test_schema_mode_whole_model`, `test_schema_mode_with_batch`, `test_schema_mode_category`, `test_sample_values_whole_model`, `test_sample_values_category`, `test_full_values_blocked`, `test_blocked_message_mentions_schema` |
| **related_artifact_path** | `src/axiom_core/prompt_resolver.py`, `src/axiom_revit/Axiom.Core/Models/InventoryParameters.cs`, `src/axiom_revit/Axiom.RevitAddin/Services/ModelInventoryService.cs`, `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` |
| **notes** | Root cause: full parameter value extraction is the expensive Revit API operation. Schema discovery reads only `param.Definition` properties (Name, StorageType, IsReadOnly, BuiltInParameter) which is lightweight. Value sampling caps at SampleLimit (default 10) unique values per parameter. Full value extraction remains blocked. **Update:** Schema validated PASS. Whole-model sample values crashed — see BHV-014. |

## BHV-014: Whole-model value sampling blocked — requires category/level/max constraint

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-014 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel sample values` |
| **previous_behavior** | Resolved to `ScanMode=sample_values` with `SampleValues=true`, `SampleLimit=10` — whole-model value sampling. Crashed Revit 2027. |
| **expected_behavior** | Whole-model `sample values` returns `clarification_needed`. Constrained sample values allowed. |
| **current_behavior** | `Run InventoryModel sample values` → blocked. `Run InventoryModel sample values for Walls` → allowed (SampleLimit=5, MaxElements=25). |
| **status** | fixed |
| **related_bug_id** | BUG-016 |
| **related_test_case** | `test_sample_values_whole_model_blocked`, `test_whole_model_sample_values_always_blocked`, `test_sample_values_for_category_alternate_syntax`, `test_sample_values_with_max`, `test_sample_values_on_level`, `test_sample_values_category_and_level`, `test_sample_values_plumbing_fixtures` |
| **related_artifact_path** | `src/axiom_core/prompt_resolver.py`, `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs`, `src/axiom_core/inventory/extraction_planner.py` |
| **notes** | Hard caps: MaxElements=25, SampleLimit=5. Category filter detection extended to support "values for X" and "schema for X" patterns. Planner never recommends whole-model sample values. |

## BHV-015: Schema mode split into object_schema and parameter_schema

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-015 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel schema` |
| **previous_behavior** | ScanMode=`schema` with SchemaOnly=true — collected ElementId, Category, ClassName, Name, LevelName, IsType (object inventory with no parameters). Misleadingly named "schema" despite collecting zero parameter definitions. `CollectSchema()` method existed in C# but was never called. |
| **expected_behavior** | Clear distinction: `object_schema` = element/class inventory; `parameter_schema` = parameter definitions (name, type, built-in ID, read-only, instance/type, observed count). |
| **current_behavior** | `Run InventoryModel schema` → `object_schema`. `Run InventoryModel parameter schema` → `parameter_schema` (calls `CollectSchema()`, reads `param.Definition` objects). Category variants: `category_object_schema`, `category_parameter_schema`. C# capability routes `ParameterSchemaOnly=true` to `CollectSchema()`. Output includes `instance_count`, `type_count`, `element_count` (sum of both) for clarity. |
| **status** | fixed |
| **related_bug_id** | — |
| **related_test_case** | `test_object_schema_whole_model`, `test_object_schema_with_batch`, `test_object_schema_category`, `test_parameter_schema_whole_model`, `test_parameter_schema_with_batch`, `test_parameter_schema_category`, `test_param_schema_alias` |
| **related_artifact_path** | `src/axiom_core/prompt_resolver.py`, `src/axiom_revit/Axiom.Core/Models/InventoryParameters.cs`, `src/axiom_revit/Axiom.RevitAddin/Capabilities/InventoryModelCapability.cs`, `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` |
| **notes** | Live Revit 2027 validation: object_schema produced 16MB JSON with 45,157 elements (42,881 instances + 2,276 types), parameter_count=0. parameter_schema pending live validation. |

## BHV-016: Whole-model parameter schema blocked after Revit 2027 crash

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-016 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel parameter schema` |
| **previous_behavior** | Resolved to `parameter_schema` (ScanMode) and would execute `CollectSchema()` across all ~43K elements. Crashed Revit 2027. |
| **expected_behavior** | Block whole-model parameter schema. Require category, level, or category+level constraint. |
| **current_behavior** | `Run InventoryModel parameter schema` → `clarification_needed` with blocked message. Allowed: `Run InventoryModel for Walls parameter schema`, `parameter schema on Level 1`, etc. C# defense-in-depth: `BLOCKED_UNSAFE` for unconstrained. |
| **status** | fixed |
| **related_bug_id** | BUG-017 |
| **related_test_case** | `test_parameter_schema_whole_model_blocked`, `test_parameter_schema_with_batch_blocked`, `test_param_schema_alias_blocked`, `test_whole_model_parameter_schema_always_blocked`, `test_parameter_schema_category`, `test_parameter_schema_ceilings`, `test_parameter_schema_plumbing`, `test_parameter_schema_on_level`, `test_parameter_schema_category_and_level` |
| **related_artifact_path** | `src/axiom_core/prompt_resolver.py`, `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs`, `src/axiom_core/inventory/extraction_planner.py` |
| **notes** | Same pattern as BHV-014 (whole-model sample values). Iterating 43K elements' param.Definition objects is still too expensive even without value accessors. Category-constrained parameter schema pending live validation. |


## BHV-017: Full registry coverage workflow — planner-driven parameter discovery

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-017 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `axiom inventory-plan --mode parameter-schema`, `axiom inventory-import-batch`, `axiom parameter-registry-build` |
| **previous_behavior** | Planner sorted all categories smallest-to-largest with no priority ordering. Registry builder deduped by 5-tuple key. No batch import. No object registry candidate. No coverage analysis. |
| **expected_behavior** | Priority categories first, then remaining by size. Registry builder uses 8-tuple dedup key. Batch import available. Object registry candidate from object_schema. Coverage summary reports missing categories. |
| **current_behavior** | `inventory-plan` outputs priority categories first (Walls, Doors, Windows, etc.) then remaining smallest-to-largest. Blocked commands explicitly excluded. `inventory-import-batch` filters by scan_mode. `parameter-registry-build` uses 8-tuple dedup, tracks SourceModels/RunIds, reports coverage gaps. Object schema import produces object registry candidate. |
| **status** | implemented |
| **related_bug_id** | — |
| **related_test_case** | `TestRegistryCoverageWorkflow` (8 tests) |
| **related_artifact_path** | `src/axiom_core/inventory/extraction_planner.py`, `src/axiom_core/inventory/storage.py`, `src/axiom_cli/main.py` |
| **notes** | Automatic multi-category execution in Revit deferred to future PR. Current workflow: object_schema → plan → copy-paste prompts → batch import → registry build. |


## BHV-018: Parameter schema plan execution queue

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-018 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel parameter schema plan`, `Run InventoryModel parameter schema plan max 10`, `Run InventoryModel parameter schema plan priority only`, `Run InventoryModel parameter schema plan resume` |
| **previous_behavior** | No automatic multi-category execution. User had to copy-paste up to 279 individual category prompts from the plan. |
| **expected_behavior** | Single prompt executes category-by-category parameter schema discovery from plan JSON. Supports max N, priority-only, and resume. Writes manifest with per-category status. |
| **current_behavior** | `Run InventoryModel parameter schema plan` reads latest `parameter_schema_plan.json`, executes each category's `category_parameter_schema` sequentially. Each category writes its own export JSON. Manifest written to `%LOCALAPPDATA%\Axiom\inventory_exports\parameter_schema_manifest_<timestamp>.json`. `max 10` limits categories. `priority only` filters to priority set. `resume` skips already-successful categories from latest manifest. Failed categories recorded without stopping execution. Dialog shows completed/failed/skipped counts and next CLI command. `inventory-import-batch --manifest <path>` imports successful exports from manifest. |
| **status** | implemented |
| **related_bug_id** | - |
| **related_test_case** | `TestParameterSchemaPlanExecution` (11 tests) |
| **related_artifact_path** | `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs`, `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs`, `src/axiom_core/prompt_resolver.py`, `src/axiom_cli/main.py` |
| **notes** | Safety: only executes `category_parameter_schema` jobs. Whole-model parameter schema, sample values, full inventory remain blocked. Manifest structure supports future resume even if resume is not fully tested in current PR. |


## BHV-019: Plan handoff path fix and diagnostics

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-019 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `axiom inventory-plan --mode parameter-schema`, `axiom inventory-plan-status`, `Run InventoryModel parameter schema plan` |
| **previous_behavior** | `inventory-plan` wrote plan JSON to repo artifacts only. Revit plan executor searched `%LOCALAPPDATA%\Axiom\inventory_plans\` subdirectories then repo artifacts. Mismatch caused "plan not found" errors. No plan diagnostics command. Manifest lacked per-category `prompt` field. Registry coverage did not report priority categories. |
| **expected_behavior** | Plan written to both repo and LocalAppData. Revit searches LocalAppData/latest first. Dialog shows searched paths. Diagnostics command available. Manifest includes prompt per category. Registry coverage reports priority coverage. |
| **current_behavior** | `inventory-plan` writes to repo artifacts AND copies to `%LOCALAPPDATA%\Axiom\inventory_plans\latest\parameter_schema_plan.json` and `%LOCALAPPDATA%\Axiom\inventory_plans\parameter_schema_plan.json`. Revit search order: LocalAppData/latest → flat → subdirs → repo artifacts. "Not found" dialog lists all searched paths. `axiom inventory-plan-status` reports plan locations, existence, category counts, next Revit prompts. Manifest per-category entries include `prompt` field. Registry coverage reports covered/missing priority categories. |
| **status** | implemented |
| **related_bug_id** | — |
| **related_test_case** | `TestPlanHandoff`, `TestManifestImport` |
| **related_artifact_path** | `src/axiom_cli/main.py`, `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs`, `src/axiom_core/inventory/extraction_planner.py` |
| **notes** | Hardening packet for merge-readiness. No new features. |


## BHV-020: Structured dispatch for plan execution — bypass NLP resolver

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-020 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel parameter schema plan`, `Run InventoryModel parameter schema plan max 10` |
| **previous_behavior** | Plan executor generated a prompt string per category (e.g. "Run InventoryModel for Grids parameter schema") and dispatched it through the NLP resolver. Categories not in the hardcoded `knownCategories` list (Grids, Views, Sheets, Materials, Project Information, etc.) fell through to the whole-model parameter schema block, producing BLOCKED_UNSAFE. Result: 231/270 categories failed with BLOCKED_UNSAFE in full plan run. |
| **expected_behavior** | Plan executor dispatches directly using structured parameters (CategoryFilter + ScanMode) without NLP parsing. All categories in the plan execute or are explicitly skipped with a reason. |
| **current_behavior** | `ExecuteParameterSchemaPlan()` calls `dispatcher.DispatchCategoryParameterSchema(doc, category)` which builds args JSON directly with `CategoryFilter`, `ScanMode = "category_parameter_schema"`, `ParameterSchemaOnly = true`. Human-readable prompt still recorded in manifest for traceability. Non-executable categories ((No Category), <Unnamed>) pre-filtered as `skipped_unsupported`. Manifest distinguishes: `success`, `failed`, `skipped_unsupported`, `skipped_resume`, `skipped_no_elements`. |
| **status** | validated |
| **related_bug_id** | — |
| **related_test_case** | `test_planner_skips_non_executable_categories`, `test_structured_dispatch_bypasses_resolver` |
| **related_artifact_path** | `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs`, `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs`, `src/axiom_core/inventory/extraction_planner.py` |
| **notes** | Live Revit 2027 validation: max 10 = 10/10 completed, priority only = 16/16 completed, full plan = 278/278 successful, 0 BLOCKED_UNSAFE. |


## BHV-021: Export path collision fix — unique filenames per category

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-021 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `Run InventoryModel parameter schema plan` |
| **previous_behavior** | `PersistInventoryJson` used `inv_YYYYMMDD_HHmmss.json` — second-level timestamp precision. Multiple categories processed within the same second wrote to the same filename, causing 252 overwrites out of 278 exports (only 26 unique files). |
| **expected_behavior** | Every category export gets a unique filename. No overwrites. |
| **current_behavior** | Filename format: `inv_YYYYMMDD_HHmmss_fff_NNN_category_slug.json`. Milliseconds + atomic sequence counter + sanitized category name. 278 exports → 278 unique files, 0 duplicates. |
| **status** | validated |
| **related_bug_id** | BUG-018 |
| **related_test_case** | `test_unique_export_paths_within_same_second`, `test_manifest_duplicate_detection`, `test_import_batch_warns_on_duplicate_paths`, `test_category_slug_sanitization` |
| **related_artifact_path** | `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` |
| **notes** | Atomic counter uses `System.Threading.Interlocked.Increment` for thread safety. Category slug sanitizes spaces to `_` and removes special characters. Manifest duplicate detection added to `inventory-import-batch` as defense-in-depth. |


## BHV-022: Registry coverage reporting — executed vs definitions vs zero-definitions

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-022 |
| **date** | 2026-05-06 |
| **capability** | InventoryModel |
| **observed_prompt** | `axiom parameter-registry-build --from-inventory ... --object-registry ...` |
| **previous_behavior** | Registry summary reported "Categories with coverage: 33" and "Categories missing coverage: 171" — misleading because many categories were successfully executed but had zero parameter definitions (tags, annotation symbols, etc.). |
| **expected_behavior** | Distinguish: executed categories, categories with definitions, categories with zero definitions, categories not executed/imported. |
| **current_behavior** | Summary reports: categories executed successfully (278), categories with parameter definitions (33+), categories with zero parameter definitions (245), discovered object categories (204), not executed/imported (0). Scans `run_metadata.json` to identify zero-definition categories. Summary.md includes "Executed With Zero Parameter Definitions" section. |
| **status** | validated |
| **related_bug_id** | — |
| **related_test_case** | `test_registry_zero_definitions_reporting` |
| **related_artifact_path** | `src/axiom_cli/main.py` |
| **notes** | Reporting/accounting change only. No extraction behavior modified. Zero-definition categories are genuine — Revit tags, annotation symbols, and similar categories have elements but no exposed parameter definitions. |


## BHV-023: SetParameterValue interactive preview → apply with element-ID reuse

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-023 |
| **date** | 2026-05-06 |
| **capability** | SetParameterValue |
| **observed_prompt** | `Set Comments to Axiom test 001 for 1 Walls` |
| **previous_behavior** | Preview result was a static TaskDialog with only OK/Close. To apply, the user had to re-type the prompt with the `Apply` keyword; apply then recollected elements by category, which could target a different set than was previewed. |
| **expected_behavior** | Preview dialog is interactive (Apply / Open evidence folder / Close). Apply is only available after a successful preview, reuses the exact previewed element IDs, runs in a transaction, and blocks if any previewed element no longer resolves. |
| **current_behavior** | Preview dialog offers command-link buttons. On successful preview the previewed elements are selected and zoomed/focused in Revit (`UIDocument.Selection.SetElementIds` + `UIDocument.ShowElements`, read-only/best-effort) with dialog note "Previewed element(s) selected in Revit for review." Apply re-executes `SetParameterValue` in apply mode with `ElementIds` = previewed editable IDs via `PromptDispatcher.DispatchWithArgs`, resolving elements with `ParameterEditService.CollectElementsByIds` + `RevitElementIdCompat.FromLong`. If any ID is missing, apply is blocked with an explanation and the model is not modified. Apply evidence records `initiated_from: preview_approval`, `targeted_by_ids: true`, and `preview_evidence_path`. The `Apply Set ...` prompt fallback remains supported (`initiated_from: prompt`). |
| **status** | pending live validation |
| **related_bug_id** | — |
| **related_test_case** | C# (no Python harness) — live Revit 2027 validation |
| **related_artifact_path** | `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs`, `src/axiom_revit/Axiom.RevitAddin/Capabilities/SetParameterValueCapability.cs`, `src/axiom_revit/Axiom.RevitAddin/Services/ParameterEditService.cs`, `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs`, `src/axiom_revit/Axiom.Core/Models/SetParameterValueParameters.cs`, `src/axiom_revit/Axiom.Core/Compat/RevitElementIdCompat.cs` |
| **notes** | Hard cap 5 still enforced (also on the ElementIds path). Preview remains read-only. Safety constraints (text instance parameters only, writable only, category-constrained, active-view default) unchanged. |

## BHV-024: SetParameterValue apply-from-preview linked preview evidence snapshot

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-024 |
| **date** | 2026-05-06 |
| **capability** | SetParameterValue |
| **observed_prompt** | `Set Comments to Axiom test 001 for 1 Walls` → Apply from preview dialog |
| **previous_behavior** | Apply run folder contained `request.json`, `changes.json`, `result_summary.md`, and a `preview_evidence_path` pointer only. There was no durable copy of the preview snapshot inside the apply run, so audit required following the pointer to a separate run folder that could be deleted/moved independently. |
| **expected_behavior** | Apply runs initiated from preview approval contain a durable linked preview snapshot and reconciliation metadata, and `result_summary.md` surfaces the preview path, snapshot status, and whether applied IDs match previewed IDs. A missing `preview.json` must not fail an apply that already modified the model. |
| **current_behavior** | On apply-from-preview, `PromptCommand.WriteLinkedPreviewArtifacts` copies the preview run's `preview.json` into the apply run folder as `linked_preview.json` and writes `linked_preview_metadata.json` with `preview_evidence_path`, `copied_at`, `source_preview_run_id`, `apply_run_id`, `element_ids_previewed`, `element_ids_applied`, `target_ids_match`, `initiated_from: preview_approval`, and `copy_status`. `result_summary.md` adds **Preview evidence path**, **Linked preview snapshot**, and **Target IDs match preview**. If `preview.json` is missing, the apply is not failed — `copy_status: missing_preview_json` is recorded and a warning is appended to `result_summary.md`. |
| **status** | pending live validation |
| **related_bug_id** | — |
| **related_test_case** | C# (no Python harness) — live Revit 2027 validation |
| **related_artifact_path** | `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` |
| **notes** | No change to model behavior, element selection behavior, hard cap 5, or exact-ID reuse. No changes to CreateGrids/CreateLevels/InventoryModel. Linking is best-effort and never undoes a successful model update. |

## BHV-025: Validation Automation Loop v0 — semi-autonomous PR/live-validation runner

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-025 |
| **date** | 2026-05-06 |
| **capability** | ValidationLoop (new harness; not a Revit capability) |
| **observed_prompt** | `poetry run axiom validation-run --scenario set_parameter_preview_apply --phase pre` / `--phase scan` |
| **previous_behavior** | Around the single live-Revit human step, every other step (record context/git, pull, run tests + ruff, deploy, capture DLL timestamps, print manual steps, scan evidence across user profiles, validate conditions, classify pass/fail, write a result summary) was performed manually and reported by hand in chat. There was no structured validation-run artifact bundle. |
| **expected_behavior** | A single command automates everything before and after the live Revit step and emits a structured `artifacts/validation_runs/<run_id>/` bundle with a deterministic pass/fail classification, leaving only the live Revit interaction to the human. |
| **current_behavior** | `axiom validation-run` (and `scripts/local/run-validation-loop.ps1`) runs phases `pre` (context/git/optional pull/tests+ruff/optional deploy/DLL timestamps/manual steps), `scan` (cross-profile evidence scan → 12 v0 conditions → classification), or `all`. Evidence is searched across all user profiles' `…\AppData\Local\Axiom\parameter_edit_runs`. Classification uses ordered precedence: tests_failed → needs_admin → deploy_failed → revit_manual_step_pending → evidence_missing → evidence_mismatch → pass. The bounded retry budget (`--max-attempts`, default `DEFAULT_MAX_ATTEMPTS=5`) is configurable and recorded in `request.json`/`pass_fail.json` (`max_attempts`, `attempts_made`); it drives re-scanning while the add-in writes evidence asynchronously, and is overridable to confirm larger testing concepts. All subprocesses use fixed argv lists (never a shell string); branch/scenario inputs are validated against conservative patterns. |
| **status** | implemented (Python harness; ruff + pytest green) |
| **related_bug_id** | — |
| **related_test_case** | `tests/test_validation_loop.py` (29 tests), `tests/test_local_runner.py::TestActionAllowlist::test_validation_loop_*` |
| **related_artifact_path** | `src/axiom_core/validation_loop.py`, `src/axiom_cli/main.py` (validation-run command), `scripts/local/run-validation-loop.ps1`, `tools/local_runner/local_runner.py`, `tools/local_runner/examples/test_validation_loop.task.json`, `docs/runbooks/validation-loop-runbook.md` |
| **notes** | No new Revit capability and no change to SetParameterValue/CreateGrids/CreateLevels/InventoryModel behavior. Live Revit remains the one human step. This is the throughput tool; the bounded-retry/promotion-scoring discovery machinery (spec §9) is the next target and explicitly out of scope here. SetParameterValue evidence schema was consumed read-only (no metadata changes were required). |

## BHV-026: Axiom Automation Bridge v0 - external driver + durable evidence

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-026 |
| **date** | 2026-05-06 |
| **capability** | AutomationBridge (new driver/harness; not a Revit capability) |
| **observed_prompt** | `poetry run axiom bridge-execute --capability InventoryModel` (live) / `--simulate` (mock) |
| **previous_behavior** | No software path existed for an external process (CI / Validation Loop) to send an execution request to a running Revit add-in and capture durable evidence. The named-pipe bridge (PR #2: `AxiomPipeServer` + `PipeClient`) existed but had no non-interactive driver, no evidence capture, and no pass/fail classification for an outside-Revit caller. |
| **expected_behavior** | A single non-interactive command sends one capability `execute_tool` request over the existing named pipe to the running add-in, the add-in executes it via ExternalEvent, and the caller writes durable evidence proving request sent -> received -> executed -> result -> classified, with no human interaction after dispatch. |
| **current_behavior** | `axiom bridge-execute` (driver `axiom_core.automation_bridge.execute_capability_via_bridge`) reuses `PipeClient` verbatim, defaults `InventoryModel` to safe summary mode (`SummaryOnly=true`, `ScanMode=summary`; no full scan, no model mutation), and writes `artifacts/validation_runs/<run_id>/bridge/{bridge_request.json,bridge_response.json,bridge_result_summary.md,pass_fail.json}`. Classification: `pass` / `capability_failed` / `bridge_unavailable` / `bridge_error`, with evidence written for every outcome. Exit codes: 0 pass, 1 fail/unavailable/error, 2 bad `--args-json`. `windows-revit-validation.yml` gains opt-in `run_bridge` / `bridge_simulate` / `bridge_capability` dispatch inputs to drive it on Axiom-01 after the add-in is loaded. |
| **status** | validated - live Revit acceptance passed on Axiom-01 (Revit 2027). Full chain proven: GitHub Actions -> Axiom-01 self-hosted runner -> validation workflow -> Automation Bridge -> named pipe -> running Revit 2027 -> InventoryModel capability -> evidence collection -> artifact upload, with no human interaction after dispatch. (Python harness: full pytest 546 passed/1 skipped + ruff green.) |
| **related_bug_id** | — |
| **related_test_case** | `tests/test_automation_bridge.py` (classifier + driver + CLI vs mock PipeClient) |
| **related_artifact_path** | `src/axiom_core/automation_bridge.py`, `src/axiom_cli/main.py` (bridge-execute), `.github/workflows/windows-revit-validation.yml`, `docs/architecture/revit-automation-bridge-v0.md` |
| **notes** | No new Revit capability; no change to CreateGrids/CreateLevels/InventoryModel/SetParameterValue behavior. No new transport (Option A only; no Job Queue / Local HTTP). No UI automation. Establishes the Axiom-outside <-> Axiom-inside communication boundary for the verification factory. |

## BHV-027: Evidence Promotion safety hardening — duplicate + conflict handling (PR #148)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-027 |
| **date** | 2026-06-23 |
| **capability** | EvidencePromotionLoop (M2 evidence-to-confidence/readiness coordinator; not a Revit capability) |
| **observed_prompt** | `poetry run axiom capability-evidence-apply --evidence artifacts/execution_chain/<run>/evidence.json --json-output` (same evidence applied twice; or evidence whose `evidence.json` and sibling `trace.json` disagree on PASS/FAIL) |
| **previous_behavior** | (PR #147) Re-applying the exact same evidence record always accumulated again — `execution_count`/`success_count`/`failure_count` incremented every time, silently inflating confidence. Outcome was resolved by source **priority** (`bundle.passed` → `bundle.status` → `trace.status`), so when signals disagreed the highest-priority source silently won and mutated confidence/readiness. |
| **expected_behavior** | Re-applying an already-accepted evidence record must not mutate confidence/readiness a second time, and must remain queryable. Disagreeing outcome signals must be quarantined (no mutation) rather than silently resolved by priority. Distinct evidence from distinct runs must still accumulate. |
| **current_behavior** | `apply()` computes a stable per-record fingerprint (`evidence_id`, else a content `sha256`). If that fingerprint was already **accepted** for the capability, the application is recorded with decision `duplicate`, `state_changed: false`, and `duplicate_of: <prior intake_id>` — no confidence write. `_outcome()` now collects **all** recognised signals (`bundle.passed`, `bundle.status`, `trace.status`); agreement → that outcome, disagreement → outcome `conflict` → decision `quarantined` with `state_changed: false` and the detected `outcome_signals` preserved in the intake record. Accepted/failing/missing/no-identity/stale behaviour is unchanged. Confidence math in `CapabilityConfidenceEngine` is unchanged; readiness labelling stays an implementation-local projection of the score (not promotion doctrine; doctrine routed to Program 6). |
| **status** | implemented (Python; targeted + full pytest + ruff green) |
| **related_bug_id** | post-merge self-audit of PR #147 (duplicate inflation; silent priority resolution) |
| **related_test_case** | `tests/test_evidence_promotion.py` (duplicate / conflict / distinct-run accumulation + existing matrix) |
| **related_artifact_path** | `src/axiom_core/evidence_promotion.py`, `src/axiom_cli/main.py` (capability-evidence-apply renderer), `docs/architecture/integration/M2_Evidence_Promotion_Validation_Packet.md` |
| **notes** | No new promotion framework, doctrine, registry, object family, or durable state separate from `CapabilityConfidenceEngine`. Intake records remain audit artifacts only. EVID-001 remains closed only for the narrow M2 execution-chain slice; `model_health` producer gap stays open. |

## BHV-028: Windows artifact path containment compatibility fix (PR #151)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-028 |
| **date** | 2026-06-23 |
| **capability** | Artifact sandbox path containment (shared persistence helper across execution-chain, evidence-promotion, capability-confidence, and all `execution_*`/registry engines; not a Revit capability) |
| **observed_prompt** | `poetry run axiom execution-chain-run --capability self-model-build --artifacts-root <root> --json-output` (and `capability-evidence-apply`) run on Windows |
| **previous_behavior** | Every artifact-persisting engine validated sandbox containment with the POSIX-only check `str(target).startswith(str(sandbox) + "/")`. On Windows, `Path.resolve()` yields `\\` separators, so a valid `<sandbox>\\<uuid>` never matched the hard-coded `/` and was wrongly rejected with `Error: Resolved path escapes artifacts root: '<uuid>'`. This false-failed `execution-chain-run`, `capability-evidence-apply`, and the targeted execution-chain / evidence-promotion tests on Windows (38 failed / 77 passed / 1 skipped on the operator's Windows run), with both relative and absolute artifact roots. POSIX behaviour was correct. |
| **expected_behavior** | Sandbox containment must accept a valid id segment that resolves under the artifacts root on both Windows and POSIX, while still rejecting traversal (`../outside`, `..\\outside`), absolute/drive-root injection, UNC escapes, and separator-bearing ids. |
| **current_behavior** | A single shared helper `axiom_core.artifact_paths.is_within_sandbox(target, sandbox)` performs containment via `Path.relative_to()` (pathlib semantics: separator-aware and, on Windows, case-insensitive; no hard-coded `/` or `\\`; cross-drive inputs return `False` rather than raising). All 124 previous inline POSIX checks across 63 modules (`_safe_path` helpers and `list_*`/scan loops) now route through it. Id-segment validation (`_validate_id_segment` rejecting `..`, `/`, `\\`, empty) is unchanged. Confidence math, evidence-promotion semantics, and execution-chain ID-flow are unchanged. Local Runner was inspected and contains no such helper, so it is untouched. |
| **status** | implemented (Python; full pytest 5072 passed/1 skipped + ruff green on Ubuntu). Windows execution simulated via `PureWindowsPath` regression tests; true on-Windows re-run pending operator. |
| **related_bug_id** | Program 5 Windows Local Runner Compatibility Probe — `Resolved path escapes artifacts root` |
| **related_test_case** | `tests/test_artifact_paths.py` (Windows-simulated + POSIX + traversal/drive/UNC/sibling-prefix), plus existing `tests/test_execution_chain_orchestrator.py`, `tests/test_evidence_promotion.py` path-safety suites |
| **related_artifact_path** | `src/axiom_core/artifact_paths.py` (new helper); 63 `src/axiom_core/*.py` engines updated to call it; `tests/test_artifact_paths.py` |
| **notes** | Compatibility hardening only — no new framework or object family, no new runner, no retry/worker behavior, no canonical-seed work. Path-traversal protection preserved on both platforms. 2024 Revit baseline unaffected; no Revit live validation required. |

## BHV-029: CLI validation evidence recorder (PR #153)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-029 |
| **date** | 2026-06-28 |
| **capability** | CLI Validation Evidence Recorder (`axiom cli-validation-record`; validation-evidence infrastructure, not a Revit capability) |
| **observed_prompt** | `poetry run axiom cli-validation-record --plan docs/validation_plans/m4_execution_chain.json` (and the `m2_evidence_promotion.json` plan with `--set evidence=<path>`) |
| **previous_behavior** | No Axiom-native way to run an explicit, ordered sequence of allowlisted CLI commands and persist durable proof of the run. Validation proof relied on manual terminal copy/paste, Devin session context, or screenshots. `EvidenceRunner` (PR #25) only covers three fixed in-process validations (DiscoveryHarness / CommandRegistry / ValidationRegistry); it cannot run an arbitrary plan of CLI commands. |
| **expected_behavior** | Accept an explicit plan file, run each listed command under existing command-registry governance (safe, non-Revit only by default), capture inputs/outputs/exit/timing/env per command, and write a durable, machine- and human-readable evidence bundle. Failures must be first-class (recorded, outputs preserved, run marked failed, later commands skipped per policy). Must be Windows/POSIX path-safe and must not implement retry, a new runner, or promotion changes. |
| **current_behavior** | `axiom cli-validation-record --plan <path> [--artifacts-root <p>] [--name <run-name>] [--set KEY=VALUE] [--dry-run] [--json-output]` loads/validates a JSON `ValidationPlan`, authorizes each command via `command_registry` (`authorize_command`: cataloged + `SafetyLevel.SAFE` + not `requires_revit`, else `blocked`), executes via an injectable `CommandExecutor` (default `SubprocessCommandExecutor` runs `poetry run axiom <name> <args>` with an explicit argv — no shell), evaluates exit-code / stdout-contains / stderr-contains / artifact-exists assertions, and writes `artifacts/validation_evidence/<run_id>/` containing `validation_run.json`, `commands.json`, `environment.json`, `artifact_manifest.json` (sha256 per file), `assertion_results.json`, `plan_snapshot.json`, `report.md`, and per-command `commands/NN_<id>.stdout.txt`/`.stderr.txt`. A failed/blocked command with `continue_on_failure=false` stops the run and marks the rest `skipped`; run status is `passed` only if every command passed. Bundle directory and artifact-exists checks are validated with `artifact_paths.is_within_sandbox` (POSIX + Windows safe; traversal rejected). Process exit code is 0 on pass, 1 otherwise. |
| **status** | implemented (Python; targeted recorder + command-registry + execution-chain + evidence-promotion + local-runner tests + ruff green on Ubuntu; CLI smoke test produced M4 and M2 bundles). True on-Windows re-run pending operator. |
| **related_bug_id** | — |
| **related_test_case** | `tests/test_cli_validation_recorder.py` (plan parsing, governance, success/failure/timeout/blocked/skip, variable substitution, dry-run, path safety) |
| **related_artifact_path** | `src/axiom_core/validation/cli_validation_recorder.py` (new), `src/axiom_cli/main.py` (`cli-validation-record`), `src/axiom_core/runner/command_registry.py` (registry entry), `docs/validation_plans/` (M4/M2 plans + README) |
| **notes** | Validation-evidence infrastructure only — reuses command-registry governance and `is_within_sandbox` path safety; no new runner framework, no retry loop, no implementation-worker behavior, no GPR, no canonical doctrine, no confidence-math / evidence-promotion-semantic / execution-chain ID-flow changes, no Revit live validation. Complementary to `EvidenceRunner`, not a replacement. Generated bundles stay under git-ignored `artifacts/validation_evidence/`. |

## BHV-030: Model Health readiness evidence consumer (PR #156)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-030 |
| **date** | 2026-06-23 |
| **capability** | Model Health Readiness Evidence Consumer (`axiom model-health-evidence-apply`; evidence-consumer infrastructure, not a Revit capability) |
| **observed_prompt** | `poetry run axiom model-health-evidence-apply --readiness <run>/axiom_capability_readiness.json --json-output` |
| **previous_behavior** | The Model Health producer (`axiom_core.model_health.execute_health_run`) wrote `axiom_capability_readiness.json` but had only **read-only** consumers (`server_tools.axiom_capability_readiness_get` / `axiom_model_health_get_latest`) which return data and mutate no durable state. The readiness artifact was therefore orphaned — the open Model Health slice of EVID-001. |
| **expected_behavior** | The readiness artifact must have a state/evidence consumer that validates it, preserves provenance, de-duplicates, quarantines conflicts/stale, rejects malformed evidence, and records durable, queryable state — without inventing a readiness→confidence doctrine or mutating confidence math. |
| **current_behavior** | `ModelHealthReadinessConsumer.apply(readiness_path, max_age_seconds=None)` reads/validates `axiom_capability_readiness.json` (top-level `capabilities` list; per-entry non-empty `capability` and `readiness` in {READY,WARNING,BLOCKED,UNKNOWN}). Each capability entry is recorded as a durable intake under `artifacts/model_health_readiness_intake/<intake_id>/` (`report.json` + `pass_fail.json`) using the shared `is_within_sandbox` path safety and `_validate_id_segment`. Decisions: `accepted` (valid, first time — provenance preserved), `duplicate` (same capability+readiness+`generated_at_utc` fingerprint already accepted — not re-recorded), `quarantined` (conflicting labels for one capability within one artifact, or opt-in stale via `generated_at_utc`), `rejected` (unreadable/invalid JSON, missing `capabilities`, or per-entry missing/invalid fields). A single malformed entry is rejected without blocking valid siblings. `model-health-evidence-history` lists the intake log; `current_readiness(capability)` returns the latest accepted readiness state. Readiness is **not** mapped onto `CapabilityConfidenceEngine` factors — `confidence_mutated` is always `False`. |
| **status** | implemented (Python; targeted `test_model_health_evidence` + evidence-promotion + execution-chain + model-health + capability-confidence tests + ruff green on Ubuntu; CLI smoke test recorded accept/duplicate). |
| **related_bug_id** | EVID-001 (Model Health readiness slice) |
| **related_test_case** | `tests/test_model_health_evidence.py` (valid / missing / invalid-JSON / missing-fields / invalid-label / duplicate / distinct-run / conflict / stale / provenance / confidence-untouched / read-only / CLI) |
| **related_artifact_path** | `src/axiom_core/model_health_evidence.py` (new), `src/axiom_cli/main.py` (`model-health-evidence-apply`, `model-health-evidence-history`) |
| **notes** | Adapter/coordinator only — no new evidence framework, no new registry, no readiness/promotion doctrine, no confidence-math change, no implementation-worker / retry / GPR / Revit behavior. Closes EVID-001 **only** for the Model Health readiness evidence slice implemented here; broader EVID-001 remains open. Whether readiness should influence confidence is an open Program 6 doctrine question, intentionally left open. Intake records stay under git-ignored `artifacts/`. |

## BHV-031: Context Preflight and Live System Map (PR #157)

| Field | Value |
|-------|-------|
| **behavior_id** | BHV-031 |
| **date** | 2026-06-29 |
| **capability** | Context Preflight (`axiom context-preflight`; live repo-derived system map, not a Revit capability) |
| **observed_prompt** | `poetry run axiom context-preflight --artifacts-root <path> [--json-output]` |
| **previous_behavior** | No live context-loading mechanism existed. Program 1, Devin, and other programs reasoned from partial chat memory, stale summaries, or the most recent PR only. No single command could report what Axiom knows about itself, what evidence exists, what remains unknown, or what existing components must be checked before adding anything new. |
| **expected_behavior** | A bounded context preflight that inspects the current repo and reports: git state, canonical context, integration docs, CLI/command map, evidence topology, runner/execution substrate, known caveats, overlap guardrails, and a reusable Context Basis template — without mutating canonical docs, without creating a new knowledge framework, and without committing generated artifacts. |
| **current_behavior** | `context_preflight.run_preflight(repo_root, artifacts_root)` inspects the repo and emits a 9-section preflight report plus a System Atlas (25 component families, incl. earlier-introduced foundational pipe/spine/bridge/MCP/agents components) as both JSON and Markdown under gitignored `artifacts/context_preflight/<run_id>/`. Reuses existing `CodebaseInventory` (CLI command AST scan) and `command_registry.command_names()` for command discovery. Missing optional docs are reported as `unknown`, never as errors. Known caveats include EVID-001 partially closed, GPR unimplemented, Windows revalidation pending, confidence math untouched by Model Health, Program 3/4 out of scope. Overlap guardrails list 6 areas with existing components that must be checked before adding new systems. Context Basis template provides a pasteable section for future PR bodies. Additionally creates 3 tracked reference docs: PR Purpose Map (PRs #143–#156 + earlier-introduced foundational component table), Duplicate/Alias Map (12 concept clusters incl. Revit-execution-boundary, execution-record, and coordinator clusters), and Current Context Pack (index). |
| **status** | implemented (Python; targeted `test_context_preflight` 33 passed; ruff clean; CLI smoke tested on real repo). |
| **related_bug_id** | (none — new capability, not a bug fix) |
| **related_test_case** | `tests/test_context_preflight.py` (canonical present/missing/partial, integration present/unknown, evidence topology, runner substrate, known caveats, overlap guardrails, full run artifacts, canonical-not-mutated, 9-section completeness, context basis, markdown rendering, system atlas families/files/markdown/references, atlas in preflight run) |
| **related_artifact_path** | `src/axiom_core/context_preflight.py` (extended), `src/axiom_cli/main.py` (`context-preflight` command), `docs/architecture/integration/PR_Purpose_Map_v0.md` (new), `docs/architecture/integration/Duplicate_Alias_Map_v0.md` (new), `docs/architecture/integration/Axiom_Current_Context_Pack.md` (new), `docs/architecture/integration/PR157_Design_Pass.md` (new) |
| **notes** | Read-only inspector only — no new knowledge framework, no new evidence system, no canonical mutation, no committed generated artifacts, no implementation-worker / retry / GPR / Revit behavior. Not canonical truth by itself; it is a context preflight / live system map consumed by Program 1, Devin, and future PR preflight. System Atlas component families are hardcoded from the PR #157 design pass + foundational provenance scan; file presence is checked live. Tracked docs are committed; generated artifacts are gitignored. The required foundational provenance scan reconciled earlier-introduced pipe/spine/bridge/job-plan/MCP/agents concepts: results recorded in the Duplicate/Alias Map (Clusters 10–12 + "Foundational provenance scan result" section) and the PR Purpose Map earlier-introduced foundational component table. Mapping only — no pipe/spine/bridge/orchestrator/runtime behavior changed. |
