# Knowledge-Aware Capability Planner v1

## Purpose

Transforms accumulated knowledge into structured capability plans.

## What it does

- Consumes knowledge graph, semantic retrieval results, workflow definitions,
  provenance records, reviews, learning candidates, and failure patterns.
- Generates structured plans with ordered steps, dependencies, evidence,
  assumptions, risks, validations, and explanations.
- Persists plans to SQLite for retrieval and audit.

## What it does NOT do

- Execute capabilities.
- Mutate knowledge state.
- Run autonomous planning loops.
- Use embeddings, LLM scoring, or vector databases.

## Data model

- `PlanningRequest` — objective + max_steps
- `PlanningResult` — full plan with steps, dependencies, evidence, explanations
- `PlanningStep` — ordered step with capabilities, evidence, risk notes
- `PlanningDependency` — `requires | recommends | validates | derived_from`
- `PlanningEvidence` — evidence reference with trust level
- `PlanningExplanation` — reason + source for each step and plan-level decision

## Plan generation flow

1. Retrieve relevant knowledge via `SemanticRetrievalEngine`.
2. Extract workflow steps from matched workflows via `WorkflowKnowledgeRegistry`.
3. Build planning steps: workflow steps first, then knowledge matches.
4. Derive sequential dependencies.
5. Collect assumptions, risks, validations from knowledge.
6. Collect evidence references from provenance.
7. Generate plan-level explanations.
8. Persist plan to database.

## Ordering

Deterministic:
1. Workflow-derived steps first (by step_order).
2. Knowledge-derived steps second (by retrieval score).
3. Dependencies: sequential chain.

## Safety

- Empty objectives rejected.
- Max steps capped at 50.
- Plans never execute capabilities.
- Plans never mutate knowledge.

## CLI

```
axiom plan "diffuser placement"
axiom plan "room occupancy" --json-output
axiom plan "grid creation" --max-steps 20
```

## Database

Table: `capability_plans`

## Dependencies

- `SemanticRetrievalEngine` (PR #43)
- `WorkflowKnowledgeRegistry` (PR #39)
- Knowledge Graph (PR #42)
- All upstream registries consumed via retrieval engine
