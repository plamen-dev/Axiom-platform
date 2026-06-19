# Patch Impact Analyzer v1

Deterministic impact analysis for proposed changes before patch application.

## Position in Chain

```
Work Item -> Implementation Plan -> Patch Proposal -> Patch Impact Analysis
-> Test Selection -> Validation -> PR Draft
```

## What It Does

- Analyzes patch proposals or file lists to identify affected components
- Detects affected symbols, CLI commands, registries, tests, docs, and evidence contracts
- Flags high-risk areas: evidence, persistence, runner, mutation, Revit bridge, governance, security
- Computes overall impact level and full-suite test requirement
- Writes evidence bundles for each analysis run

## What It Does Not Do

- Does not apply patches
- Does not modify code
- Does not execute tests
- Does not create PRs
- No autonomous behavior

## High-Risk Areas

| Area | Impact | Triggered By |
|------|--------|-------------|
| mutation | critical | patch_application.py |
| security | critical | security-related paths |
| persistence | high | database.py, models.py, persistence.py |
| runner | high | runner/ directory |
| governance | high | run_spine.py, mcp_layer.py |
| revit_bridge | high | automation_bridge.py |
| evidence | high | artifacts/ directory |
| cli | medium | main.py, command_registry.py |

## CLI

```bash
axiom impact-analyze --proposal-id <id> [--json-output]
axiom impact-analyze --files <file1> --files <file2> [--json-output]
axiom impact-analyze-files <file1> <file2> ... [--json-output]
```

## Evidence

```
artifacts/impact_analysis/<run_id>/
  impact_request.json
  impact_result.json
  impact_summary.md
  pass_fail.json
```

## Data Model

- `ImpactScope` — complete impact scope with all affected components
- `AffectedSymbol` — function/class affected by change
- `AffectedCommand` — CLI command affected
- `AffectedTest` — test file likely affected
- `AffectedDoc` — documentation file affected
- `AffectedEvidence` — evidence contract affected
- `HighRiskFlag` — high-risk area flagged for scrutiny

## Security

- Path traversal validation on all IDs
- No network dependency
- No GitHub API
- No code modification
