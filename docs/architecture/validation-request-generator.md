# Plan-to-Validation Request Generator v1

## Purpose

Transforms approved capability plans into structured validation requests.
This is the bridge between **plan governance** (PR #51) and **validation execution** (future).

## Chain Position

```
Knowledge → Plan (PR #45) → Plan Review (PR #51) → Validation Request (PR #52)
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                ValidationRequestGenerator                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Inputs:                                                │
│    • Approved Plan Reviews (PR #51)                     │
│    • Validation Registry                                │
│    • Capability State                                   │
│    • Command Registry                                   │
│    • Failure Classification                             │
│    • Promotion Decisions                                │
│                                                         │
│  Outputs:                                               │
│    • ValidationRequest                                  │
│      ├── plan_id                                        │
│      ├── required_capabilities                          │
│      ├── steps (validation procedures)                  │
│      ├── dependencies                                   │
│      ├── evidence (required evidence)                   │
│      ├── blockers                                       │
│      ├── prerequisites                                  │
│      ├── known_risks                                    │
│      └── expected_outputs                               │
│                                                         │
│  Persistence: SQLite (validation_requests table)        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Models

| Model | Purpose |
|-------|---------|
| `ValidationRequest` | Top-level request generated from an approved plan |
| `ValidationRequestStep` | Individual validation procedure within a request |
| `ValidationRequestDependency` | Ordering constraint between steps |
| `ValidationRequestEvidence` | Evidence requirement specification |
| `ValidationRequestBlocker` | Condition preventing validation |
| `ValidationRequestGenerator` | Stateful generator with SQLite persistence |

## Enums

| Enum | Values |
|------|--------|
| `ValidationRequestStatus` | pending, ready, blocked, completed, cancelled |
| `BlockerType` | missing_capability, missing_evidence, unsafe_procedure, prerequisite_failed, dependency_unmet, policy_violation |

## CLI Commands

```bash
# Generate a validation request from an approved plan
axiom validation-request-create --plan-id <id> [--json-output]

# Show details for a specific request
axiom validation-request --id <id> [--json-output]

# List all validation requests
axiom validation-requests [--status <status>] [--plan-id <id>] [--json-output]
```

## Rules

1. Only approved plans may generate validation requests
2. Rejected plans are refused with a clear error
3. Unknown plan IDs fail with exit code 2
4. Blockers set request status to `blocked`
5. Requests without blockers are `ready`
6. No execution occurs — requests are work descriptions only

## Non-Goals

- No execution
- No retries
- No promotion
- No learning

## Strategic Purpose

PR #45 creates plans.
PR #51 decides which plans are trusted.
PR #52 transforms trusted plans into validation work — without executing anything.
