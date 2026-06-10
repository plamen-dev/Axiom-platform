# Knowledge Source Registry

## Overview

The Knowledge Source Registry is a governed metadata layer describing every
source of knowledge that Axiom may consume. It establishes **where knowledge
comes from** before Axiom reasons about it.

This is metadata and governance only:
- No retrieval
- No embeddings
- No vector DB
- No graph
- No learning
- No workflow execution

## Architecture

```
Knowledge Source → register() → SQLite (knowledge_sources table)
                                        ↓
CLI / API ←──── list_sources() / refresh() / to_json()
```

## Source Types

| Type | Description |
|---|---|
| `architecture_doc` | System architecture documentation |
| `runbook` | Operational runbook |
| `skill` | Agent/system skill definition |
| `pr_snapshot` | Pull request state capture |
| `evidence_bundle` | Validation evidence artifacts |
| `capability_state` | Capability lifecycle state |
| `validation_registry` | Validation rule/procedure registry |
| `command_registry` | Command governance definitions |
| `discovery_candidate` | Candidate for discovery processing |
| `founder_document` | Foundational strategy document |
| `workflow_document` | Workflow specification |
| `external_reference` | External reference material |

## Source Lifecycle

```
ACTIVE → DISABLED (excluded from default listing)
ACTIVE → DEPRECATED (still listed, marked deprecated)
DISABLED → ACTIVE (re-enabled)
```

## Metadata Schema

```json
{
  "source_id": "ks_001",
  "source_name": "Local Audit Spine Doc",
  "source_type": "architecture_doc",
  "path": "docs/architecture/local-audit-and-run-spine.md",
  "created_at": "2026-06-07T12:00:00+00:00",
  "updated_at": "2026-06-07T12:00:00+00:00",
  "enabled": true,
  "deprecated": false,
  "trust_level": "high",
  "notes": null
}
```

## Persistence

Uses SQLite via SQLAlchemy (same database layer as jobs, plans, etc).

### Tables

**`knowledge_sources`** — source definitions:
- `source_id` (PK)
- `source_name`
- `source_type`
- `path`
- `created_at`, `updated_at`
- `enabled`, `deprecated`
- `trust_level`, `notes`

**`knowledge_source_events`** — lifecycle event log:
- `event_id` (PK)
- `source_id`
- `event_type` (registered, updated, disabled, enabled, deprecated)
- `timestamp_utc`
- `details`

## CLI

```bash
# Human-readable table
axiom knowledge-sources

# Machine-readable JSON
axiom knowledge-sources --json-output

# Filter by name
axiom knowledge-sources --name "audit"

# Deterministic refresh
axiom knowledge-sources --refresh

# Include disabled sources
axiom knowledge-sources --include-disabled
```

## Python API

```python
from axiom_core.knowledge_registry import (
    KnowledgeSourceMetadata,
    KnowledgeSourceRegistry,
    KnowledgeSourceType,
)

registry = KnowledgeSourceRegistry()

# Register
source = KnowledgeSourceMetadata(
    source_id="ks_001",
    source_name="Local Audit Spine Doc",
    source_type=KnowledgeSourceType.ARCHITECTURE_DOC,
    path="docs/architecture/local-audit-and-run-spine.md",
    trust_level="high",
)
registry.register(source)

# List
sources = registry.list_sources()

# JSON
print(registry.to_json())

# Refresh (deterministic)
active = registry.refresh()

# Disable/enable
registry.disable("ks_001")
registry.enable("ks_001")
```

## Strategic Purpose

The Knowledge Registry establishes where knowledge comes from before Axiom
reasons about it. Future layers (retrieval, relevance ranking, learning) will
build on top of this governed source list.

## Adding New Source Types

1. Add the type to `KnowledgeSourceType` enum in `knowledge_registry.py`.
2. Register sources of that type.
3. Document the type in this file.
