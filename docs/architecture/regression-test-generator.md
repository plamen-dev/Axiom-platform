# Regression Test Generator v1

Structured regression-test recommendations from bugs, review findings,
policy violations, and failure classifications.

## Position in Chain

```
Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
-> Patch Application -> Code Validation -> PR Draft -> Review Findings
-> Self-Improvement Loop -> Test Selection Engine -> Regression Test Generator
```

## What It Does

- Analyzes review findings to detect bug classes
- Maps bug classes to test intents (what the recommended test should assert)
- Generates regression test candidates with assertion hints
- Detects recurring bug patterns (2+ occurrences)
- Links recommendations to review findings, work items, and failure classifications
- Writes evidence bundles for each generation run

## What It Does Not Do

- Does not modify test files
- Does not generate code
- Does not apply patches
- Does not create PRs
- Does not execute tests
- No autonomous behavior

## Bug Classes

| Bug Class | Test Intent | Priority |
|-----------|-------------|----------|
| truthiness_bug | assert_falsy_rejected | medium |
| enum_serialization | assert_enum_round_trip | medium |
| persistence_defect | assert_persisted_correctly | high |
| evidence_failure | assert_evidence_written | medium |
| cli_exit_code | assert_exit_code | medium |
| refusal_path | assert_refusal | medium |
| malformed_input | assert_validation_error | medium |
| path_traversal | assert_path_rejected | high |
| command_injection | assert_injection_rejected | high |
| silent_exception | assert_exception_logged | medium |
| stage_ordering | assert_ordering_stable | low |
| duplicated_logic | assert_no_duplication | low |

## Failure Origins

- review_finding
- runtime_failure
- policy_violation
- human_review
- external_review
- security

## CLI

```bash
axiom regression-test-generate [--json-output]
axiom regression-test-create --title <t> --failure-origin <origin> [--bug-class <c>] [--json-output]
axiom regression-test-candidates [--bug-class <c>] [--status <s>] [--priority <p>] [--json-output]
axiom regression-test-candidate --id <id> [--json-output]
axiom regression-test-update --id <id> --status <s> [--json-output]
axiom regression-test-patterns [--json-output]
```

## Evidence

```
artifacts/regression_tests/<run_id>/
  regression_request.json
  regression_result.json
  regression_summary.md
  pass_fail.json
```

## Data Model

- `RegressionTestCandidate` — proposed test with bug class, intent, priority, and assertion hint
- `BugPattern` — recurring bug class across findings (2+ occurrences)
- `TestIntent` — describes what the recommended test should assert
- `RegressionTestCandidateRow` — SQLAlchemy persistence
- `BugPatternRow` — SQLAlchemy persistence

## Security

- Path traversal validation on all IDs
- No network dependency
- No GitHub API
- No code modification
