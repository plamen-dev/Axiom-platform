# Knowledge Review and Approval Layer

## Purpose

Axiom accumulates candidate knowledge through the Knowledge Source Registry,
Knowledge Object Model, Provenance & Trust Engine, Workflow Knowledge Registry,
and Learning Candidate Engine.  This layer provides the governed mechanism to
determine what knowledge should be accepted, rejected, deprecated, superseded,
or kept as a candidate.

**Governance only.**  No autonomous approval.  No automatic learning.  No
automatic mutation of existing knowledge.

## Architecture

```
Knowledge Sources ─┐
Knowledge Objects ──┤
Provenance Records ─┼──▶ KnowledgeReviewRegistry ──▶ Governed Decisions
Workflow Definitions┤         (references only,       (approved / rejected /
Learning Candidates ┘          never mutates)          deprecated / superseded)
```

The review layer **references** upstream registries but **never mutates** them.
Review decisions are persisted independently in their own SQLite tables.

## Data Model

### KnowledgeReview

| Field | Type | Description |
|-------|------|-------------|
| `review_id` | `str` | Unique identifier (UUID) |
| `knowledge_id` | `str` | ID of the knowledge item under review |
| `knowledge_name` | `str` | Human-readable name |
| `decision` | `ReviewDecision` | Deterministic outcome |
| `reason` | `ReviewReason` | Categorised rationale |
| `status` | `ReviewStatus` | Lifecycle: open / closed |
| `reviewer` | `str?` | Who performed the review |
| `notes` | `str?` | Free-form notes |
| `evidence_paths` | `list[str]` | Paths to supporting evidence |
| `metadata` | `dict` | Arbitrary key-value metadata |
| `superseded_by` | `str?` | ID of the newer review that replaced this one |
| `created_at` | `str` | ISO 8601 timestamp |
| `updated_at` | `str` | ISO 8601 timestamp |

### ReviewDecision

Deterministic outcomes ordered by priority:

1. `approved` — knowledge accepted
2. `proposed` — under consideration
3. `needs_more_evidence` — insufficient evidence to decide
4. `rejected` — knowledge rejected
5. `deprecated` — previously accepted, now outdated
6. `superseded` — replaced by a newer review

### ReviewReason

Categorised rationale:

- `insufficient_evidence`
- `conflicting_knowledge`
- `duplicate`
- `obsolete`
- `low_confidence`
- `founder_override`
- `human_validation`
- `policy_violation`

## Persistence

SQLite tables (reuses Axiom database layer):

- `knowledge_reviews` — review records
- `knowledge_review_events` — lifecycle event log

## CLI

```
axiom knowledge-reviews [--json-output] [--name <filter>] [--decision <dec>] [--status <status>]
axiom knowledge-review-create --knowledge-id <id> --knowledge-name <name> --decision <dec> --reason <reason> [--notes <notes>] [--reviewer <reviewer>] [--json-output]
```

Invalid `--decision`, `--reason`, or `--status` values exit with code 1 and
list valid options.

## Ordering

Reviews list in **decision-priority** order (approved first), then
alphabetically by knowledge name within the same decision tier.

## Supersession

Reviews support supersession chains.  `supersede_review(old_id, new_id)` marks
the old review as superseded and closed, with the `superseded_by` field pointing
to the new review.  Self-supersession is rejected.  Chain walking stops on cycle
or missing link.

## Non-Goals

- No autonomous approval or rejection
- No automatic learning
- No semantic retrieval or graph traversal
- No workflow or capability execution
- No promotion logic or confidence learning
- No LLM scoring
- No autonomous mutation of upstream knowledge registries
