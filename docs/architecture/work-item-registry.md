# Autonomous Work Item Registry v1

## Purpose

Durable internal backlog for implementation work items that Axiom can
reason about before code is written. Replaces ephemeral chat messages
and session prompts with persistent, queryable records.

## Components

| Component | Role |
|-----------|------|
| `WorkItemRegistry` | CRUD + dependency tracking + history |
| `WorkItem` | Data model with lifecycle state |
| `WorkItemType` | Classification (bug_fix, feature, cleanup, test, documentation, refactor, validation, investigation, review_finding) |
| `WorkItemStatus` | Lifecycle (proposed, approved, in_progress, blocked, completed, rejected, deferred) |
| `WorkItemPriority` | Urgency (critical, high, medium, low, unset) |
| `WorkItemEvidence` | Evidence attached to work items |
| `WorkItemDependency` | Dependency relationships between items |

## CLI

```bash
axiom work-items [--status <s>] [--type <t>] [--json-output]
axiom work-item --id <id> [--json-output]
axiom work-item-create --title "..." --type bug_fix [--priority high] [--json-output]
axiom work-item-update --id <id> [--status approved] [--priority critical] [--json-output]
```

## Persistence

SQLite via SQLAlchemy, same database layer as all other Axiom registries.
Three tables: `work_items`, `work_item_history`, `work_item_dependencies`.

## Non-Goals

- No code generation.
- No execution.
- No GitHub API integration.
- No autonomous coding.

## Strategic Context

This is the internal backlog layer. Combined with the Promotion Eligibility
Engine (PR #30) and the Controlled Discovery Loop (PR #55), Axiom can now
track what needs to be done, not just what has been done.
