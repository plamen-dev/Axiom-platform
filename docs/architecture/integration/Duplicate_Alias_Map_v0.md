# Duplicate / Alias Map v0

Concept clusters that may represent the same or overlapping functions within the
Axiom codebase. Seeded from direct repo inspection of source modules, schemas,
CLI commands, and architecture docs.

Last updated: PR #157 (Axiom Context Preflight, PR Purpose Map, and Live System Atlas v0).
Clusters 10–12 added by the required old-foundation scan (pipe/spine/bridge/MCP/agents).

---

## Cluster 1: Job / Plan / Task Packet / Work Item / Work Queue

| Field | Value |
|-------|-------|
| **Names / aliases** | Job, NormalizedJob, Plan, ToolStep, WorkItem, WorkQueue, WorkPrioritization, WorkDependency, WorkItemRegistry, TaskPacket (referenced in docs/task-spec language, not implemented as runtime), SessionPlan, SessionTaskGraph |
| **Likely overlap** | Job/Plan/ToolStep (schemas.py) is the older prompt→plan→step pipeline. WorkItem/WorkQueue/WorkPrioritization is the newer autonomous-engineering backlog. SessionTaskGraph/SessionPlan tracks session-level planning. All represent "what should be done." |
| **Known distinct responsibilities** | `NormalizedJob` is input normalization from Excel/prompts. `Plan`/`ToolStep` is Revit execution planning with MCP bridge steps. `WorkItem`/`WorkQueue` is autonomous capability backlog. `SessionTaskGraph` is session-scope dependency graph. |
| **Active files** | `src/axiom_core/schemas.py` (Job, Plan, ToolStep), `src/axiom_core/work_queue.py`, `src/axiom_core/work_item_registry.py`, `src/axiom_core/work_prioritization.py`, `src/axiom_core/work_dependency.py`, `src/axiom_core/session_task_graph.py`, `src/axiom_core/session_plan_registry.py` |
| **Risk of duplication** | Medium. Three parallel "what to do" models exist. Future task-packet or work-dispatch features must choose one or add an adapter, not a fourth model. |
| **Rule for future PRs** | Check all three families before adding any new task/work/plan model. If a "task packet consumer" is built, it should consume through one of these, not create a new model. |
| **Status** | needs reconciliation |

---

## Cluster 2: Orchestrator / Execution-Chain / Runner / Worker

| Field | Value |
|-------|-------|
| **Names / aliases** | Orchestrator, PlanTemplate, ExecutionChainOrchestrator, CodingSessionOrchestrator, ControlledValidationOrchestrator, CodeValidationOrchestrator, OrchestratorAgent, Local Runner, CapabilityRunner, EvidenceRunner, PatchApplicationRunner, LiveCodingTrialRunner, ParserCodingTrialRunner, Worker (referenced in docs as "implementation-worker" — not a runtime class) |
| **Likely overlap** | Multiple "orchestrate something" classes. The original `Orchestrator` converts Jobs→Plans→MCP execution. `ExecutionChainOrchestrator` drives the 7-stage ID-flow chain. `CodingSessionOrchestrator` manages coding sessions. `ControlledValidationOrchestrator` runs approved validation requests. Each has a distinct scope but the naming pattern is similar. |
| **Known distinct responsibilities** | `Orchestrator` = job/plan/MCP bridge (Revit execution). `ExecutionChainOrchestrator` = M4 evidence chain. `Local Runner` = allowlisted shell command harness. `CapabilityRunner` = capability execution with run-spine. `EvidenceRunner` = 3 fixed in-process validations. `CodingSessionOrchestrator` = autonomous coding session management. |
| **Active files** | `src/axiom_core/orchestrator.py`, `src/axiom_core/execution_chain_orchestrator.py`, `src/axiom_core/coding_session_orchestrator.py`, `src/axiom_core/validation_orchestrator.py`, `src/axiom_core/code_validation.py`, `tools/local_runner/local_runner.py`, `src/axiom_core/runner/capability_runner.py`, `src/axiom_core/validation/evidence_runner.py` |
| **Risk of duplication** | High. Any new "runner" or "orchestrator" will look like a 7th+ variant. |
| **Rule for future PRs** | Before adding a new orchestrator/runner, confirm none of the existing ones can be extended or composed. The M4 chain orchestrator is the proven execution path; new runtime orchestration should coordinate through it or justify why not. |
| **Status** | accepted distinct (each has a clear scope, but naming overlap is confusing) |

