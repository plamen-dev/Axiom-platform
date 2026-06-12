# Semantic Retrieval Engine v1

## Purpose

Retrieval infrastructure for the Axiom knowledge system.  The engine
answers questions like:

- What do we know about diffuser placement?
- Which workflows depend on room occupancy?
- Which capabilities consume this parameter?
- What evidence supports this decision?

The graph and registries remain the source of truth.

## Architecture

```
RetrievalQuery  ──►  SemanticRetrievalEngine  ──►  RetrievalResult
                          │                           │
                          ├─ Phase 1: node search     ├─ matches[]
                          │   (exact + partial)       │   .object_id
                          │                           │   .score
                          ├─ Phase 2: relationship    │   .trust_level
                          │   search via graph edges  │   .explanation
                          │                           │
                          ├─ Dedup by object_id       ├─ total_candidates
                          ├─ Enrich trust/approval    │
                          └─ Sort deterministically   └─ query metadata
```

## Query Types

| Type | Example | Mechanism |
|------|---------|-----------|
| Exact | `"Room Occupancy"` | Label equals query (case-insensitive) |
| Partial | `"Occupancy"` | Label contains query substring |
| Type-filtered | `"Room" --type workflow` | Restrict to node type |
| Relationship-aware | `"Room Occupancy"` | Also returns nodes connected via graph edges |

## Scoring

Deterministic, simple scoring:

| Factor | Points |
|--------|--------|
| Exact name match | 100 |
| Partial name match | 50 |
| Relationship match | 30 |
| Trust: founder_verified | +25 |
| Trust: human_verified | +20 |
| Trust: evidence_supported | +15 |
| Trust: derived | +10 |
| Trust: candidate | +5 |
| Approval: approved | +15 |
| Approval: proposed | +5 |
| Approval: needs_more_evidence | +2 |

Tiebreakers: score DESC → trust rank → approval rank → name ASC.

## Explanations

Every match includes an explanation:

- `"Exact object name match."`
- `"Partial match: label contains 'occupancy'."`
- `"Relationship derived from Knowledge Graph: connected to 'Room Occupancy' via depends_on."`

## CLI

```
axiom retrieve "room occupancy"
axiom retrieve "diffuser placement"
axiom retrieve "InventoryModel" --type capability
axiom retrieve "grid creation" --json-output
axiom retrieve "lighting load" --max-results 5
```

## Safety

- Empty queries rejected (ValueError / exit 1).
- Max results capped at 100.
- Unknown types return empty results cleanly.
- Never mutates knowledge.
- Read-only queries against existing graph/registries.

## Inputs Consumed

| Registry | Consumed via |
|----------|-------------|
| Knowledge Objects | Graph nodes |
| Knowledge Relationships | Graph edges |
| Workflow Definitions | Graph nodes + edges |
| Knowledge Provenance | Graph nodes (trust enrichment) |
| Knowledge Reviews | Graph edges (approval enrichment) |
| Learning Candidates | Graph nodes |
| Capability State | Graph nodes |

## Non-Goals

- No embeddings
- No vector database
- No LLM scoring
- No probabilistic ranking
- No autonomous reasoning
- No planning or execution
- No learning or automatic approval

## Strategic Context

PR #42 connected knowledge into a graph.
PR #43 enables retrieval and explanation of that knowledge.
This is the first knowledge access layer before planning and AI-native reasoning.
