# Patch Review and Approval Queue v1

## Purpose

Human review and approval for patch proposals. The approval gate before
Axiom begins applying patches. Keeps the system safe while moving toward
autonomous programming.

## Components

| Component | Role |
|---|---|
| `PatchReviewRegistry` | Creates, persists, and queries reviews |
| `PatchReview` | A single review decision with evidence |
| `PatchReviewEvidence` | Evidence attached to a review |
| `PatchReviewHistoryEntry` | Immutable history record of each decision |
| `ReviewDecision` | Enum: proposed, approved, rejected, needs_more_evidence, superseded, deprecated |

## Data Flow

```
PatchProposal (PR #59)
        |
        v
  patch-review-create --proposal-id <id> --decision approved
        |
        v
  PatchReviewRegistry.create_review()
        |
        +---> PatchReviewRow (persisted)
        +---> PatchReviewHistoryRow (immutable audit)
        +---> _sync_proposal_status() -> PatchProposalRegistry.update_status()
```

## Review Decisions

| Decision | Proposal Sync | Meaning |
|---|---|---|
| proposed | (none) | Initial state |
| approved | APPROVED | Patch may proceed to application |
| rejected | REJECTED | Patch blocked |
| needs_more_evidence | (none) | Reviewer requests additional validation |
| superseded | (none) | Replaced by newer review |
| deprecated | SUPERSEDED | Proposal no longer relevant |

## CLI

```bash
axiom patch-review-create --proposal-id <id> --decision approved --reason human_validation
axiom patch-reviews [--proposal-id <id>] [--decision <filter>] [--json-output]
axiom patch-review --proposal-id <id> [--json-output]
```

## Constraints

- Read-only: never edits files, never runs git, never applies patches
- Unknown proposal IDs fail with ValueError
- Duplicate reviews preserve full history (chronological)
- JSON output valid on all commands