---

## Cluster 3: Local Runner / CLI Validation Recorder / Command Registry / Shell Execution

| Field | Value |
|-------|-------|
| **Names / aliases** | Local Runner, CLIValidationRecorder, CommandRegistry, runner-commands (CLI), cli-validation-record (CLI), local-runner (CLI) |
| **Likely overlap** | All three execute shell commands under governance. Local Runner is the security harness. CommandRegistry is the policy catalog. CLIValidationRecorder runs plans of allowlisted commands. |
| **Known distinct responsibilities** | `Local Runner` = lowest-level subprocess executor with workspace policy. `CommandRegistry` = static catalog (safety classification, timeouts, evidence outputs). `CLIValidationRecorder` = plan-driven evidence-producing test runner using CommandRegistry for governance. |
| **Active files** | `tools/local_runner/local_runner.py`, `src/axiom_core/runner/command_registry.py`, `src/axiom_core/validation/cli_validation_recorder.py` |
| **Risk of duplication** | Low if governance is respected. Risk rises if a new "shell executor" bypasses CommandRegistry. |
| **Rule for future PRs** | All shell command execution must go through CommandRegistry governance. New execution harnesses should compose Local Runner + CommandRegistry, not duplicate them. |
| **Status** | accepted distinct |

---

## Cluster 4: ExecutionTrace / QAReport / Validation Bundle / Evidence Bundle / pass_fail Report

