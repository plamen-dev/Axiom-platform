# Knowledge Graph Foundation v1

## Purpose

Connects knowledge objects, workflows, provenance, evidence, capabilities, failures, and decisions into a navigable structure derived from existing registries.

Structural/navigation infrastructure only — no semantic retrieval, no embeddings, no autonomous reasoning, no workflow execution.

## Architecture

The graph is **derived** from existing registries, not a competing source of truth:

```
Knowledge Sources ──┐
Knowledge Objects ──┤
Knowledge Provenance┤
Workflow Definitions┼──> KnowledgeGraph (nodes + edges)
Learning Candidates ┤
Knowledge Reviews ──┘
```

### Node Types

| Type | Source Registry |
|------|---------------|
| `knowledge_source` | Knowledge Source Registry |
| `knowledge_object` | Knowledge Object Model |
| `workflow` | Workflow Knowledge Registry |
| `workflow_step` | Workflow Knowledge Registry |
| `rule` | Workflow Knowledge Registry |
| `capability` | (future) Capability Registry |
| `evidence` | (future) Evidence bundles |
| `provenance` | Knowledge Provenance |
| `review` | Knowledge Reviews |
| `learning_candidate` | Learning Candidate Engine |
| `failure_pattern` | (future) Failure classifications |
| `decision` | (future) Promotion decisions |

### Edge Types

| Type | Semantic |
|------|---------|
| `relates_to` | General relationship |
| `depends_on` | Dependency |
| `derived_from` | Derivation |
| `validated_by` | Validation/provenance |
| `supersedes` | Supersession |
| `approved_by` | Approval decision |
| `rejected_by` | Rejection decision |
| `reviewed_by` | General review |
| `supported_by` | Evidence support |
| `produced_by` | Production |
| `consumes` | Consumption |
| `produces` | Production |
| `failed_by` | Failure |
| `candidate_for` | Learning candidate |
| `has_step` | Workflow → step |
| `has_rule` | Workflow → rule |
| `sourced_from` | Object → source |

## Persistence

SQLite tables:

- `knowledge_graph_nodes` — node_id, node_type, source_registry, label, metadata_json, created_at
- `knowledge_graph_edges` — edge_id, source_node_id, target_node_id, edge_type, source_registry, metadata_json, created_at
- `knowledge_graph_snapshots` — snapshot_id, node_count, edge_count, node_types_json, edge_types_json, source_registries_json, created_at

Edge IDs are deterministic: `{source}--{type}-->{target}` for registry-derived edges.

## Traversal

Bounded BFS traversal:
- Default max depth: 2
- Hard cap: 10 (`MAX_TRAVERSAL_DEPTH`)
- Cycles detected but do not crash or loop
- Results are deterministically ordered (by type, then label/ID)

## CLI

```
axiom knowledge-graph                          # Summary
axiom knowledge-graph --json-output            # Full JSON dump
axiom knowledge-graph --refresh                # Rebuild from registries
axiom knowledge-graph --node <id>              # Node lookup
axiom knowledge-graph --neighbors <id>         # Neighbor traversal
axiom knowledge-graph --neighbors <id> --depth 3  # Bounded traversal
```

## Safety

- Read-only by default
- `--refresh` rebuilds from registries (no external calls)
- No graph database (no Neo4j, no vector DB)
- No embeddings
- No autonomous reasoning

## Future Sources

These registries are documented as future graph inputs but not yet consumed:
- Capability State (capability registry)
- Failure Classifications (failure classifier)
- Promotion Decisions (promotion score)

## Non-Goals

- Semantic retrieval
- Embeddings / vector database
- Graph database (Neo4j etc.)
- Autonomous reasoning / inference
- Workflow execution
- Capability execution
- Learning / promotion logic
- External integrations / MCP
