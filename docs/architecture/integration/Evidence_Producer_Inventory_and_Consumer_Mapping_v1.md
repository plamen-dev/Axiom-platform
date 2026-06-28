# Evidence Producer Inventory and Consumer Mapping v1

PR #154 | Date: 2026-06-23 | Owner: Program 1 (implementation) / Program 0 (sequencing)

---

## 1. Executive Summary

**Is the original "Model Health Evidence Consumer" target confirmed?**

**Partially confirmed.** `axiom_core.model_health` IS a confirmed evidence producer with
orphaned output (no state-mutating consumer). The EVID-001 gap finding from PR #144 is
accurate: `model_health` produces `axiom_model_health.json`, `axiom_capability_readiness.json`,
and related artifacts, but nothing reads these to change capability confidence, readiness state,
or promotion status.

However, `model_health` is **not the only orphaned producer**. This inventory identifies
**8 distinct evidence-producing tiers** and maps each to its current consumer status.
The `model_health` orphan is the one explicitly named by EVID-001, but at least 4 other
producers also lack state-mutating consumers. A "Model Health Evidence Consumer" PR would
close the specific EVID-001 finding but would not close the broader evidence-orphaning pattern.

**What PRs #147/#148/#153 already closed:**

| PR | What it closed |
|----|----------------|
| PR #147 | Narrow M2 slice of EVID-001: execution-chain `evidence.json` routed to `EvidencePromotionLoop` → `CapabilityConfidenceEngine`. Passing evidence raises confidence; failing evidence lowers it. |
| PR #148 | Hardened the M2 path: duplicate evidence is no longer double-counted; conflicting outcome signals are quarantined (no silent mutation). |
| PR #153 | Added `CLIValidationRecorder` — a new evidence producer for recording ordered CLI validation plans. Does NOT claim to close EVID-001; designed for traceability first, consumer path deferred. |

**What remains open:** `model_health` readiness output, `EvidenceRunner` validation bundles,
`SetParameterValue` evidence, `CapabilityRunner` execution bundles, `Discovery` evidence,
and `CLIValidationRecorder` bundles all lack a path to capability confidence/readiness state.

---

## 2. Evidence Producer Inventory

### Producer 1: ExecutionChainOrchestrator

