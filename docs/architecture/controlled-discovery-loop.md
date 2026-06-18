# Controlled Discovery Loop v1

## Purpose

First end-to-end controlled loop where Axiom begins testing Axiom —
under tightly controlled, evidence-based conditions.

## Chain

```
Discovery → Candidate → State → Validation Request → Validation Execution
→ Failure Classification → Promotion Eligibility (check only, never apply)
```

## Models

| Model | Role |
|-------|------|
| `ControlledDiscoveryLoop` | Orchestrator for the full loop |
| `DiscoveryLoopResult` | Run result with steps, evidence, counts |
| `DiscoveryLoopStep` | Individual step in the loop |
| `DiscoveryLoopEvidence` | Evidence produced by the loop |
| `LoopStatus` | Enum: pending, running, simulated, completed, failed, refused |
| `LoopStepType` | Enum: discovery, candidate_generation, state_update, validation_request, validation_execution, classification, promotion_check |
| `StepOutcome` | Enum: passed, failed, skipped, refused, not_run |

## Loop Steps (7 total)

1. **Discovery** — discover capabilities from source
2. **Candidate Generation** — generate candidates from discoveries
3. **State Update** — update capability state
4. **Validation Request** — generate validation requests
5. **Validation Execution** — execute safe validations
6. **Classification** — classify results
7. **Promotion Check** — check eligibility (NEVER applied)

## CLI

```bash
axiom discovery-loop [--source <folder>] [--simulate] [--json-output]
```

## Safety Rules

1. No automatic promotion — `promotions_applied` is always 0
2. Mutation capabilities always refused
3. Unsafe procedures always refused
4. Evidence always written (even on refusal)
5. Simulate mode available for dry runs

## Key Invariant

```python
assert result.promotions_applied == 0  # ALWAYS
```

## Non-Goals

- No automatic promotion
- No mutations
- No retries
- No scheduling
- No learning
