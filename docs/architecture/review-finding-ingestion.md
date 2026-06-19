# Review Finding Ingestion v1

## Position in Chain

```
Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
-> Patch Application -> Code Validation -> PR Draft
-> Review Findings (this module)
```

## Purpose

Converts review feedback into persistent, categorized findings with
pattern tracking and history preservation. Establishes durable engineering
memory for review feedback before the self-improvement loop.

## Components

| Component | Role |
|-----------|------|
| `ReviewFindingRegistry` | Main registry — CRUD + ingestion + patterns |
| `ReviewFinding` | Individual finding record |
| `ReviewCategory` | 7 categories: bug, flag, security, architecture, performance, style, informational |
| `ReviewSeverity` | 5 levels: critical, high, medium, low, informational |
| `ReviewPatternKind` | 9 recurring patterns + other |
| `ReviewHistory` | Audit trail for status changes |
| `ReviewPattern` | Detected pattern record |

## Pattern Tracking

Automatically detects recurring patterns from finding text:

| Pattern | Keywords |
|---------|----------|
| `truthiness_bug` | truthiness, truthy, falsy, bool check |
| `enum_serialization` | enum serial, .value |
| `persistence_defect` | persist, updated_at, write, save |
| `evidence_failure` | evidence, artifact, bundle |
| `silent_exception` | silent, swallow, bare except |
| `duplicated_logic` | duplicate, redundant, copy |
| `path_traversal` | path traversal, CWE-22, ../ |
| `command_injection` | command injection, CWE-88, shlex |
| `stage_ordering` | stage order, deterministic order |

## Evidence Outputs

Written to `artifacts/review_findings/<run_id>/`:

| File | Purpose |
|------|---------|
| `review_request.json` | Ingestion request metadata |
| `review_result.json` | Full results with category/severity/pattern counts |
| `review_summary.md` | Human-readable summary |
| `pass_fail.json` | Machine-readable verdict |

## CLI

```bash
axiom review-findings [--category <cat>] [--severity <sev>] [--status <status>] [--pattern <kind>] [--json-output]
axiom review-finding --id <id> [--json-output]
axiom review-finding-create --title <title> [--category <cat>] [--severity <sev>] [--json-output]
axiom review-finding-update --id <id> [--status <status>] [--resolution <text>] [--json-output]
axiom review-finding-ingest [--draft-id <id>] [--source-dir <dir>] [--json-output]
axiom review-patterns [--kind <kind>] [--json-output]
```

## Non-Goals

- No automatic repair
- No learning loops
- No patch generation
- No PR creation
- No code modification
- No GitHub API
- No network dependency

## Strategic Significance

PR #61 applies changes. PR #62 validates them. PR #63 generates release
artifacts. PR #64 converts review feedback into durable engineering memory.
This establishes the feedback layer required before PR #65 Self-Improvement
Loop v1.
