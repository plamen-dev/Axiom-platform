# PR Draft Generator v1

## Position in Chain

```
Work Item → Implementation Plan → Patch Proposal → Patch Review
→ Patch Application → Code Validation → PR Draft (this module)
```

## Purpose

Converts code validation evidence and work item context into merge-ready
release artifacts without touching GitHub API, creating PRs, or performing
any network/Git operations.

## Components

| Component | Role |
|-----------|------|
| `PRDraftGenerator` | Main orchestrator — consumes upstream artifacts |
| `PRDraft` | Complete draft record with all sections |
| `PRSummary` | Commit title + extended description + metrics |
| `PRValidationSection` | Structured validation evidence |
| `PRStrategicSection` | Significance, next step, non-goals, what didn't change |

## Inputs

- **WorkItemRegistry** — title, type, description for commit message
- **PatchProposalRegistry** — risk level, rollback notes, risks
- **Patch Application runs** — files changed, steps applied
- **Code Validation runs** — pass/fail, stages, evidence paths
- **Evidence bundles** — artifact paths for traceability

## Evidence Outputs

Written to `artifacts/pr_drafts/<draft_id>/`:

| File | Purpose |
|------|---------|
| `pr_request.json` | Request metadata |
| `pr_result.json` | Full draft serialization |
| `pr_summary.md` | Human-readable summary |
| `pass_fail.json` | Machine-readable verdict |

## CLI

```bash
axiom pr-draft --work-item <id>                    # From work item
axiom pr-draft --validation-run-id <id>            # From validation run
axiom pr-draft --validation-run-id <id> --json-output  # JSON output
axiom pr-drafts [--json-output]                    # List all drafts
axiom pr-draft-show --draft-id <id> [--json-output]    # Show specific draft
```

## Security

- No GitHub API
- No PR creation
- No merge behavior
- No network dependency
- No Git operations
- Path traversal validation on all IDs

## Non-Goals

- No review finding ingestion
- No automatic fixes
- No PR opening
- No learning
- No autonomous merge

## Strategic Significance

PR #61 applies changes. PR #62 validates them. PR #63 converts evidence
into merge-ready release artifacts. This internalizes release engineering
and prepares the system for review-finding ingestion in PR #64.
