# Implementation Plan Generator v1

## Purpose

Generates structured implementation plans from approved work items.
Bridges the gap between backlog knowledge and code-change planning.
Read-only: never modifies files, never executes code, never creates PRs.

## Components

| Component | Role |
|-----------|------|
| `ImplementationPlanner` | Planning engine — consumes registries, produces plans |
| `ImplementationPlan` | Top-level plan with steps, file changes, test plan, risks |
| `ImplementationStep` | Ordered step with target files and verification |
| `FileChangeIntent` | Proposed change: file path, change type, related symbols |
| `TestPlan` | Existing test files to run + new tests needed |
| `RiskNote` | Risk with severity and mitigation |

## Inputs

| Registry | Usage |
|----------|-------|
| `WorkItemRegistry` | Source work item (must be approved or in_progress) |
| `CodeSymbolRegistry` | Target file discovery, symbol matching, test coverage |
| `KnowledgeGraph` (optional) | Related knowledge node discovery |

## Enums

| Enum | Values |
|------|--------|
| `ChangeType` | add, modify, delete |
| `RiskLevel` | low, medium, high |
| `PlanStatus` | draft, ready, superseded |

## CLI

```bash
axiom implementation-plan --work-item <id>
axiom implementation-plan --work-item <id> --json-output
```

## Persistence

Plans persist in SQLite (`implementation_plans` table). Regenerating a plan
for the same work item supersedes the previous plan.

## Non-Goals

- No code editing
- No PR creation
- No autonomous execution
- No external API calls
