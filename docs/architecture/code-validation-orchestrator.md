# Code Validation Orchestrator v1

## Purpose

Validates patch application results through governed stages. The validation
layer after patch application in the governed change chain:

```
Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
-> Patch Application -> Code Validation (this module)
```

## Components

| Component | Role |
|-----------|------|
| `CodeValidationOrchestrator` | Engine: loads patch run, builds stages, executes, writes evidence |
| `CodeValidationRun` | Complete run record with stages, evidence, and summary |
| `CodeValidationStage` | Single validation stage with command, result, and status |
| `CodeValidationStageResult` | Stdout/stderr/exit code/duration from stage execution |
| `CodeValidationEvidence` | Evidence artifact reference |
| `CodeValidationSummary` | Aggregate result counts and overall pass/fail |

## Safety Gates

The orchestrator refuses:
- **Unknown patch runs** — no `patch_result.json` found
- **Failed patch runs** — status not `completed` or `simulated`
- **Unsuccessful patch runs** — `result.success` is false
- **Non-allowlisted commands** — only `poetry run pytest` and `poetry run ruff` permitted
- **Workspace escape** — commands execute within workspace root only

## Stages

Executed in deterministic order:

| Stage | Kind | Required | Implementation |
|-------|------|----------|----------------|
| Targeted tests | `targeted_tests` | Yes | `poetry run pytest <test_files> -x -q` |
| Full pytest | `full_pytest` | Yes | `poetry run pytest -x -q` |
| Ruff | `ruff` | Yes | `poetry run ruff check <src_files>` |
| CLI walkthrough | `cli_walkthrough` | No | Placeholder (skipped) |
| Artifact inspection | `artifact_inspection` | No | Placeholder (skipped) |

## Stage Statuses

| Status | Meaning |
|--------|---------|
| `passed` | Command exited 0 |
| `failed` | Command exited non-zero |
| `skipped` | Placeholder or no command |
| `simulated` | Simulate mode — not executed |
| `refused` | Command not in allowlist |
| `blocked` | Prerequisite not met |

## Overall Result

- **PASSED** if no required stages failed
- **FAILED** if any required stage failed
- **SIMULATED** if simulate mode was used

## Evidence Artifacts

Every run writes to `artifacts/code_validation_runs/<run_id>/`:

| File | Content |
|------|---------|
| `validation_request.json` | Input metadata |
| `validation_result.json` | Full run record |
| `validation_summary.md` | Human-readable summary |
| `pass_fail.json` | Machine-readable verdict |
| `test_outputs/` | Stdout/stderr from pytest stages |
| `ruff_output/` | Stdout/stderr from ruff stages |
| `walkthroughs/` | CLI walkthrough evidence (future) |

Evidence is always written, even on failure or simulate.

## Command Registry

| Command | Classification | Safety |
|---------|---------------|--------|
| `code-validate` | READ_ONLY | SAFE |
| `code-validation-runs` | READ_ONLY | SAFE |
| `code-validation-run` | READ_ONLY | SAFE |

## CLI

```bash
axiom code-validate --patch-run-id <id>                # validate
axiom code-validate --patch-run-id <id> --simulate     # dry-run
axiom code-validate --patch-run-id <id> --json-output  # machine output
axiom code-validation-runs [--json-output]             # list runs
axiom code-validation-run --run-id <id> [--json-output]  # show run
```

## Constraints

- Allowlisted commands only (no arbitrary execution)
- Repo-root boundary enforcement
- No git operations
- No network dependency
- No review ingestion
- No automatic fixes
- No PR generation
- No learning
- No autonomous merge
- Deterministic stage ordering

## Dependencies

- `PatchApplicationRunner` (PR #61) — consumes patch run evidence
