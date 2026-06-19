# Test Selection Engine v1

## Position in Chain

Supports the validation layer by selecting which tests to run before executing them.

## Purpose

Deterministic selection of targeted tests based on changed files, work items, implementation plans, or patch proposals. Reduces unnecessary validation cost while preserving full-suite safety rules.

## Components

- **TestSelectionEngine**: Core engine that maps changes to tests.
- **TestSelectionRequest**: Input specifying changed files or context IDs.
- **SelectedTestPlan**: Output with strategy, selected tests, and ruff targets.
- **SelectedTest**: A single test selected with reason and priority.
- **TestSelectionReason**: Why a test was selected (direct_mapping, module_match, high_risk_area, full_suite_fallback, ruff_always).

## Selection Strategy

1. If `force_full_suite`, run everything.
2. Gather changed files from request + work item + plan + proposal.
3. If no changed files, fall back to full suite.
4. If any high-risk file changed (database, models, persistence, runner, schemas), full suite.
5. Map files to tests via direct mapping, module prefix, or convention (`test_<stem>.py`).
6. Always include ruff for Python changes.

## High-Risk Areas (full suite required)

- `database.py`, `models.py`, `persistence.py`, `run_spine.py`, `schemas.py`
- `runner/command_registry.py`, `runner/capability_runner.py`
- Any file containing `/runner/` or `/agents/`

## CLI Surface

- `axiom test-selection [--changed-files] [--work-item] [--plan-id] [--proposal-id] [--full-suite] [--json-output]`
- `axiom test-selection-files <files...> [--json-output]`

## Evidence Output

Written to `artifacts/test_selection/<plan_id>/`:
- `selection_request.json`
- `selection_result.json`
- `selection_summary.md`
- `pass_fail.json`

## Non-Goals

- No test execution.
- No code modification.
- No patch application.
- No PR creation.
- No autonomous behavior.
