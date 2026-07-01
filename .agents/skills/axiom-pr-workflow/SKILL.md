---
name: axiom-pr-workflow
description: PR execution guidance for Axiom-platform PRs — compute mode recommendation, pre-review self-audit for architecture-sensitive changes, Purpose-to-Workflow reconciliation gate, test tiering, reporting conventions, and the same-PR skill-update rule. Use when creating, reviewing, or preparing to merge any Axiom PR.
---

# Axiom PR workflow

## Domain

How PRs are scoped, audited, tested, and reported in Axiom-platform. This is **operational guidance, not doctrine**.

## Recommended Devin Compute Mode

Future Axiom PR task packets should include a compute-mode section.

### Template

```
Recommended Devin Compute Mode:
* Ultra / Normal / Fast
* Reason: <why this mode>
* Operator Action Required:
  - Keep current mode
  - Switch to Ultra before starting
  - Switch down after planning
  - Switch down after architecture-impacting work is complete
```

### When to use Ultra

Use Ultra when reasoning failure would be expensive:

- repo-wide reconciliation
- duplicate-concept detection
- architectural cleanup
- M4 vertical execution-chain reasoning
- M2 evidence-to-promotion mapping
- M3 purpose/layer/consumer mapping
- deciding whether code should be deleted, merged, preserved, or deferred
- resolving contradictions between implementation and canonical direction
- producing architecture-impacting PR scope

### When to use Normal/Fast

Use Normal/Fast when work is bounded, mechanical, already scoped, or primarily validation/refactor/docs work.

## Required Pre-Review Self-Audit

For architecture-sensitive PRs, before marking the PR review-ready, perform and post a self-audit in the PR body.

### Trigger conditions

Trigger the self-audit for PRs that touch:

- execution flow
- evidence
- capability state
- confidence/readiness
- promotion behavior
- persistent artifacts
- registries
- canonical doctrine
- source-of-truth boundaries
- CLI validation evidence
- architectural/program boundaries

### Self-audit checklist

Check each of these before posting the PR:

- [ ] overclaims (does the PR body claim more than the code delivers?)
- [ ] new object families (were any introduced without justification?)
- [ ] doctrine accidentally encoded in code (should it be routed to a Program instead?)
- [ ] idempotency / duplicate handling (can the same input be applied twice safely?)
- [ ] conflict handling (are contradictory signals handled explicitly, not silently?)
- [ ] invalid/stale/missing behavior (are edge cases covered?)
- [ ] source-of-truth boundaries (does the PR respect existing ownership?)
- [ ] unresolved questions routed rather than silently solved
- [ ] PR body accurately describes closure scope (no overclaiming EVID-* or gap closures)

## Purpose-to-Workflow Reconciliation Gate

For architecture-sensitive PRs, answer these questions in the PR body before implementing:

1. What existing PR/component/capability does this use?
2. What workflow does it participate in?
3. What consumes its output?
4. What evidence proves it works?
5. Is the result integrated, support-only, planning-only, superseded, duplicate candidate, deprecated, unresolved, or temporary?
6. What existing structure was checked before adding anything new?
7. What complexity, latency, indirection, or duplicate-engine risk does this introduce?
8. What should be deleted, merged, preserved, or left alone?

## Test tiering (per repo policy)

Code + tests changes: run targeted tests then full `poetry run pytest` + `poetry run ruff check` at the PR checkpoint. Docs/log-only changes: do not run full pytest. After each session report tests run, tests intentionally skipped, and reason.

## Skill updates travel with the PR

Any PR that changes how a domain is operated, tested, or verified must update that domain's `SKILL.md` (under `.agents/skills/`) **in the same PR**, populated at the end of the work — after verification, before marking ready for review. New domains get their skill directory in the PR that introduces them. See `.agents/skills/README.md` for the full policy.

## Reporting

Post ONE PR comment with collapsed <details> sections (pre-expand the main evidence), inline screenshots, the recording, and a link to the Devin session. Update relevant ledgers (`docs/logs/behavior-change-ledger.md`, `docs/logs/bug-validation-log.md`, `docs/logs/pr-review-ledger.md`) when behavior changes.
