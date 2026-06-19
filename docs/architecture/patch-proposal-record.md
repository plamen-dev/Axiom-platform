# Patch Proposal Record v1

## Purpose

Durable record format for proposed code changes before they are applied.
Describes patches, evidence, tests, and risks without editing files.
Read-only: never modifies source files, never runs git operations.

## Components

| Component | Role |
|-----------|------|
| `PatchProposalRegistry` | Creates and manages proposals from implementation plans |
| `PatchProposal` | Top-level proposal with file changes, tests, risks |
| `ProposedFileChange` | Intended edit: file path, edit type, before/after hints |
| `ProposedTestCommand` | Test or validation command with expected exit code |
| `PatchRisk` | Risk with severity, mitigation, affected area |
| `PatchEvidenceRequirement` | Evidence that must be produced when applying |

## Inputs

| Source | Usage |
|--------|-------|
| `ImplementationPlanner.get_plan()` | Source plan for deriving file changes, tests, risks |

## Enums

| Enum | Values |
|------|--------|
| `PatchStatus` | proposed, approved, rejected, applied, superseded |
| `PatchRiskLevel` | low, medium, high, critical |
| `FileEditType` | add, modify, delete, rename |

## CLI

```bash
axiom patch-proposal-create --plan-id <id> [--json-output]
axiom patch-proposals [--status <status>] [--json-output]
axiom patch-proposal --id <id> [--json-output]
```

## Persistence

Proposals persist in SQLite (`patch_proposals` table). Regenerating a proposal
for the same plan supersedes the previous proposal.

## Non-Goals

- No patch application
- No code generation
- No PR creation
- No git operations
