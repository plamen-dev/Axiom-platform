# Learning Candidate Engine

## Strategic Purpose

Provides the bridge between static knowledge and future self-improvement.
Identifies patterns worth learning — does NOT learn them.

## Scope

Consumes:
- Capability state (repeated success/failure)
- Evidence bundles (validation results)
- Failure classifications (recurring failures)
- Workflow registry (repeated workflows)

Produces:
- Suggested candidates only
- No acceptance, no promotion, no registry mutation

## Candidate Types

| Type | Description |
|------|-------------|
| `repeated_success` | Same capability succeeds repeatedly |
| `repeated_failure` | Same capability fails repeatedly |
| `repeated_workflow` | Same workflow pattern observed multiple times |
| `recurring_parameter_usage` | Same parameter set used across runs |
| `recurring_validation_pattern` | Same validation sequence repeated |

## Data Model

### LearningCandidate

| Field | Type | Description |
|-------|------|-------------|
| `candidate_id` | string | Unique identifier |
| `candidate_name` | string | Human-readable pattern name |
| `candidate_type` | CandidateType | Classification |
| `strength` | strong/moderate/weak/speculative | Confidence level |
| `status` | active/merged/dismissed | Lifecycle |
| `confidence_score` | int (0-100) | Numeric confidence |
| `observation_count` | int | Times this pattern observed |
| `sources` | list[CandidateSource] | Where observed |
| `evidence` | list[CandidateEvidence] | Supporting evidence |

### CandidateSource

| Field | Type | Description |
|-------|------|-------------|
| `source_type` | string | e.g. capability_state, workflow_registry |
| `source_id` | string | ID in the source system |
| `source_name` | string | Human-readable source |
| `observation_timestamp` | string | When observed |

### CandidateEvidence

| Field | Type | Description |
|-------|------|-------------|
| `evidence_type` | string | e.g. run_artifact, validation_result |
| `evidence_path` | string | Path to evidence file |
| `description` | string | What this proves |
| `timestamp` | string | When captured |

## Duplicate Merging

When a candidate with the same `name + type` is registered:
1. Observation count incremented
2. Sources merged (accumulated)
3. Evidence merged (accumulated)
4. Confidence score increased (capped at 100)
5. Strength auto-upgraded: 3+ observations → moderate, 5+ → strong

## Confidence Ordering

Candidates are always returned ordered by:
1. `confidence_score` descending (highest first)
2. `candidate_name` ascending (alphabetical tiebreaker)

This ordering is deterministic across repeated queries.

## CLI

```bash
# Human-readable table
axiom learning-candidates

# Filter by name
axiom learning-candidates --name "Grid"

# Filter by type
axiom learning-candidates --type repeated_success

# Include dismissed
axiom learning-candidates --include-dismissed

# Machine-readable JSON
axiom learning-candidates --json-output
```

## Persistence

SQLite table: `learning_candidates`

## Non-Goals

- No learning / autonomous changes
- No registry mutation
- No workflow execution
- No embeddings
- No acceptance or promotion

## Future Layers

Once candidates are stable, future PRs may add:
- Candidate acceptance (human approval → promoted pattern)
- Automatic candidate generation from run history
- Cross-reference with Knowledge Provenance (PR #38)
- Integration with Verification Factory promotion scoring
