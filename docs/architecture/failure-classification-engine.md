# Failure Classification Engine v1

PR #29 — classification/governance infrastructure only.

## Purpose

Axiom produces `passed`/`failed`/`denied`/`refused`/`blocked`/`unsupported`
outcomes from the Capability Execution Runner (PR #26) and the Validation
Evidence Runner (PR #25), but it does not yet normalize failure causes into
durable categories or determine whether a failed run is retryable.

The Failure Classification Engine reads existing evidence bundles and produces
a deterministic classification — category, severity, retry eligibility, and a
structured retry decision — that future promotion, recovery, and autonomous
discovery loops will consume.

## Components

| Component                  | Role                                              |
|----------------------------|---------------------------------------------------|
| `FailureCategory`          | Enum of 14 deterministic failure categories       |
| `FailureSeverity`          | Enum of 4 severity levels (info/warning/error/critical) |
| `RetryDecision`            | Structured retry recommendation                   |
| `RetryEligibility`         | High-level eligibility (not_needed/eligible/ineligible/conditional) |
| `RetryPolicyEvaluator`     | Rules engine mapping category → retry decision    |
| `FailureEvidenceSummary`   | Consolidated classification record                |
| `FailureClassificationEngine` | The classifier itself                          |

## Failure Categories

| Category               | Outcome mapping            | Severity  | Retry eligible? |
|------------------------|----------------------------|-----------|-----------------|
| `passed`               | outcome=passed             | info      | not needed      |
| `denied`               | outcome=denied             | warning   | no              |
| `refused`              | outcome=refused            | info      | no              |
| `blocked`              | outcome=blocked            | error     | conditional (env change) |
| `unsupported`          | outcome=unsupported        | warning   | no              |
| `execution_failed`     | outcome=failed (default)   | error     | yes (3×, 10s)   |
| `validation_failed`    | outcome=failed (val bundle)| error     | yes (2×, 5s)    |
| `prerequisite_missing` | failed + prerequisite keywords | error | conditional (env change) |
| `transport_failed`     | failed + bridge keywords   | error     | conditional (human) |
| `timeout`              | failed + timeout keywords  | error     | yes (2×, 60s)   |
| `parse_error`          | malformed pass_fail.json / failed + parse keywords | error | no (fix first) |
| `evidence_missing`     | pass_fail.json absent      | error     | no (fix pipeline) |
| `policy_violation`     | reserved (governance breach during execution) | critical | no |
| `unknown_error`        | unrecognized outcome       | error     | no (investigate) |

## Sub-classification of "failed" outcomes

When `outcome == "failed"`, the engine inspects the check details and reason
string for keywords to sub-classify:

1. Prerequisite keywords (prerequisite, prerequisites, missing_prerequisite) →
   `prerequisite_missing`
2. Bridge/transport keywords (bridge, transport, pipe, connection, unavailable,
   unreachable, namedpipe) → `transport_failed`
3. Timeout keywords (timeout, timed out, deadline, exceeded) → `timeout`
4. Validation bundle type → `validation_failed`
5. Default → `execution_failed`

The direct `outcome=blocked` verdict from the runner (command prerequisites not
met) maps to the `blocked` category, mirroring `CapabilityStatus.BLOCKED`.
`prerequisite_missing` is reserved for `failed` runs whose evidence explicitly
names an unmet declared prerequisite.

## CLI

```bash
axiom classify-failure --evidence-path <path>
axiom classify-failure --evidence-path <path> --json
```

Writes `failure_classification.json` + `failure_classification.md` into the
evidence directory. Never overwrites `pass_fail.json`.

## State Registry Integration (deferred)

The Capability State Registry (PR #27) already consumes `pass_fail.json`
outcomes and maps them to lifecycle statuses. In a future PR (#30+), the
state registry could additionally consume `failure_classification.json` to:

- Store `failure_category` and `retry_eligibility` on `CapabilityState`
- Expose classification in `axiom capability-state --name <cap>` output
- Feed the promotion engine with retry-eligibility signals

This integration was deferred to keep PR #29 narrow — classification only,
no state mutation beyond writing the classification files.

## Explicit Non-Goals

- Automatic retry execution
- Retry scheduling
- Promotion engine
- Learning loop
- Autonomous discovery loop
- Capability mutation
- External integrations / MCP
