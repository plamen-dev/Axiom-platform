---
name: testing-execution-chain
description: Verify the M4 execution-chain orchestrator (axiom execution-chain-run) — the Plan→Step→Attempt→Result→Artifact→Evidence→Report ID flow, persisted disk records, and evidence bundle shape. Use when testing execution-chain behavior or changes to the orchestrator/frameworks it links.
---

# Testing the execution chain (M4)

## Domain

The execution-chain orchestrator runs one deterministic capability through the full execution stack. Source: `src/axiom_core/execution_chain_orchestrator.py` plus the `execution_*` frameworks it links. Run CLI walkthroughs in the recordable terminal (see `testing-axiom-cli`) with shell-authoritative JSON checks alongside.

## Commands

- `axiom execution-chain-run --capability <id> [--artifacts-root <p>] [--json-output]`
- `axiom loop-run [--cycles <n>] [--artifacts-root <p>] [--json-output]` — bounded loop composing the chain: self-model gap analysis → work-queue → execution-chain-run → capability-evidence-apply → re-queue. Max 10 cycles; stops on the first chain failure; loop report at `artifacts/loop_runner/<loop_id>/report.json` links the real ids of every stage of every cycle (queue_report_id, chain_run_id + all 7 chain ids, intake_id, requeue_report_id).

## Registry pointers

- Command governance: `src/axiom_core/runner/command_registry.py` (READ classification, evidence outputs).
- Evidence quality verdicts: `src/axiom_core/evidence_quality.py` (`quality.verdict` stamped into `evidence.json`).

## Verification checklists

### M4 execution-chain-run CLI verification

1. **Run deterministic capability:** `poetry run axiom execution-chain-run --capability self-model-build --artifacts-root <art> --json-output > chain.json`
2. **Confirm all 7 IDs present:** ExecutionPlan, ExecutionStep, ExecutionAttempt, ExecutionResult, ExecutionArtifact, Evidence, ExecutionReport.
3. **Confirm ID-flow PASS:** `ID-flow status: PASS` in console output, `7/7` transitions `[OK]`.
4. **Confirm each downstream reference_value equals upstream ID:** Shell-authoritative: parse JSON, assert `downstream.reference_value == upstream.id` for all 7 transitions. Assert `ids_distinct: True`.
5. **Confirm terminal report resolves back through artifact/result/attempt/step/plan:** Read persisted disk records and verify the resolution chain from report back to plan.
6. **Confirm persisted disk records, not response-only records:** Load `report.json` from the artifacts directory and resolve IDs from persisted files, not just the in-memory orchestrator response.
7. **Distinguish runtime relationship proof from static import metrics:** The static analyzer's `declared_but_unwired_chains` may remain unchanged. The M4 proof is the runtime executable ID flow + disk resolution, not static import edges. Do NOT add direct `execution_*` imports merely to improve the static analyzer.

### Output shape

- All 7 chain IDs present in output (plan, step, attempt, result, artifact, evidence, report).
- `status: "PASS"` and `id_flow_status: "PASS"`.
- `transitions` array shows 7/7 `[OK]` with `reference_value == upstream_id` at each stage.
- `ids_distinct: true` (all 7 IDs are unique).
- Use `--artifacts-root /tmp/testdir/artifacts` for isolated test runs.
- Evidence file persisted at `artifacts/execution_chain/<run_id>/evidence.json` with `capability_id`, `result_id`, `artifact_id` in `references`, and a `quality` block (`verdict`/`required_metrics`/`zero_metrics`/`reason`).
- Trace file at `artifacts/execution_chain/<run_id>/trace.json` with `status`, `report_id`, `created_at`.
- `status=PASS` is the **ID-flow/plumbing verdict only**; substance lives in `quality.verdict` (SUBSTANTIVE/EMPTY/NOT_EVALUATED). A run can be PASS + EMPTY.

## Tests

Targeted: `tests/test_execution_chain_orchestrator.py`, `tests/test_evidence_quality.py`, `tests/test_loop_runner.py`. Full pytest only at PR checkpoints (tiering policy).

## Notes / gotchas

- On Windows, drive the CLI via `python -m poetry run axiom ...` (WDAC blocks bare exe shims).
- `self-model-build` requires `module_count > 0` for SUBSTANTIVE; a zero-module run stays PASS (plumbing) but stamps EMPTY.
