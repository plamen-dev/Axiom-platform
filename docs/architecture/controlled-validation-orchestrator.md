# Controlled Validation Orchestrator v1

## Purpose

Execute approved validation requests using existing safe validation infrastructure.
Only safe/read-only validations are allowed — mutations are refused.

## Chain Position

```
Knowledge → Plan → Plan Review → Validation Request → Validation Execution (PR #53)
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│           ControlledValidationOrchestrator               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Inputs:                                                │
│    • Validation Requests (PR #52)                       │
│    • Validation Registry                                │
│    • Command Registry                                   │
│    • Evidence Runner                                    │
│    • Failure Classification                             │
│    • Capability State                                   │
│                                                         │
│  Safety Gate:                                           │
│    REFUSED capabilities:                                │
│      SetParameterValue, DeleteElements, MoveElements,   │
│      RotateElements, CreateWalls, CreateFloors,         │
│      CreateRoofs                                        │
│    REFUSED procedures:                                  │
│      unbounded_inventory_scan, full_model_export,       │
│      live_mutation                                      │
│                                                         │
│  Outputs:                                               │
│    • ValidationOrchestrationResult                      │
│      ├── run_id                                         │
│      ├── request_id                                     │
│      ├── status (pending/simulated/running/             │
│      │          completed/failed/refused)               │
│      ├── steps[] with results                           │
│      └── evidence[]                                     │
│                                                         │
│  Evidence Directory:                                    │
│    artifacts/validation_orchestrations/<run_id>/         │
│      ├── orchestration_request.json                     │
│      ├── orchestration_result.json                      │
│      ├── orchestration_summary.md                       │
│      ├── pass_fail.json                                 │
│      ├── step_results/                                  │
│      └── failure_classifications/                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Models

| Model | Purpose |
|-------|---------|
| `ValidationOrchestrationResult` | Complete run result with steps and evidence |
| `ValidationOrchestrationStep` | Individual step result (passed/failed/refused) |
| `ValidationOrchestrationEvidence` | Evidence artifact produced |
| `ControlledValidationOrchestrator` | Stateful orchestrator with safety gates |

## CLI Commands

```bash
# Execute a validation request
axiom validation-orchestrate --request-id <id> [--json-output]

# Simulate without execution
axiom validation-orchestrate --request-id <id> --simulate [--json-output]
```

## Safety Rules

1. Mutation capabilities are always refused
2. Unbounded scans are refused
3. Missing prerequisites block execution
4. Evidence is always written (even on refusal/failure)
5. Simulate mode marks all steps as passed without execution

## Non-Goals

- No retries
- No promotion
- No learning
- No scheduling
