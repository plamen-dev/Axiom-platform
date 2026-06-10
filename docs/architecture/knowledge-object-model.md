# Knowledge Object Model

## Strategic Purpose

The Knowledge Object Model creates a universal, first-class representation
for all knowledge Axiom reasons about.  Knowledge is no longer implicit
in files — it is typed, named, versioned, and can form governed relationships.

This is a common language for all future reasoning layers.

## Explicit Non-Goals

- No graph traversal (BFS/DFS/shortest-path algorithms)
- No semantic search
- No inference or reasoning engine
- No embeddings or vector similarity
- No workflow execution

## Object Types

| Type | Description |
|------|-------------|
| `concept` | Abstract domain idea or terminology |
| `rule` | Constraint, invariant, or policy |
| `workflow` | Multi-step process or procedure |
| `pattern` | Reusable solution template |
| `capability` | Executable Axiom capability reference |
| `decision` | Architectural or operational decision record |
| `playbook` | Operational runbook or playbook |
| `failure_pattern` | Known failure mode with classification |
| `evidence_reference` | Pointer to evidence artifacts |

## Relationship Types

| Type | Semantics |
|------|-----------|
| `depends_on` | Source requires target to function |
| `derived_from` | Source was created from target |
| `validated_by` | Source is validated/proven by target |
| `supersedes` | Source replaces target |
| `related_to` | Loose association |
| `consumes` | Source reads/uses target as input |
| `produces` | Source generates target as output |

Cycles are explicitly allowed — this is metadata, not execution dependency.

## Object Schema

```json
{
  "object_id": "obj_001",
  "object_name": "Grid Creation Pattern",
  "object_type": "pattern",
  "description": "Standard grid creation workflow",
  "source_id": "ks_001",
  "created_at": "2026-06-07T12:00:00+00:00",
  "updated_at": "2026-06-07T12:00:00+00:00",
  "version": "1.0",
  "metadata": {}
}
```

## Relationship Schema

```json
{
  "relationship_id": "rel_uuid",
  "source_object_id": "obj_001",
  "target_object_id": "obj_002",
  "relationship_type": "depends_on",
  "created_at": "2026-06-07T12:00:00+00:00",
  "notes": "Grid creation depends on level setup"
}
```

## Persistence

Two SQLite tables via SQLAlchemy ORM:

| Table | Purpose |
|-------|---------|
| `knowledge_objects` | Object definitions and metadata |
| `knowledge_relationships` | Typed edges between objects |

Reuses the existing `axiom_core.database` layer (WAL mode, session management).

## CLI

```bash
# List all knowledge objects (human-readable table)
axiom knowledge-objects

# Machine-readable JSON
axiom knowledge-objects --json-output

# Filter by name substring
axiom knowledge-objects --name "grid"

# Filter by type
axiom knowledge-objects --type pattern

# List relationships
axiom knowledge-relationships

# Filter relationships by object
axiom knowledge-relationships --object-id obj_001

# Filter by relationship type
axiom knowledge-relationships --type depends_on
```

## Python API

```python
from axiom_core.knowledge_objects import (
    KnowledgeObject,
    KnowledgeObjectRegistry,
    KnowledgeObjectType,
    KnowledgeRelationship,
    RelationshipType,
)

registry = KnowledgeObjectRegistry()

# Create objects
registry.create_object(KnowledgeObject(
    object_id="obj_001",
    object_name="Grid Creation Pattern",
    object_type=KnowledgeObjectType.PATTERN,
    description="Standard grid creation workflow",
))

# Create relationships
registry.create_relationship(KnowledgeRelationship(
    source_object_id="obj_001",
    target_object_id="obj_002",
    relationship_type=RelationshipType.DEPENDS_ON,
))

# Query
objects = registry.list_objects(name_filter="grid")
rels = registry.get_relationships_for("obj_001")
```

## How Future Layers Build on This

| Future Layer | How It Uses Knowledge Objects |
|-------------|-------------------------------|
| Retrieval | Queries objects by type/relationship to find relevant knowledge |
| Relevance Ranking | Scores objects based on relationship distance and metadata |
| Learning Loop | Creates new objects from validated patterns |
| Reasoning | Traverses relationships to build context for decisions |
| Promotion | Links evidence_reference objects to capability objects |
