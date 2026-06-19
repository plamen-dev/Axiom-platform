# Self-Improvement Loop v1

## Position in Chain

```
Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
  -> Patch Application -> Code Validation -> PR Draft -> Review Findings
  -> Self-Improvement Loop (this module)
```

## Purpose

The first loop where Axiom studies its own engineering history. Consumes review findings and generates improvement candidates without automatic modification.

## Components

- **SelfImprovementLoop**: Orchestrates analysis, pattern detection, and candidate generation.
- **ImprovementCandidate**: Proposed improvement with category, priority, evidence, and recommendation.
- **ImprovementPattern**: Detected recurring pattern across review findings.
- **ImprovementEvidence**: Supporting evidence for a candidate.
- **ImprovementPriority**: Priority ranking (critical, high, medium, low, unset).
- **ImprovementCategory**: Classification (repeated_bug_class, missing_test, duplicated_pattern, candidate_helper, knowledge_update, skill_update, playbook_update).

## Analysis Flow

1. Gather all review findings from ReviewFindingRegistry.
2. Group findings by detected pattern kind.
3. Generate improvement candidates from repeated patterns.
4. Detect missing test coverage from bug/security findings.
5. Generate knowledge/skill/playbook update recommendations.
6. Persist all patterns and candidates to SQLite.
7. Write evidence bundle.

## CLI Surface

- `axiom self-improvement [--json-output]` - Run analysis loop.
- `axiom improvement-candidates [--category] [--priority] [--status] [--json-output]` - List candidates.
- `axiom improvement-candidate --id <id> [--json-output]` - Show candidate detail.
- `axiom improvement-patterns [--json-output]` - List detected patterns.

## Evidence Output

Written to `artifacts/self_improvement/<run_id>/`:
- `improvement_request.json`
- `improvement_result.json`
- `improvement_summary.md`
- `pass_fail.json`

## Non-Goals

- No automatic code changes.
- No autonomous patch application.
- No autonomous approval.
- No self-modification.
- No GitHub API, no network dependency.

## Strategic Significance

PR #65 is where Axiom begins to study and improve the process of building Axiom itself. This is the first step toward a genuine software engineering organization rather than a collection of tools.