| Field | Value |
|-------|-------|
| **Producer name** | `ExecutionChainOrchestrator` |
| **File/module** | `src/axiom_core/execution_chain_orchestrator.py` (826 lines) |
| **Command/CLI** | `axiom execution-chain-run --capability <id> [--artifacts-root <p>] [--json-output]` |
| **Artifacts produced** | `evidence.json`, `trace.json`, `self_model.json` |
| **Artifact location** | `artifacts/execution_chain/<run_id>/` |
| **Schema/shape** | `evidence.json`: `{evidence_id, references: {capability_id, result_id, artifact_id}, metrics, summary}` |
| **Identity fields** | `evidence_id` (UUID), `capability_id`, `result_id`, `artifact_id` |
| **Capability linkage** | `references.capability_id` (e.g. `self-model-build`) |
| **Current consumer** | `EvidencePromotionLoop.apply()` (PR #147) → `CapabilityConfidenceEngine` |
| **Missing consumer** | None — fully consumed |
| **Confidence/state effect** | Passing evidence raises confidence score/level; failing evidence lowers it |
| **EVID-001 status** | **CLOSED** (M2 slice) |

### Producer 2: EvidencePromotionLoop (intake records)

| Field | Value |
|-------|-------|
| **Producer name** | `EvidencePromotionLoop` |
| **File/module** | `src/axiom_core/evidence_promotion.py` (647 lines) |
| **Command/CLI** | `axiom capability-evidence-apply --evidence <path> [--capability <id>] [--json-output]` |
| **Artifacts produced** | `report.json`, `pass_fail.json` per intake |
| **Artifact location** | `artifacts/capability_evidence_intake/<intake_id>/` |
| **Schema/shape** | `report.json`: `{intake_id, evidence_path, capability_id, decision, state_changed, outcome, before, after, ...}` |
| **Identity fields** | `intake_id` (UUID), `capability_id`, `evidence_path` |
| **Capability linkage** | `capability_id` from evidence bundle or CLI override |
| **Current consumer** | IS the consumer for execution-chain evidence; writes to `CapabilityConfidenceEngine` |
| **Missing consumer** | None — intake records are audit artifacts, not meant for further consumption |
| **Confidence/state effect** | Mutates confidence via `CapabilityConfidenceEngine.create()` |
| **EVID-001 status** | N/A — this IS the consumer, not an orphaned producer |

### Producer 3: ModelHealth / execute_health_run

| Field | Value |
|-------|-------|
| **Producer name** | `ModelHealth` (`execute_health_run`) |
| **File/module** | `src/axiom_core/model_health.py` (685 lines) |
| **Command/CLI** | No direct CLI command; invoked from server tools / Revit adapter |
| **Artifacts produced** | `axiom_model_health.json`, `axiom_capability_readiness.json`, `axiom_environment_report.json`, `axiom_model_health.md` |
| **Artifact location** | `artifacts/runs/<run_id>/` (via run spine) |
| **Schema/shape** | `axiom_model_health.json`: `{generated_at_utc, revit_version, model_path, level_count, grid_count, warning_count, stale_status, ...}`. `axiom_capability_readiness.json`: `{generated_at_utc, capabilities: [{capability, ready, readiness_level, checks: [{check, passed, detail}]}]}` |
| **Identity fields** | `run_id` (from run spine), capability names in readiness array |
| **Capability linkage** | Per-capability `CapabilityReadiness` objects keyed by capability name |
| **Current consumer** | Read-only retrieval: `server_tools.axiom_model_health_get_latest()`, `server_tools.axiom_capability_readiness_get()` |
| **Missing consumer** | **No state-mutating consumer** — readiness assessments do not feed into `CapabilityConfidenceEngine`, `EvidencePromotionLoop`, or `CapabilityStateRegistry` |
| **Confidence/state effect** | None — output is orphaned |
| **EVID-001 status** | **OPEN** — this is the original EVID-001 finding |

### Producer 4: EvidenceRunner (Validation Evidence)

| Field | Value |
|-------|-------|
| **Producer name** | `EvidenceRunner` |
| **File/module** | `src/axiom_core/validation/evidence_runner.py` (531 lines) |
| **Command/CLI** | `axiom validation-run --validation <name> [--json-output]` |
| **Artifacts produced** | `validation_request.json`, `validation_result.json`, `validation_summary.md`, `pass_fail.json`, `command_outputs/` |
| **Artifact location** | `artifacts/validation_evidence/<validation>/<evr_id>/` |
| **Schema/shape** | `pass_fail.json`: `{validation_name, outcome, passed, exit_code, checks_passed, checks_total, checks: [...]}` |
| **Identity fields** | `evr_id` (UUID), `validation_name` |
| **Capability linkage** | Indirect — validation name maps to a capability via `ValidationRegistry` |
| **Current consumer** | `CapabilityStateRegistry` scans `artifacts/validation_evidence/` for lifecycle state derivation; `FailureClassificationEngine` reads `pass_fail.json` for classification |
| **Missing consumer** | **No confidence/readiness consumer** — validation pass/fail does not feed into `EvidencePromotionLoop` or `CapabilityConfidenceEngine` |
| **Confidence/state effect** | None (state lifecycle only — `validated`/`failed` status, no confidence score) |
| **EVID-001 status** | **PARTIALLY CONSUMED** — lifecycle state scanned, but no confidence path |

### Producer 5: CapabilityRunner (Capability Execution Evidence)

| Field | Value |
|-------|-------|
| **Producer name** | `CapabilityRunner` |
| **File/module** | `src/axiom_core/runner/capability_runner.py` |
| **Command/CLI** | `axiom capability-run --capability <name> [--json-output]` |
| **Artifacts produced** | `capability_request.json`, `capability_result.json`, `capability_summary.md`, `pass_fail.json`, `command_outputs/` |
| **Artifact location** | `artifacts/capability_runs/<capability>/<run_id>/` |
| **Schema/shape** | `pass_fail.json`: `{capability_name, outcome, passed, exit_code, checks_passed, checks_total, checks: [...]}` |
| **Identity fields** | `run_id`, `capability_name` |
| **Capability linkage** | Direct — keyed by `capability_name` |
| **Current consumer** | `CapabilityStateRegistry` scans `artifacts/capability_runs/` for lifecycle state; `FailureClassificationEngine` reads `pass_fail.json` |
| **Missing consumer** | **No confidence/readiness consumer** — execution pass/fail does not feed into `EvidencePromotionLoop` or `CapabilityConfidenceEngine` |
| **Confidence/state effect** | None (state lifecycle only) |
| **EVID-001 status** | **PARTIALLY CONSUMED** — lifecycle state scanned, but no confidence path |

### Producer 6: CLIValidationRecorder

| Field | Value |
|-------|-------|
| **Producer name** | `CLIValidationRecorder` |
| **File/module** | `src/axiom_core/validation/cli_validation_recorder.py` (PR #153) |
| **Command/CLI** | `axiom cli-validation-record --plan <path> [--artifacts-root <p>] [--name <n>] [--dry-run] [--json-output]` |
| **Artifacts produced** | `validation_run.json`, `commands.json`, `environment.json`, `artifact_manifest.json`, `assertion_results.json`, `plan_snapshot.json`, `report.md`, per-command `stdout`/`stderr` |
| **Artifact location** | `artifacts/validation_evidence/<run_id>/` |
| **Schema/shape** | `validation_run.json`: `{run_id, name, status, total, passed, failed, skipped, started_at, completed_at, duration_seconds}` |
| **Identity fields** | `run_id` (UUID), plan `name` |
| **Capability linkage** | Indirect — plan steps reference CLI commands that map to capabilities |
| **Current consumer** | None — durable evidence bundles for traceability |
| **Missing consumer** | **No state-mutating consumer** — validation results do not feed into confidence or state |
| **Confidence/state effect** | None |
| **EVID-001 status** | **OPEN** — new producer (PR #153), consumer path deferred by design |

### Producer 7: SetParameterValue

| Field | Value |
|-------|-------|
| **Producer name** | `SetParameterValue.write_evidence()` |
| **File/module** | `src/axiom_core/set_parameter_value.py` (654 lines) |
| **Command/CLI** | `axiom set-parameter-value --prompt <p> [--mode preview|apply]` |
| **Artifacts produced** | `request.json`, `preview.json`, `changes.json` (apply mode), `result_summary.md` |
| **Artifact location** | `artifacts/parameter_edit_runs/<run_id>/` |
| **Schema/shape** | `preview.json`: `{run_id, mode, status, category, parameter_name, requested_value, element_count, model_modified, ...}` |
| **Identity fields** | `run_id`, `category`, `parameter_name` |
| **Capability linkage** | Direct — `SetParameterValue` capability |
| **Current consumer** | `ValidationLoop` scans `parameter_edit_runs/` for the SPV validation loop |
| **Missing consumer** | **No confidence/readiness consumer** |
| **Confidence/state effect** | None |
| **EVID-001 status** | **PARTIALLY CONSUMED** — validation loop scans, no confidence path |

### Producer 8: Discovery Reports

| Field | Value |
|-------|-------|
| **Producer name** | `discovery.reports` |
| **File/module** | `src/axiom_core/discovery/reports.py` (203 lines) |
| **Command/CLI** | `axiom inventory-model [--simulate]` |
| **Artifacts produced** | `categories.csv`, `parameters.csv`, `candidate_capabilities.csv`, `discovery_evidence.jsonl`, `summary.json`, `summary.md` |
| **Artifact location** | `artifacts/discovery_runs/<run_id>/` |
| **Schema/shape** | `summary.json`: `{run_id, adapter, mode, source_model, scan_mode, ...}`. JSONL: per-evidence records |
| **Identity fields** | `run_id`, `adapter`, `scan_mode` |
| **Capability linkage** | `candidate_capabilities.csv` lists discovered capability candidates |
| **Current consumer** | `CapabilityStateRegistry` can ingest discovered candidates from SQLite session |
| **Missing consumer** | **No confidence/readiness consumer** — discovery results inform candidates but do not feed confidence |
| **Confidence/state effect** | None |
| **EVID-001 status** | **PARTIALLY CONSUMED** — candidate state lifecycle, no confidence path |

### Producer 9: CapabilityConfidenceEngine (terminal producer)

| Field | Value |
|-------|-------|
| **Producer name** | `CapabilityConfidenceEngine` |
| **File/module** | `src/axiom_core/capability_confidence.py` |
| **Command/CLI** | Internal — called by `EvidencePromotionLoop` |
| **Artifacts produced** | `report.json`, `pass_fail.json` per confidence measurement |
| **Artifact location** | `artifacts/capability_confidence/<report_id>/` |
| **Identity fields** | `report_id`, `capability_id`, `evidence_id` |
| **Current consumer** | IS the terminal state store |
| **Missing consumer** | None — this is where evidence arrives and state is stored |
| **EVID-001 status** | N/A — terminal consumer, not orphaned |

### Tier 2 — Framework Engines with write_evidence (audit/traceability only)

Approximately **70+ framework engines** (e.g. `execution_plan.py`, `execution_step.py`,
`execution_attempt_v2.py`, `execution_result.py`, `execution_artifact.py`,
`execution_report.py`, `session_state_machine.py`, `session_plan_registry.py`,
`session_question_registry.py`, `coding_session_registry.py`, `capability_summary.py`,
`capability_knowledge_graph.py`, `capability_event_timeline.py`, `conflict_registry.py`,
`repair_decision_registry.py`, `repair_proposal_registry.py`, `escalation_registry.py`,
`assertion_registry.py`, `devin_session_import.py`, `github_metadata_import.py`,
`test_selection_engine.py`, `regression_test_generator.py`, `patch_impact_analyzer.py`,
`code_review_policy.py`, etc.) each have a `write_evidence()` method.

These are **internal framework state/audit bundles** — they record the state of framework
objects for traceability, not capability validation outcomes. They are NOT evidence producers
in the EVID-001 sense. Their output is consumed implicitly by their own framework's `list()`
/ `get()` methods and by the knowledge graph's module-relationship edges.

**These do not require consumer paths for EVID-001 closure.**

---

## 3. Consumer Mapping

```
Producer                → Artifact                       → Identity              → Current Consumer                    → Missing Consumer              → Status
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
ExecutionChainOrch.     → evidence.json + trace.json     → capability_id, UUID   → EvidencePromotionLoop → ConfEngine  → None                          → CLOSED
EvidencePromotionLoop   → intake report.json             → intake_id, cap_id     → IS the consumer (audit output)      → None                          → N/A
ModelHealth             → axiom_model_health.json +      → run_id, cap names     → Read-only: server_tools helpers     → NO state-mutating consumer    → OPEN
                          axiom_capability_readiness.json
EvidenceRunner          → pass_fail.json + result.json   → evr_id, val_name      → CapStateReg (lifecycle) + FailClass → NO confidence consumer        → PARTIAL
CapabilityRunner        → pass_fail.json + result.json   → run_id, cap_name      → CapStateReg (lifecycle) + FailClass → NO confidence consumer        → PARTIAL
CLIValidationRecorder   → validation_run.json + etc.     → run_id, plan name     → None                               → NO consumer (by design)       → OPEN
SetParameterValue       → preview.json + changes.json    → run_id, cat/param     → ValidationLoop (SPV loop)           → NO confidence consumer        → PARTIAL
Discovery Reports       → discovery_evidence.jsonl       → run_id, adapter       → CapStateReg (candidate ingest)      → NO confidence consumer        → PARTIAL
CapabilityConfidence    → report.json (terminal)         → report_id, cap_id     → Terminal state store                → None                          → TERMINAL
```

---

## 4. EVID-001 Status

### What EVID-001 is

EVID-001 (`artifact_or_evidence_producers_without_consumers`) was identified in
PR #144's self-model gap analysis. The specific finding: `axiom_core.model_health`
produces evidence/readiness output but has **no visible downstream consumer** in
the self-model. Evidence is preserved but does not change capability state,
readiness, confidence, or promotion.

### What is closed

| PR | Scope closed | Evidence |
|----|-------------|----------|
| PR #147 | **Narrow M2 slice**: execution-chain `evidence.json` → `EvidencePromotionLoop` → `CapabilityConfidenceEngine`. Passing evidence raises confidence; failing lowers it. Identity linked via `capability_id`. | `tests/test_evidence_promotion.py`: H1-H5 green; before/after confidence assertion. Ledger BHV-026. |
| PR #148 | **Hardening of M2 slice**: duplicate evidence fingerprinting (no double-count); conflicting outcome signals quarantined (no silent resolution). | `tests/test_evidence_promotion.py`: duplicate/conflict/accumulation tests. Ledger BHV-027. |

### What is NOT closed

| Orphaned Producer | Artifact | Why it's orphaned | Severity |
|-------------------|----------|-------------------|----------|
| `model_health` | `axiom_capability_readiness.json` | Readiness assessments not consumed by confidence/promotion | **High** — explicitly named by EVID-001 |
| `EvidenceRunner` | `pass_fail.json` | Validation pass/fail not fed to confidence | Medium — lifecycle state consumed, confidence gap only |
| `CapabilityRunner` | `pass_fail.json` | Execution pass/fail not fed to confidence | Medium — same pattern as EvidenceRunner |
| `CLIValidationRecorder` | `validation_run.json` | No consumer at all | Low — by design (traceability first, PR #153) |
| `SetParameterValue` | `preview.json`/`changes.json` | Not fed to confidence | Low — SPV validation loop consumes partially |
| `Discovery` | `discovery_evidence.jsonl` | Discovery results not fed to confidence | Low — candidate state consumed |

### Honest EVID-001 closure assessment

**EVID-001 is NOT fully closed.** It is closed for the narrow M2 execution-chain slice only.
The original finding was about `model_health`, which remains orphaned. Full EVID-001 closure
requires at minimum: `model_health` readiness output gaining a state-mutating consumer path
and a re-run of gap analysis confirming it.

The broader evidence-orphaning pattern (Producers 4-8 above) is a **separate concern** from
EVID-001 specifically, because EVID-001 named `model_health` specifically. However, the same
class of gap (`artifact_or_evidence_producers_without_consumers`) applies to them.

---

## 5. Candidate Next Implementation PRs

### Candidate A: Model Health Evidence Consumer

| Field | Assessment |
|-------|-----------|
| **Why** | Directly closes the named EVID-001 finding. `model_health` readiness output has a natural shape compatible with `CapabilityConfidenceFactors`. |
| **Prerequisite** | Decide whether readiness assessments map to confidence factors (likely yes: `CapabilityReadiness.checks` → factor inputs) or to `CapabilityValidationKnowledgeEngine` entries (traceability). The existing `EvidencePromotionLoop.apply()` expects `evidence.json` with a `capability_id` and determinable pass/fail — `model_health` readiness has both (per-capability `ready` boolean + `readiness_level`). |
| **Risk** | Medium. The `EvidencePromotionLoop` was built for execution-chain evidence bundles with a specific schema (`evidence.json` with `references.capability_id` + sibling `trace.json`). Model health's per-capability readiness format differs — either a thin adapter is needed, or `EvidencePromotionLoop` must accept readiness bundles. The adapter approach is smaller and lower risk. |
| **Owner program** | Program 1 (implementation), Program 0 (approval) |
| **Type** | Implementation (small adapter + tests) |
| **Priority** | **1st** — closes the named finding |

### Candidate B: Validation/Execution Evidence → Confidence Adapter

| Field | Assessment |
|-------|-----------|
| **Why** | `EvidenceRunner` and `CapabilityRunner` both produce `pass_fail.json` with `capability_name`/`validation_name` and `passed` boolean — structurally identical to what `EvidencePromotionLoop` needs. Connecting them would mean every validation-run and capability-run outcome feeds confidence. |
| **Prerequisite** | Candidate A (model health) should be proven first to validate the adapter pattern. Also need to confirm that automated validation/capability runs should actually affect confidence — this may be a doctrine question (Program 6). |
| **Risk** | Medium-high. Connecting every validation-run to confidence could cause rapid confidence oscillation if validations are run frequently. May need a doctrine decision on which evidence types affect confidence. |
| **Owner program** | Program 1 (implementation), Program 6 (doctrine approval) |
| **Type** | Implementation (after doctrine decision) |
| **Priority** | **2nd** — broader than model health, needs doctrine input |

### Candidate C: Capability Validation Knowledge Population

| Field | Assessment |
|-------|-----------|
| **Why** | `CapabilityValidationKnowledgeEngine` already accepts validation records, findings, and artifacts. Evidence from `EvidenceRunner`, `CapabilityRunner`, and `CLIValidationRecorder` could be routed there for durable knowledge aggregation. |
| **Prerequisite** | None technically — the engine API exists. But this is traceability/knowledge, not confidence/state mutation. It would populate validation history but not close EVID-001 (which requires state-mutating consumption). |
| **Risk** | Low. Append-only engine, no state mutation risk. |
| **Owner program** | Program 1 |
| **Type** | Implementation |
| **Priority** | **3rd** — useful but orthogonal to EVID-001 |

### Candidate D: pass_fail.json Universal Evidence Adapter

| Field | Assessment |
|-------|-----------|
| **Why** | Every evidence producer that writes `pass_fail.json` (EvidenceRunner, CapabilityRunner, CapabilityConfidenceEngine, EvidencePromotionLoop) could have a single adapter that reads `pass_fail.json` + infers capability identity and routes to `EvidencePromotionLoop`. |
| **Prerequisite** | Candidate A (prove the adapter pattern with model_health first). Doctrine decision on which `pass_fail.json` types affect confidence. |
| **Risk** | Medium — `pass_fail.json` schemas vary slightly across producers. |
| **Owner program** | Program 1 (implementation), Program 6 (doctrine) |
| **Type** | Implementation (after Candidates A and B) |
| **Priority** | **4th** — generalization after specific adapters are proven |

### Candidate E: Runtime Relationship Awareness First

| Field | Assessment |
|-------|-----------|
| **Why** | Instead of wiring individual producer→consumer paths, instrument the self-model gap analysis to detect orphaned producers automatically and recommend consumer targets. |
| **Prerequisite** | The gap analysis already does this (gap type `artifact_or_evidence_producers_without_consumers`). What's missing is a re-run mechanism that validates closure claims. |
| **Risk** | Low — analysis/docs only. |
| **Owner program** | Program 1 |
| **Type** | Investigation/docs |
| **Priority** | **5th** — improves detection but doesn't close gaps |

### Candidate F: No Implementation Yet

| Field | Assessment |
|-------|-----------|
| **Why** | The evidence-producer inventory may be sufficient for now. EVID-001 is documented, the orphans are identified, and doctrine questions remain open. |
| **Prerequisite** | None |
| **Risk** | Low — but EVID-001 stays open indefinitely |
| **Owner program** | Program 0 (decision) |
| **Type** | N/A |
| **Priority** | Not recommended unless doctrine is blocked |

---

## 6. Recommendation

**Recommended next implementation PR: Candidate A — Model Health Evidence Consumer.**

Rationale:
1. It directly closes the named EVID-001 finding.
2. The producer (`model_health.py`) and terminal consumer (`CapabilityConfidenceEngine`)
   both already exist and are well-tested.
3. The adapter is small: read `axiom_capability_readiness.json`, extract per-capability
   `ready`/`readiness_level`/`checks`, derive `CapabilityConfidenceFactors`, and call
   `EvidencePromotionLoop.apply()` or `CapabilityConfidenceEngine.create()` directly.
4. The pattern proven here can then be reused for Candidates B-D.
5. No doctrine decision is needed for this specific case — `model_health` readiness is
   a deterministic assessment of whether the environment supports a capability, which
   is a direct input to confidence.

**Implementation scope estimate:** ~200-300 lines of adapter code + ~150-200 lines of tests.
No new framework, registry, or object family. Reuses `EvidencePromotionLoop` or calls
`CapabilityConfidenceEngine` directly (whichever is semantically correct — readiness vs.
execution evidence may warrant direct confidence creation rather than routing through the
execution-chain promotion path).

**Prerequisite for implementation:** Program 0 approval of this inventory and confirmation
that the model-health → confidence path is the approved next step.

---

## 7. Non-Goals

- No new evidence framework.
- No new registry.
- No promotion doctrine (doctrine routed to Program 6).
- No implementation-worker behavior.
- No retry loop.
- No GPR/global PR registry.
- No canonical knowledge base rewrite.
- No Revit live validation.
- No broad refactor.
- No confidence math changes in this inventory PR.
- No evidence-promotion semantic changes in this inventory PR.
- No execution-chain ID-flow changes in this inventory PR.
