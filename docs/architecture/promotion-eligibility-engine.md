# Promotion Eligibility Engine v1

PR #30 — eligibility/governance infrastructure only.

## Purpose

Axiom can already discover, execute, validate, classify, and remember capability
lifecycle state, but it could not yet decide whether a capability is *eligible*
to be promoted from candidate/experimental toward trusted status.

The Promotion Eligibility Engine adds that decision layer. It **summarizes
existing governed sources** into one deterministic per-capability promotion
decision. It decides and recommends only: it promotes nothing, mutates no
registry or capability state, executes nothing, retries nothing, and schedules
nothing. The CLI may write an optional evidence record — that is a report, not a
state change.

This is the final governance layer before controlled autonomous loops: Axiom
must know which capabilities are trusted, which need more evidence, and which
must remain blocked.

## Components

| Component                    | Role |
|------------------------------|------|
| `PromotionStatus`            | Enum of 7 deterministic verdicts |
| `PromotionCriteria`          | Explicit, simple v1 thresholds/policy |
| `PromotionBlocker`           | A single reason a capability is not eligible |
| `PromotionEvidenceSummary`   | The consolidated read-only inputs the decision used |
| `PromotionDecision`          | The decision for one capability |
| `PromotionEligibilityEngine` | The decision engine itself |

## Consumed sources (read-only)

- **Capability State Registry (PR #27):** current lifecycle status, evidence
  counts (`pass_count`/`fail_count`/…), `validation_pass_count`, latest run ids,
  `last_evidence_path`. Also seeds the universe of known capabilities (validation
  registry + command registry + DiscoveryHarness candidates when a db exists).
- **Capability Validation Registry (PR #24):** whether a validation definition
  exists and the capability type (`mutation` is the strongest "not eligible"
  signal).
- **Runner Command Registry (PR #22):** the governed command a capability drives
  and its safety classification (`mutation` / `high_risk`).
- **Failure Classification Engine (PR #29):** the `failure_classification.json`
  written next to the latest evidence bundle — consumed when present, handled
  conservatively when absent.

## Promotion statuses

| Status                | Meaning |
|-----------------------|---------|
| `eligible`            | Meets every v1 criterion |
| `not_eligible`        | Known, but does not qualify (reserved) |
| `needs_more_evidence` | No / insufficient passing evidence, or no evidence bundle |
| `failed_recently`     | Latest run failed — must recover first |
| `blocked`             | Unresolved blocked/unsupported status, or critical/policy-violation classification |
| `policy_refused`      | Mutation/high-risk capability, or latest run refused by policy |
| `unknown`             | Not known to any registry/artifact (CLI exits non-zero) |

## Decision order (deterministic)

For a known capability, the engine returns the first matching verdict:

1. **Mutation / high-risk** (and not explicitly allowed) → `policy_refused`.
2. **Latest run refused** by policy → `policy_refused`.
3. **Failure classification** is a `policy_violation`, or severity `critical` →
   `blocked`.
4. **Unresolved** `blocked` / `unsupported` current status → `blocked`.
5. **Recent failure** (`execution_failed` / `validation_failed` current status)
   → `failed_recently`. (A later passing run changes the current status and
   clears this.)
6. **No evidence bundle** → `needs_more_evidence`.
7. **Insufficient passing runs** (`pass_count + validation_pass_count <
   minimum_successful_runs`) → `needs_more_evidence`.
8. Otherwise → `eligible`.

An unknown capability short-circuits to `unknown` before any of the above.

## v1 criteria (`PromotionCriteria` defaults)

- `minimum_successful_runs = 1` — at least one passing validation **or** execution.
- `require_evidence_bundle = True` — a valid evidence bundle must exist.
- `allow_mutation = False`, `allow_high_risk = False` — mutation/high-risk are
  not eligible in v1.
- `disallow_recent_failure = True`, `disallow_unresolved_block = True`.

The criteria are intentionally simple and explicit — not overfit. They are
captured on every decision so the threshold set is auditable.

### Why the engine does not enforce the validation registry's numeric contract

`ValidationProcedure.promotion_eligibility` (PR #24) carries a per-capability
contract (`minimum_successes`, `minimum_evidence_sets`, `required_confidence`,
default 3/3/0.8). v1 deliberately uses the simpler `PromotionCriteria` (≥1
passing run) so a single validated read-only capability can become eligible, per
the PR #30 default. The richer contract remains available for a future
confidence-scoring pass; v1 keeps the decision narrow.

## Failure-classification consumption

The engine reads `failure_classification.json` from the latest evidence bundle
(`last_evidence_path`) when present and records `category`/`severity` on the
evidence summary. A `policy_violation` category or `critical` severity blocks
promotion. When the file is absent or unreadable, it is ignored conservatively —
absence never makes a capability eligible, and a clean passing run with no
classification stays eligible.

## CLI

```bash
axiom promotion-check --capability InventoryModel
axiom promotion-check --capability SetParameterValue
axiom promotion-check --all
axiom promotion-check --all --json
```

- Exactly one of `--capability <name>` or `--all` is required.
- `--json` emits a machine-readable decision (single object, or
  `{"decisions": [...]}` for `--all`).
- An unknown capability exits non-zero (2) with a clear message.
- By default an evidence record is written under
  `artifacts/promotion_checks/<run_id>/`:
  - `promotion_decision.json`
  - `promotion_decision.md`
- `--no-write` skips the evidence record; `--out <dir>` overrides the location.
- Read-only: the command attaches to the SQLite db only if it already exists and
  never creates one. It modifies no capability state or candidate registry.

The command is cataloged in the Runner Command Registry as `read_only` / `safe`.

## Explicit non-goals

No automatic promotion, no registry/state mutation by default, no autonomous
discovery loop, no retry execution, no scheduling, no learning loop, no workflow
generation, no `SetParameterValue` execution, no mutation allowance, no external
integrations / MCP / Autodesk Assistant integration.

## 2024 baseline

Unaffected — this is read-only governance tooling over existing artifacts and
registries.
