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