| Field | Value |
|-------|-------|
| **Names / aliases** | ExecutionTrace (referenced in schemas as future), QAReport (schemas.py), validation_run.json, evidence.json, trace.json, report.json, pass_fail.json, chain_evidence.json, axiom_capability_readiness.json, artifact_manifest.json |
| **Likely overlap** | Multiple "execution result" artifact formats. QAReport is the older Revit execution report. Evidence bundles are the newer M2/M4 format. Validation bundles are from CLIValidationRecorder. All represent "what happened and was it correct." |
| **Known distinct responsibilities** | `QAReport` = Revit plan execution quality assessment (violations, anomalies). `evidence.json`/`trace.json` = M4 execution chain output. `report.json`/`pass_fail.json` = per-engine intake convention (evidence promotion, model health). `validation_run.json` = CLI validation recorder output. `axiom_capability_readiness.json` = Model Health readiness snapshot. |
| **Active files** | `src/axiom_core/schemas.py` (QAReport), `src/axiom_core/execution_chain_orchestrator.py`, `src/axiom_core/evidence_promotion.py`, `src/axiom_core/model_health_evidence.py`, `src/axiom_core/validation/cli_validation_recorder.py` |
| **Risk of duplication** | Medium. New evidence/report formats may emerge without reconciling with existing conventions. |
| **Rule for future PRs** | New evidence-producing components should follow the `report.json` + `pass_fail.json` convention. New artifact formats should be documented in the Evidence Producer Inventory (PR #154). |
| **Status** | needs reconciliation (artifact schema unification is a potential future PR) |

---

## Cluster 5: EvidencePromotionLoop / ModelHealthReadinessConsumer / CLI Validation Recorder Consumer Gap

| Field | Value |
|-------|-------|
| **Names / aliases** | EvidencePromotionLoop, ModelHealthReadinessConsumer, CLIValidationRecorder (producer only — no consumer), CapabilityConfidenceEngine (terminal state mutator) |
| **Likely overlap** | All are evidence consumers or producer-consumer pairs. The pattern is: artifact → validate → dedup → accept/quarantine/reject → state effect (or no state effect). |
| **Known distinct responsibilities** | `EvidencePromotionLoop` consumes M4 execution evidence → mutates confidence. `ModelHealthReadinessConsumer` consumes readiness snapshots → intake records only (confidence_mutated=false). `CLIValidationRecorder` produces validation bundles but has no consumer (traceability-first by design). |
| **Active files** | `src/axiom_core/evidence_promotion.py`, `src/axiom_core/model_health_evidence.py`, `src/axiom_core/validation/cli_validation_recorder.py`, `src/axiom_core/capability_confidence.py` |
| **Risk of duplication** | Low — each consumes a distinct artifact type. Risk is a future "universal evidence consumer" that reimplements the validate/dedup/quarantine pattern instead of extracting the shared pattern. |
| **Rule for future PRs** | New evidence consumers should reuse the validate → dedup → quarantine convention. A CLIValidationRecorder consumer is a known open gap but deferred intentionally. |
| **Status** | accepted distinct (shared pattern could be extracted as adapter seam in future) |

---

## Cluster 6: Capability State / Readiness / Confidence / Model Health Readiness

| Field | Value |
|-------|-------|
| **Names / aliases** | CapabilityConfidenceEngine, CapabilityConfidenceLevel, CapabilityConfidenceFactors, ModelHealth (readiness), axiom_capability_readiness.json, ModelHealthReadinessConsumer, capability_state_registry (referenced in overlap guardrails but not a standalone module — confidence IS the state), readiness labels (READY/WARNING/BLOCKED/UNKNOWN), confidence levels (very_low..very_high) |
| **Likely overlap** | "Readiness" (precondition assessment) and "confidence" (execution-derived score) are semantically distinct but both describe "how trustworthy is this capability." Without doctrine, they could drift toward measuring the same thing differently. |
| **Known distinct responsibilities** | `CapabilityConfidenceEngine` = execution-derived score from pass/fail history. `Model Health readiness` = precondition check (can the capability run against the current model?). `ModelHealthReadinessConsumer` = intake recorder for readiness (does NOT feed confidence). |
| **Active files** | `src/axiom_core/capability_confidence.py`, `src/axiom_core/model_health.py`, `src/axiom_core/model_health_evidence.py` |
| **Risk of duplication** | Medium. Whether readiness should ever influence confidence is an open Program 6 doctrine question. Without a decision, a future PR might build a readiness→confidence bridge that the current architecture explicitly defers. |
| **Rule for future PRs** | Do NOT route readiness into confidence without a Program 6 doctrine decision. confidence_mutated must remain false for readiness intake until that decision is made. |
| **Status** | accepted distinct (pending Program 6 doctrine) |

---

## Cluster 7: Failure Classification / Recovery Recommendation / Retry Executor

| Field | Value |
|-------|-------|
| **Names / aliases** | FailureClassificationFramework, CapabilityFailure, RecoveryRecommendation, RecoveryExecution, runner.failure_classification, FailureType/Category/Severity, RecoveryRecommendationType, RecoveryExecutionType |
| **Likely overlap** | Two failure classification modules exist: `failure_classification_framework.py` (Execution Outcome → failure → type/category/severity) and `runner/failure_classification.py` (runner-level failure analysis). `CapabilityFailure` is the older per-capability failure tracker. Recovery forms a chain: failure → recommendation → execution. |
| **Known distinct responsibilities** | `failure_classification_framework.py` = classify execution outcome failures with evidence bundles. `runner/failure_classification.py` = runner command-level failure policy. `capability_failure.py` = per-capability failure tracking with counts. `recovery_recommendation.py` = what should be done. `recovery_execution.py` = what was attempted. |
| **Active files** | `src/axiom_core/failure_classification_framework.py`, `src/axiom_core/capability_failure.py`, `src/axiom_core/recovery_recommendation.py`, `src/axiom_core/recovery_execution.py`, `src/axiom_core/runner/failure_classification.py` |
| **Risk of duplication** | Medium. Two failure classification modules with overlapping purpose. |
| **Rule for future PRs** | Before adding retry/recovery logic, check both failure classifiers and the recovery chain. Do not build a parallel retry engine. |
| **Status** | needs reconciliation (two failure classification paths) |

---

## Cluster 8: Canonical KB / Impact Ledger / Behavior-Change Ledger / PR-Review Ledger / Context Pack

| Field | Value |
|-------|-------|
| **Names / aliases** | docs/canonical_knowledge_base/ (00–60), impact_ledger/ (CIL clusters), behavior-change-ledger.md, pr-review-ledger.md, docs/runbooks/, docs/architecture/integration/, axiom-doctrine.md, Context Basis template, Context Pack, PR Purpose Map, Duplicate/Alias Map |
| **Likely overlap** | Multiple "what does Axiom know about itself" documents. The canonical KB (PR #152) is the durable seed. The impact ledger (PR #155) is cross-program reconciliation. The behavior-change ledger is runtime behavior history. The PR-review ledger is PR audit history. Integration docs are per-milestone analysis. |
| **Known distinct responsibilities** | Canonical KB = stable organizational context. Impact ledger = cross-program impact flags. Behavior-change ledger = runtime behavior history (BHV entries). PR-review ledger = PR audit trail. Runbooks = operational procedures. Integration docs = milestone validation packets and inventories. Context Basis template = per-PR preflight output. |
| **Active files** | `docs/canonical_knowledge_base/`, `docs/logs/behavior-change-ledger.md`, `docs/logs/pr-review-ledger.md`, `docs/runbooks/`, `docs/architecture/integration/`, `docs/architecture/axiom-doctrine.md` |
| **Risk of duplication** | Medium. Adding a new "context" or "knowledge" document without checking existing ones could create a parallel source of truth. |
| **Rule for future PRs** | Run context-preflight before adding any new docs under docs/. Check canonical KB, impact ledger, integration docs, and this map before creating new context/knowledge/reconciliation documents. |
| **Status** | accepted distinct (clear ownership boundaries per PR/program) |

---

## Cluster 9: DeepWiki / Static Docs / Generated Live Maps

| Field | Value |
|-------|-------|
| **Names / aliases** | DeepWiki (external/generated wiki showing platform overview), docs/architecture/ (static design docs), context_preflight.json/.md (generated live), system_atlas.json/.md (generated live), PR Purpose Map (tracked static), Duplicate/Alias Map (tracked static) |
| **Likely overlap** | DeepWiki provides an older overview of the job/plan pipeline, prompt execution flow, and orchestration layers. The context-preflight and system atlas provide a newer, repo-derived live map. Static docs provide per-component design specs. |
| **Known distinct responsibilities** | DeepWiki = external platform (not in-repo; reflects an older snapshot). Static docs = manually maintained design specs. Generated live maps = `artifacts/context_preflight/` output reflecting current repo state. Tracked reference docs = curated reconciliation documents (PR Purpose Map, Duplicate/Alias Map) that are committed and versioned. |
| **Active files** | No DeepWiki source files found in repo (external service). `docs/architecture/` (static). `artifacts/context_preflight/` (generated, gitignored). `docs/architecture/integration/PR_Purpose_Map_v0.md`, `docs/architecture/integration/Duplicate_Alias_Map_v0.md` (tracked). |
| **Risk of duplication** | Low if the distinction between live-generated (gitignored) and tracked-static (committed) is maintained. Risk rises if someone creates a new static "system map" doc that duplicates what context-preflight generates dynamically. |
| **Rule for future PRs** | For current repo state, use `axiom context-preflight` (generated). For curated references, update the tracked docs in `docs/architecture/integration/`. Do not create static copies of what should be generated. |
| **Status** | accepted distinct |

---

## Cluster 10: Revit Execution Boundary — MCP Layer / Automation Bridge / Pipe Client / Pipe Server / Revit Bridge

| Field | Value |
|-------|-------|
| **Names / aliases** | MCPLayer, MCP layer, AutomationBridge, automation bridge, PipeClient, pipe client, named pipe, AxiomPipeServer, PromptDispatcher (C#), PromptCommand, Revit bridge |
| **Likely overlap** | All describe "how Axiom reaches Revit to execute a tool." `MCPLayer` is a **mock** protocol boundary (simulates tool execution). The **real** path is the named-pipe bridge: Python `PipeClient` → in-Revit `AxiomPipeServer` → `PromptDispatcher`/ToolRegistry → Revit capability. `AutomationBridge` wraps `PipeClient` with a non-interactive driver + durable evidence. |
| **Known distinct responsibilities** | `MCPLayer` = mock tool-protocol/catalog boundary (off-Revit simulation). `PipeClient` = JSON-RPC named-pipe transport (Python side). `AxiomPipeServer` = pipe host (C#, in Revit). `PromptDispatcher` = C# prompt→capability router (in-Revit counterpart of Python `prompt_resolver`). `AutomationBridge` = autonomy driver + bridge evidence over `PipeClient`. |
| **Active files** | `src/axiom_core/mcp_layer.py`, `src/axiom_core/automation_bridge.py`, `src/axiom_core/pipe_client.py`, `src/axiom_revit/Axiom.Core/Bridge/AxiomPipeServer.cs`, `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs`, `src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs` |
| **Risk of duplication** | **High.** `MCPLayer` (mock) and the pipe bridge (real) are two representations of the same "Revit execution boundary." A future "task packet consumer" or "local worker loop" that sends work to Revit would be a THIRD path unless it reconciles here. |
| **Rule for future PRs** | Before building any new Revit-execution dispatch (worker loop, task-packet executor, retry-driven dispatch), reuse `AutomationBridge`/`PipeClient` (real transport) or decide explicitly whether `MCPLayer` should become the real boundary. Do not invent a new transport. The mock-MCP ↔ real-pipe adapter seam is unresolved. |
| **Status** | needs reconciliation — **adapter seam needed** (mock MCPLayer vs real pipe bridge) |

---

## Cluster 11: Execution Record / Run Spine / ExecutionTrace / QA Report / Evidence & Validation Bundles

| Field | Value |
|-------|-------|
| **Names / aliases** | run_spine (RunMetadata, AuditEntry, artifact_manifest.json, run_summary.md), ExecutionTrace (persistence), QAReport (schemas), ExecutionReport (chain), evidence.json/trace.json, validation_run.json, pass_fail.json, chain_evidence.json |
| **Likely overlap** | Several layers each record "what happened during a run." `Run Spine` = run identity + standard artifact folder + audit log (cross-cutting backbone). `ExecutionTrace` (persistence) = legacy SQLite execution record. `QAReport` = legacy Revit plan quality assessment. `ExecutionReport` (PR #142) = execution-chain terminal record. Evidence/validation bundles = M2/M4 + CLI recorder outputs. |
| **Known distinct responsibilities** | `Run Spine` = run-folder/audit identity layer every action wraps. `ExecutionTrace` = legacy job→trace persistence (queryable by job_id). `QAReport` = legacy quality/violation assessment. `ExecutionReport` = newer chain report. Bundles = per-engine evidence intake. |
| **Active files** | `src/axiom_core/run_spine.py`, `src/axiom_core/persistence.py` (ExecutionTrace), `src/axiom_core/schemas.py` (QAReport), `src/axiom_core/execution_report.py`, `src/axiom_core/execution_chain_orchestrator.py`, `src/axiom_core/validation/cli_validation_recorder.py` |
| **Risk of duplication** | **High.** ExecutionTrace (legacy) and ExecutionReport (new) are duplicate-candidates for "the execution record." Run Spine artifacts overlap with bundle layouts. (Cluster 4 covers the artifact-format angle; this cluster covers the record-model + run-identity angle.) |
| **Rule for future PRs** | Before adding a new validation/evidence bundle model or changing run-folder layout, reconcile against Run Spine (identity), ExecutionTrace (legacy record), and ExecutionReport (chain record). Do not add a fourth execution-record model. |
| **Status** | needs reconciliation — **duplicate candidate** (ExecutionTrace vs ExecutionReport) |

---

## Cluster 12: Coordinators — Agents Layer vs Data-Model Orchestrator vs Chain Orchestrator

| Field | Value |
|-------|-------|
| **Names / aliases** | OrchestratorAgent, ExecutionAgent, TelemetryAgent (agents/), Orchestrator + PlanTemplate (orchestrator.py), ExecutionChainOrchestrator, AutomationPlanner |
| **Likely overlap** | "Coordinate prompt → execution" appears in three places: the **agents** vertical slice (OrchestratorAgent→ExecutionAgent→TelemetryAgent), the data-model **Orchestrator** (Job→Plan→ToolStep→MCP), and the **ExecutionChainOrchestrator** (7-stage ID chain). AutomationPlanner adds event→lane planning. |
| **Known distinct responsibilities** | Per architecture rule "agents coordinate, capabilities execute": `OrchestratorAgent` = thin prompt→capability coordinator + telemetry. `Orchestrator` (orchestrator.py) = job→plan→MCP data-model pipeline. `ExecutionChainOrchestrator` = evidence-bearing chain. `AutomationPlanner` = event-driven dry-run lane planning. |
| **Active files** | `src/axiom_core/agents/orchestrator_agent.py`, `src/axiom_core/agents/execution_agent.py`, `src/axiom_core/agents/telemetry_agent.py`, `src/axiom_core/orchestrator.py`, `src/axiom_core/execution_chain_orchestrator.py`, `src/axiom_core/automation_planner.py` |
| **Risk of duplication** | **High.** Overlaps with Cluster 2. Any new "coordinator/worker loop" risks being a 4th coordination model. |
| **Rule for future PRs** | Do not move capability ownership into agents. Before a new coordination/worker layer, decide which existing coordinator it extends. Keep agents thin (coordinate only). |
| **Status** | accepted distinct (clear per-layer scope) but **high naming-overlap risk** |

---

## Old-foundation scan result

Required scan (PR #157, before final commit) reconciling older pipe / spine / bridge / job-plan / MCP / agents concepts against the newer execution-chain / evidence / confidence work.

1. **Did older pipe/spine/bridge/job-plan concepts already cover parts of the autonomy loop?**
   Yes. The named-pipe bridge (`PipeClient` → `AxiomPipeServer` → `PromptDispatcher`, "PR #2" per code) is the **real Revit execution edge**; `AutomationBridge` already wraps it as a non-interactive autonomy driver with durable bridge evidence. `Run Spine` already provides run identity + audit + artifact folders. `Orchestrator` already does Job→Plan→ToolStep→MCP. `WorkItem`/`WorkQueue` already model a work backlog. These cover transport, run-identity, planning, and backlog edges that a naive "new autonomy loop" would otherwise re-invent.

2. **Which newer concepts overlap with them?**
   - `MCPLayer` (mock) overlaps the real pipe bridge → Cluster 10.
   - `ExecutionReport`/evidence bundles overlap legacy `ExecutionTrace`/`QAReport` and Run Spine artifacts → Clusters 4 & 11.
   - `ExecutionChainOrchestrator` / `OrchestratorAgent` overlap the legacy `Orchestrator` → Clusters 2 & 12.
   - WorkItem/WorkQueue overlap Job/Plan as "what to do" → Cluster 1.

3. **Which older concepts are still active vs legacy/unknown?**
   - **Active:** Run Spine, PipeClient/AutomationBridge (Windows revalidation pending), AxiomPipeServer/PromptDispatcher (C#), Orchestrator, AutomationPlanner, Persistence/ExecutionTrace, Agents layer, input normalization, Job/Plan/ToolStep/QAReport schemas.
   - **Partial:** MCPLayer (mock only; real Revit-connected impl not proven in repo).
   - **Legacy/duplicate-candidate:** ExecutionTrace (vs newer ExecutionReport) for the "execution record" concept.
   - **Unknown:** original PR numbers for most pre-#112 foundation modules — not invented here; cited by file instead.

4. **What must future PRs check before proposing:**
   - **task packet consumer** → Cluster 1 (Job/Plan/WorkItem/WorkQueue). Consume an existing model; do not add a 4th.
   - **implementation attempt model** → `execution_attempt.py` / `execution_attempt_v2.py` already exist; reconcile, don't recreate.
   - **local worker loop** → Clusters 2, 10, 12 + Local Runner/CommandRegistry. Reuse `AutomationBridge`/`PipeClient` transport and existing coordinators.
   - **retry executor** → Cluster 7 (FailureClassification + RecoveryRecommendation + RecoveryExecution). Do not build a parallel retry engine.
   - **validation/evidence bundle changes** → Clusters 4 & 11 (Run Spine + ExecutionTrace + ExecutionReport + bundle conventions). Reconcile before changing layout.

5. **What remains unknown?**
   - Whether `MCPLayer` is intended to become the real Revit boundary or be superseded by the pipe bridge (mock↔real adapter seam unresolved).
   - Exact creating-PR numbers for pre-#112 foundation modules.
   - Whether ExecutionTrace is slated for retirement in favor of ExecutionReport, or both persist by design.

**Did this change any conclusions about future task-packet / worker / retry work?** Yes — it strengthens the anti-duplication position: a "task packet consumer," "local worker loop," and "retry executor" would each overlap **already-existing** old-foundation components (Job/Plan/WorkQueue, AutomationBridge/PipeClient, execution_attempt + recovery chain). Future PRs proposing these must start from the existing components via an adapter seam, not a new framework.
