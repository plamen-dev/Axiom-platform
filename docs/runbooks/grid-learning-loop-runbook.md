# Grid Test Harness / Learning Loop Runbook

## Overview

The grid test harness is a deterministic testing loop for the `CreateGrids` capability. It runs a suite of test cases through the prompt resolver and execution pipeline, logs structured results, and enables regression tracking across code changes.

## Quick Start

```bash
# Run all simulation test cases
python -m poetry run axiom test-grids --mode simulate

# Run with Revit connected (requires AxiomPipeServer running)
python -m poetry run axiom test-grids --mode real

# Run with a custom run ID for traceability
python -m poetry run axiom test-grids --mode simulate --run-id sprint_42_baseline
```

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mode` | `simulate` | `simulate` (no Revit) or `real` (requires Revit pipe) |
| `--case-file` | built-in suite | Path to a custom YAML test case file |
| `--limit` | all | Maximum number of test cases to run |
| `--run-id` | auto-timestamp | Custom identifier for the run |
| `--output-dir` | `artifacts/grid_test_runs/` | Base directory for output files |
| `--fail-fast` | off | Stop on first test failure |

## Test Case Categories

The built-in suite at `tests/fixtures/grid_test_cases/create_grids.yaml` covers:

| Category | Count | Examples |
|----------|-------|---------|
| Vertical-only uniform | 2 | 10 vertical grids, 3 vertical grids |
| Horizontal-only uniform | 2 | 5 horizontal grids, 4 rows |
| Both orientations uniform | 3 | 5x5 grid, 4x6 grid, columns+rows |
| Variable vertical (comma) | 2 | `spacings 10, 5, 20, 10` |
| Variable horizontal (comma) | 1 | `spacings 12, 18, 12` |
| Variable both (table) | 2 | Table with Vertical:/Horizontal: sections |
| Pasted table (unsectioned) | 1 | `1-2 = 10'` entries without section headers |
| Missing parameters | 1 | Length not specified |
| Invalid spacing | 1 | Negative values in comma list |
| Mismatched count/spacing | 1 | Count says 3 but 4 spacings given |
| Unsupported prompts | 2 | Diffuser placement, level creation |
| Edge cases (count 0/1) | 3 | Single gridline, zero count |
| Keyword discovery | 2 | `rows`/`columns` without `grid` keyword |
| Stress / misc | 3 | 50 grids, word numbers, decimal spacing |
| Duplicate run | 1 | Same prompt run twice |
| Real execution | 2 | Require Revit (skipped if pipe unavailable) |

## Output Files

Each run produces three files in `artifacts/grid_test_runs/<run_id>/`:

| File | Format | Purpose |
|------|--------|---------|
| `results.jsonl` | JSON Lines | Raw append-only event log |
| `results.parquet` | Apache Parquet | Structured dataset for analysis |
| `summary.md` | Markdown | Human-readable report with pass/fail/regression |

Results are also persisted to SQLite (`~/.axiom/axiom.db`, `prompt_executions` table) with `mode=test_simulate` or `mode=test_real`.

## Test Case Format

Each test case in the YAML file has these fields:

```yaml
- test_id: vert_uniform_10
  prompt: "Create 10 vertical gridlines, 50 ft long, spaced 10 ft apart"
  expected_capability: CreateGrids
  expected_parameters:
    HorizontalCount: 10
    VerticalCount: 0
    SpacingFeet: 10.0
    Length: 50.0
  expected_created_count: 10
  expected_success: true
  mode: simulate
  notes: "Baseline vertical-only prompt"
```

For expected failures:

```yaml
- test_id: unsupported_prompt
  prompt: "Place diffusers in every room on level 2"
  expected_capability: null
  expected_parameters: {}
  expected_created_count: 0
  expected_success: false
  expected_failure_reason: "Prompt does not match any known capability"
  mode: simulate
```

## Regression Workflow

1. **Establish baseline**: Run the harness and note the run ID
2. **Make code changes**: Fix a bug or add a feature
3. **Re-run the harness**: The report automatically compares against the most recent previous run
4. **Check the summary**: Look for newly passing, newly failing, and count changes

```bash
# Baseline
python -m poetry run axiom test-grids --mode simulate --run-id before_fix

# After code changes
python -m poetry run axiom test-grids --mode simulate --run-id after_fix

# Check regression report
cat artifacts/grid_test_runs/after_fix/summary.md
```

## Adding New Test Cases

1. Edit `tests/fixtures/grid_test_cases/create_grids.yaml`
2. Add a new entry under `test_cases:` with the required fields
3. Run `--limit 1` to test just your new case first
4. Use `--case-file` to point to a custom YAML file during development

## Known Bugs (Discovered by Harness)

These bugs are documented in the test fixture file as `BUG-DISCOVERY` notes:

1. **`rows`/`columns` without `grid` keyword**: Prompts like "Create 4 rows spaced 15 ft apart" are not recognized because `_is_grid_prompt()` requires the word "grid". Future fix: add "rows"/"columns" as grid-prompt triggers.

2. **Mock execution allows count=0**: `_mock_execute()` returns SUCCESS with 0 created when both counts are 0. The C# `GridCapability` validates this properly, but the mock does not. Future fix: add count validation to mock.

## Parquet Schema

For programmatic analysis of test results:

| Column | Type | Description |
|--------|------|-------------|
| test_id | string | Unique test case identifier |
| prompt | string | Input prompt text |
| mode | string | "simulate" or "real" |
| git_commit | string | Short commit hash at run time |
| git_branch | string | Branch name at run time |
| timestamp | string | ISO timestamp |
| resolved_capability | string | Resolved capability name |
| resolved_parameters | string (JSON) | Resolved parameter dict |
| assumptions | string (JSON) | Assumptions list |
| pipe_available | bool | Whether Revit pipe was available |
| status | string | SUCCESS / FAILED / UNRESOLVED / SKIPPED |
| created_count | int32 | Number of elements created |
| created_ids | string (JSON) | List of created element IDs |
| warnings | string (JSON) | Warning messages |
| errors | string (JSON) | Error messages |
| duration_ms | int32 | Execution time |
| expected_success | bool | Whether success was expected |
| expected_created_count | int32 | Expected created count |
| passed | bool | Whether test passed its expectations |
| failure_category | string | Category of failure if any |
| failure_detail | string | Detailed failure description |
| notes | string | Test case notes |
