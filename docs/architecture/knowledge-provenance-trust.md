# Knowledge Provenance & Trust Engine

## Strategic Purpose

Knowledge without provenance is dangerous. This engine establishes trust
infrastructure so Axiom can distinguish facts from suggestions, verified
patterns from candidates, and active knowledge from deprecated artifacts.

## Trust Levels

Ordered from highest to lowest trust:

| Level | Meaning |
|-------|---------|
| `founder_verified` | Directly authored/verified by founders |
| `human_verified` | Verified by human review |
| `evidence_supported` | Backed by evidence artifacts |
| `derived` | Derived from trusted sources |
| `candidate` | Unverified, pending review |
| `deprecated` | Previously trusted, now superseded |

## Source Confidence

| Level | Meaning |
|-------|---------|
| `high` | Source is authoritative and current |
| `medium` | Source is credible but may be stale |
| `low` | Source reliability is uncertain |
| `unknown` | No confidence assessment available |

## Provenance Status

| Status | Meaning |
|--------|---------|
| `active` | Current and valid |
| `superseded` | Replaced by newer provenance |
| `deprecated` | No longer trusted |

## Metadata Captured

- `provenance_id` — unique identifier
- `knowledge_name` — human-readable name
- `trust_level` — classification from trust hierarchy
- `source_confidence` — confidence in the originating source
- `status` — lifecycle status
- `origin` — where this knowledge came from (path, doc, PR)
- `evidence_paths` — paths to supporting evidence artifacts
- `approving_source` — who/what approved this trust level
- `confidence_score` — numeric confidence (0.0–1.0)
- `superseded_by` — provenance_id of replacement (if superseded)
- `notes` — free-text notes

## Supersession Chains

Knowledge evolves. When a newer version of knowledge replaces an older
version, the old provenance is marked `superseded` with a pointer to
the new provenance. Chains can be walked to trace knowledge evolution.

Cycles are tolerated (detected and stopped) — they indicate data
quality issues but must not crash the system.

## Persistence

SQLite tables:
- `knowledge_provenance` — provenance records
- `knowledge_provenance_events` — lifecycle event log

## CLI

```bash
# Human-readable table (ordered by trust level)
axiom knowledge-provenance

# Filter by name
axiom knowledge-provenance --name "Grid"

# Filter by trust level
axiom knowledge-provenance --trust-level human_verified

# Include deprecated records
axiom knowledge-provenance --include-deprecated

# Machine-readable JSON
axiom knowledge-provenance --json-output
```

## Python API

```python
from axiom_core.knowledge_provenance import (
    KnowledgeProvenance,
    KnowledgeProvenanceRegistry,
    TrustLevel,
    SourceConfidence,
    trust_rank,
)

registry = KnowledgeProvenanceRegistry()

# Register provenance
prov = KnowledgeProvenance(
    knowledge_name="Grid Creation Pattern",
    trust_level=TrustLevel.EVIDENCE_SUPPORTED,
    source_confidence=SourceConfidence.HIGH,
    origin="docs/architecture/grid-creation.md",
    evidence_paths=["artifacts/grid_test_runs/run_001"],
)
registry.register(prov)

# List ordered by trust
records = registry.list_provenance()

# Walk supersession chain
chain = registry.get_supersession_chain(prov.provenance_id)

# Compare trust levels
assert trust_rank(TrustLevel.FOUNDER_VERIFIED) < trust_rank(TrustLevel.CANDIDATE)
```

## Non-Goals

- No automatic trust updates
- No confidence learning
- No LLM scoring
- No graph traversal
- No semantic search
- No embeddings

## Future Layers

Once the provenance engine is stable, future PRs may add:
- Confidence decay (time-based trust reduction)
- Evidence-based promotion (auto-upgrade trust when evidence accumulates)
- Cross-reference with Knowledge Object Model (PR #37)
- Integration with capability promotion scoring
