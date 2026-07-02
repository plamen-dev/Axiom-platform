---
name: testing-evidence-promotion
description: Verify the M2 evidence-to-promotion loop — capability-evidence-apply, evidence-quality quarantine, duplicate/conflict/stale handling, evidence history/show, and cli-validation-record bundles. Use when testing evidence intake, confidence/readiness promotion, or validation-evidence recording.
---

# Testing evidence promotion (M2)

## Domain

How evidence flows into capability confidence/readiness and how validation evidence is recorded. Source: `src/axiom_core/evidence_promotion.py`, `src/axiom_core/evidence_quality.py`, `src/axiom_core/capability_confidence.py`. Run CLI walkthroughs in the recordable terminal (see `testing-axiom-cli`) with shell-authoritative JSON checks alongside.

## Commands

- `axiom capability-evidence-apply --evidence <path> [--capability-id <id>] [--max-age-seconds <n>] [--artifacts-root <p>] [--json-output]`
- `axiom capability-evidence-history --capability-id <id> [--artifacts-root <p>]`
- `axiom capability-evidence-show <intake_id> [--artifacts-root <p>]`
- `axiom cli-validation-record --plan <path> [--artifacts-root <p>] [--name <run-name>] [--set KEY=VALUE] [--dry-run] [--json-output]`

## Registry pointers

- Confidence/readiness state: `CapabilityConfidenceEngine` reports under `artifacts/capability_confidence/`.
- Intake audit records: `artifacts/capability_evidence_intake/<intake_id>/report.json` + `pass_fail.json` (exactly 2 files; not a new registry).
- Quality rule table: `_REQUIRED_METRICS` in `src/axiom_core/evidence_quality.py`.

## Verification checklists

### capability-evidence-apply (hardened, PR #147/#148/#54)

1. **Show baseline confidence/readiness:** Before applying evidence, confirm the capability starts at `very_low (0.0) / blocked`.
2. **Apply passing evidence:** Assert: decision `accepted`, confidence raised by **exactly one ladder step** (`very_low → low`, readiness `blocked → provisional`), `Signals:` line present, and the record's `promotion` field shows `{raw_level: low, effective_level: low, clamped: false}` — 1/1 damped by evidence mass scores 0.3333 (BHV-037), so the raw level is already `low` and the BHV-036 ladder does not need to clamp.
3. **Show after state:** Confirm updated confidence/readiness, factors (successes/executions), linkage fields (capability, result, artifact, report).
4. **Apply failing evidence:** Assert: decision `accepted`, confidence reduced, readiness may drop to `provisional` or `blocked`, factors show failure increment.
5. **Apply duplicate evidence:** Re-apply the exact same evidence file. Assert: decision `duplicate`, `state_changed: false`, confidence/readiness unchanged, `duplicate_of` references the prior accepted intake, execution/success counts do NOT inflate.
6. **Apply conflicting evidence:** Create evidence where `evidence.json` has `passed: true` but sibling `trace.json` has `status: FAIL`. Assert: outcome `conflict`, decision `quarantined`, `state_changed: false`, `Signals:` shows both disagreeing signals, reason mentions "rather than resolved by source priority".
7. **Apply invalid/no-identity evidence:** Evidence without `capability_id` in references. Assert: decision `quarantined`, `state_changed: false`.
8. **Apply stale evidence:** Use `--max-age-seconds 3600` with old evidence. Assert: decision `quarantined`, reason mentions staleness, `state_changed: false`.
9. **Apply semantically EMPTY evidence (quality gate):** Bundle with `quality.verdict=EMPTY` (or missing `quality` and all-required-zero metrics — defensive recompute). Assert: decision `quarantined`, no confidence/readiness/trust/promotion mutation, reason cites empty substance.
10. **Show history / show:** `capability-evidence-history` lists all intakes with timestamps, decisions, confidence transitions; `capability-evidence-show <intake_id>` shows full detail (decision, reason, signals, fingerprint, linkage).
11. **Confirm rejected/quarantined/duplicate records do not mutate confidence:** accepted intakes produce confidence reports; others do not (`accepted_count == confidence_report_count`).
12. **Confirm audit artifacts are not a new registry:** only `report.json` + `pass_fail.json` per intake; no promotion registry, no doctrine layer, no independent durable state separate from `CapabilityConfidenceEngine`.
13. **Single-step ladder (BHV-036) + damped score (BHV-037):** the score is `ratio × n/(n+2)`, so an all-pass history climbs gradually — 1/1→0.3333 `low`, 2/2→0.5 `medium`, 3/3→0.6, 4/4→0.6667 (still `medium`), 5/5→0.7143 `high`/ready, 18/18→0.9 `very_high`. The ladder remains as a guard: no accepted application may raise the published level by more than one rung (on the damped curve `clamped` is rarely `true`). Drops are never clamped: from `high` (5/5), one FAIL (5/6 damped = 0.625) lands `medium` immediately with `clamped: false`. Quarantined/rejected/duplicate applications never advance the ladder, and the effective level round-trips the durable confidence store (persisted via `create(level_override=...)`).

### cli-validation-record

- **Dry run governance:** `--dry-run` on `docs/validation_plans/m4_execution_chain.json` resolves the argv and shows each command `[OK]` (safe) without executing; an unknown/unsafe command shows `[XX]` and the run exits non-zero.
- **M4 plan:** `--plan docs/validation_plans/m4_execution_chain.json` -> `Status: PASSED`, `1/1 passed`, bundle under `artifacts/validation_evidence/<run_id>/`.
- **M2 plan:** `--plan docs/validation_plans/m2_evidence_promotion.json --set evidence=<chain_evidence.json>` -> `Status: PASSED`, `2/2 passed`.
- **Bundle shape:** `validation_run.json`, `commands.json`, `environment.json`, `artifact_manifest.json` (sha256 per file), `assertion_results.json`, `plan_snapshot.json`, `report.md`, and per-command `commands/NN_<id>.stdout.txt`/`.stderr.txt`.
- **Failures first-class:** a failing command with `continue_on_failure=false` marks later commands `skipped`, sets run status `failed`, and exits 1; stdout/stderr/exit are still preserved.
- Generated bundles stay under git-ignored `artifacts/validation_evidence/`.

## Tests

Targeted: `tests/test_evidence_promotion.py`, `tests/test_evidence_quality.py`, `tests/test_evidence_summary.py`. Full pytest only at PR checkpoints.

## Notes / gotchas

- Failing evidence for synthetic tests: write `evidence.json` with `capability_id` in `references` + sibling `trace.json` with `status: "FAIL"`.
- Cumulative behavior: applying distinct evidence increments `execution_count`/`success_count`; exact duplicates do not.
- Tracked proof objects (attested→captured) come from the Local Runner `emit_evidence_summary` action → `artifacts/validation_runs/<summary_id>/evidence_summary.{json,md}` (committable; see `testing-local-runner`).
