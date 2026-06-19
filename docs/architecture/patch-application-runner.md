# Patch Application Runner v1

## Purpose

Controlled mechanism for applying approved patch proposals. The final step
in the governed change chain:

```
Work Item -> Implementation Plan -> Patch Proposal -> Patch Review -> Patch Application
```

## Components

| Component | Role |
|-----------|------|
| `PatchApplicationRunner` | Engine: validates approval, executes steps, writes evidence |
| `PatchApplicationRun` | Complete run record with steps, evidence, and result |
| `PatchApplicationStep` | Single file-change step with status and rollback info |
| `PatchApplicationEvidence` | Evidence artifact reference |
| `PatchApplicationResult` | Aggregate result with step counts |
| `PatchRollbackInfo` | Original file backup and existence metadata |

## Safety Gates

The runner refuses proposals that are:
- **Unknown** — proposal ID not found
- **Proposed** — not yet reviewed
- **Rejected** — explicitly rejected
- **Superseded** — replaced by newer version
- **Applied** — already applied (no double-application)

Only `approved` proposals may be applied.

## Modes

| Mode | Behavior |
|------|----------|
| `apply` | Writes file changes, marks proposal as APPLIED |
| `simulate` | Runs all steps without writing files, preserves APPROVED status |

## Evidence Artifacts

Every run writes to `artifacts/patch_runs/<run_id>/`:

| File | Content |
|------|---------|
| `patch_request.json` | Input: proposal ID, plan ID, simulate flag |
| `patch_result.json` | Full run record with all steps and result |
| `patch_summary.md` | Human-readable summary |
| `pass_fail.json` | Machine-readable pass/fail verdict |
| `applied_changes/` | Copies of files as written |
| `rollback_info/` | Backups of original files |

Evidence is always written, even on failure or simulate.

## Command Registry

| Command | Classification | Safety |
|---------|---------------|--------|
| `patch-apply` | MUTATION | HIGH_RISK |

First MUTATION command in Axiom. Requires explicit proposal approval.

## CLI

```bash
axiom patch-apply --proposal-id <id>                # apply
axiom patch-apply --proposal-id <id> --simulate     # dry-run
axiom patch-apply --proposal-id <id> --json         # machine output
```

## Constraints

- No git operations
- No PR creation
- No autonomous approval
- No learning or self-modification of the runner itself
- Deterministic step ordering (follows proposal file_changes order)
- Rollback metadata captured for every step

## Dependencies

- `PatchProposalRegistry` (PR #59) — proposal lookup and status sync
- `PatchReviewRegistry` (PR #60) — approval validation (indirect via proposal status)
- `CodebaseInventory` (PR #57) — file existence awareness
- `WorkItemRegistry` (PR #56) — backlog linkage via plan_id
