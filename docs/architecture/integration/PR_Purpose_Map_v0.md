# PR Purpose Map v0

Seeded from repo-visible PR logs, behavior-change ledger entries, integration
docs, and direct code inspection. Does not fabricate missing facts — unknown
items are marked.

Last updated: PR #157 (Axiom Context Preflight, PR Purpose Map, and Live System Atlas v0).
Earlier-introduced foundational components section added by the required foundational provenance scan.

---

## Earlier-introduced foundational components (predate the PR #112+ series) — repo-visible

The required foundational provenance scan surfaced foundational modules that predate
the PR #112+ framework series. These are **not** "legacy": none is proven unused,
superseded, bypassed, or intentionally retired. They are earlier-introduced components,
mapped here so future PRs do not rebuild them under new names.

Their introducing **GitHub repo-local PR numbers are recoverable** from this repo's git
history via `git log --diff-filter=A` (they are *not* unknown): AutomationBridge = repo-local
PR #19, PipeClient = repo-local PR #2 (the earliest agents + named-pipe vertical slice),
Run Spine = repo-local PR #31, Automation Planner = repo-local PR #35, WorkItem/WorkQueue =
repo-local PR #56, Execution-attempt = repo-local PR #111. Prompt/Input Normalization,
Job/Plan/ToolStep/QAReport schemas, Orchestrator, MCP Layer, and Persistence/ExecutionTrace
were introduced by the initial-foundation commit (repo bootstrap, no associated PR).
(GitHub repo-local PR numbers are distinct from Axiom GPR numbers; Devin lane provenance is
not required to establish these — git history in this workspace is sufficient.)

| Component (repo-visible) | Files | Workflow edge | Classification |
|--------------------------|-------|---------------|----------------|
| Prompt / Input Normalization | `src/axiom_core/input_normalization.py`, `prompt_resolver.py` | User prompt/Excel → NormalizedJob | active / distinct responsibility |
| Job / Plan / ToolStep / QAReport schemas | `src/axiom_core/schemas.py` | NormalizedJob → Plan → ToolStep → QAReport | active (earlier-introduced pipeline) |
| Orchestrator (job→plan→MCP) | `src/axiom_core/orchestrator.py` | Job → Plan → ToolStep → MCP execution | active; overlaps newer orchestrators (Cluster 2/12) |
| MCP Layer (mock tool boundary) | `src/axiom_core/mcp_layer.py` | Plan/ToolStep → ToolResult (simulated) | partial (mock only; real Revit-connected impl unproven) |
| Automation Bridge / Pipe Client | `src/axiom_core/automation_bridge.py`, `pipe_client.py` | Capability request → named pipe → Revit | active; Windows revalidation pending (PR #151) |
| Revit Add-in Bridge (C#) | `src/axiom_revit/Axiom.Core/Bridge/AxiomPipeServer.cs`, `PromptDispatcher.cs`, `Axiom.RevitAddin/PromptCommand.cs` | Pipe → AxiomPipeServer → PromptDispatcher → Revit capability | active (C#); not exercised by Python pytest |
| Run Spine (audit/evidence backbone) | `src/axiom_core/run_spine.py` | Any action → run ID + artifact folder + audit log | active (cross-cutting backbone) |
| Automation Planner (event→lane) | `src/axiom_core/automation_planner.py` | Change event → dry-run plan + policy gate | active (planning/recommendation only) |
| Persistence / ExecutionTrace | `src/axiom_core/persistence.py` | Execution → ExecutionTrace → SQLite store | active; duplicate-candidate vs ExecutionReport (Cluster 11) |
| Agents Layer (coordinate-only) | `src/axiom_core/agents/orchestrator_agent.py`, `execution_agent.py`, `telemetry_agent.py` | Prompt → coordinate → capability → telemetry | active; overlaps coordinators (Cluster 12) |
| Work backlog (WorkItem/WorkQueue) | `src/axiom_core/work_item_registry.py`, `work_queue.py`, `work_prioritization.py` | Backlog of "what to do" | active; overlaps Job/Plan (Cluster 1) |
| Execution-attempt / recovery chain | `src/axiom_core/execution_attempt.py`, `execution_attempt_v2.py`, `recovery_recommendation.py`, `recovery_execution.py` | Attempt → failure classification → recommendation → execution | active; check before any new retry executor (Cluster 7) |

See the Duplicate / Alias Map (Clusters 1, 2, 4, 7, 10, 11, 12) and its **Foundational provenance scan result** section for overlap analysis and the rules future PRs must follow before adding a task-packet consumer, local worker loop, or retry executor.

---

## PR #143 — Self-Model Population v1 (M1)

| Field | Value |
|-------|-------|
| **Purpose** | Pipe existing `CodebaseInventory` producer into existing `CapabilityKnowledgeGraphEngine` and `CapabilityRelationshipEngine` so Axiom can answer repo dependency questions from its own populated graph. |
| **Components** | `axiom_core.self_model` (adapter/exporter only — no new framework) |
| **Files** | `src/axiom_core/self_model.py`, `tests/test_self_model.py` |
| **Workflow edge** | M1: code-inventory → knowledge graph + relationship graph population |
| **Validation evidence** | Tests present; produces self-model/gap intelligence from real repo structure |
| **Status** | active / implemented runtime behavior (merged) |
| **What it does NOT do** | Does not execute capabilities, does not create new registries, does not mutate upstream producers |
| **Duplicate/overlap** | Adapter only — consumes existing CodebaseInventory, feeds existing KnowledgeGraph and RelationshipEngine |
| **Check before building near** | Any new repo self-discovery or self-model population mechanism |

---

## PR #144 — Self-Model Gap Analysis v1 (M1 negative discovery)

| Field | Value |
|-------|-------|
| **Purpose** | Executable negative discovery on top of PR #143's self-model: enumerate what is missing, disconnected, unused, or unexplained across the repository. |
| **Components** | `axiom_core.self_model_gap_analysis` (analyzer only — no new framework) |
| **Files** | `src/axiom_core/self_model_gap_analysis.py`, `tests/test_self_model_gap_analysis.py` |
| **Workflow edge** | M1: self-model → gap classification → ranked integration backlog (JSON + Markdown) |
| **Validation evidence** | Tests present; identified EVID-001 (orphaned evidence producers), execution-chain unwired transitions, and other gaps that informed PRs #146–#156 |
| **Status** | active / implemented runtime behavior (merged) |
| **What it does NOT do** | Does not fix gaps — only identifies and ranks them. Does not build an execution engine. |
| **Duplicate/overlap** | Analyzer only — reads existing self-model output |
| **Check before building near** | Any new gap analysis or integration backlog generator |

---

## PR #145 — M4/M2/M3 Validation Packets v1

| Field | Value |
|-------|-------|
| **Purpose** | Create validation packet docs for the three integration milestones (M4 Execution Chain, M2 Evidence Promotion, M3 Purpose Layer). |
| **Components** | `docs/architecture/integration/M4_Execution_Chain_Validation_Packet.md`, `M2_Evidence_Promotion_Validation_Packet.md`, `M3_Purpose_Layer_Validation_Packet.md` |
| **Files** | `docs/architecture/integration/M4_Execution_Chain_Validation_Packet.md`, `docs/architecture/integration/M2_Evidence_Promotion_Validation_Packet.md`, `docs/architecture/integration/M3_Purpose_Layer_Validation_Packet.md` |
| **Workflow edge** | Docs/planning: defined what M2/M3/M4 mean, what each must prove, and what tests/evidence validate them |
| **Validation evidence** | Docs-only — no tests (defines the validation criteria, does not execute them) |
| **Status** | active / docs/validation milestone (merged) |
| **M3 nuance** | M3 (Purpose Layer) is described as "hooks + test matrix" and "does not delay M4." M3 validates that structural and semantic relationships are independently queryable. No repo evidence of M3 runtime implementation exists — it remains a docs/validation-oriented milestone. Full purpose/layer architecture is listed as future work for Program 2 + Program 6. |
| **Duplicate/overlap** | None — planning docs |
| **Check before building near** | Review these packets before claiming any milestone closure |

---

## PR #146 — Execution Chain Orchestrator v1 (M4)

| Field | Value |
|-------|-------|
| **Purpose** | Prove the M4 vertical execution chain (Plan→Step→Attempt→Result→Artifact→Evidence→Report) is executable with real linked IDs, not just declared by docstrings. |
| **Components** | `axiom_core.execution_chain_orchestrator` (ExecutionChainOrchestrator) |
| **Files** | `src/axiom_core/execution_chain_orchestrator.py`, `tests/test_execution_chain_orchestrator.py` |
| **Workflow edge** | M4: deterministic capability → 7-stage linked ID flow → evidence bundle |
| **Validation evidence** | 7/7 chain IDs, `id_flow_status: PASS`, `ids_distinct: true`, persisted disk artifacts |
| **Status** | active / implemented runtime behavior (merged) |
| **What it proves** | The execution chain is executable — each downstream stage reconstructs its upstream via recorded identifiers. |
| **What it does NOT prove** | Does not prove a full autonomous implementation loop. Does not prove arbitrary capability execution. The proof target is `self-model-build` (deterministic, CI-safe, no Revit). |
| **Duplicate/overlap** | Coordinates existing execution_plan, execution_step, execution_attempt_v2, execution_result, execution_artifact, execution_report — does not replace them |
| **Check before building near** | Any new execution orchestrator or chain runner |

---

## PR #147 — Evidence to Promotion Loop v1 (M2)

| Field | Value |
|-------|-------|
| **Purpose** | Prove M2: execution evidence changes capability state. Route execution-chain evidence bundles into CapabilityConfidenceEngine. |
| **Components** | `axiom_core.evidence_promotion` (EvidencePromotionLoop) |
| **Files** | `src/axiom_core/evidence_promotion.py`, `tests/test_evidence_promotion.py` |
| **Workflow edge** | M2: evidence bundle → pass/fail determination → CapabilityConfidenceEngine state mutation |
| **Validation evidence** | Passing evidence raises confidence/readiness; failing evidence lowers them |
| **Status** | active / implemented runtime behavior (merged) |
| **What it proves** | The narrow M2 slice: execution-chain evidence changes capability state via existing confidence engine. |
| **What it does NOT prove** | Not global evidence closure. Not all evidence types are consumed. EVID-001 remains partially closed. |
| **Duplicate/overlap** | Thin adapter to existing CapabilityConfidenceEngine — no new promotion framework |
| **Check before building near** | Any new evidence consumer that mutates capability state |

---

## PR #148 — Evidence Promotion Safety Hardening v1 (M2 hardening)

| Field | Value |
|-------|-------|
| **Purpose** | Harden evidence promotion with duplicate detection, conflict quarantine, staleness checks, and fingerprint dedup. |
| **Components** | `axiom_core.evidence_promotion` (EvidencePromotionLoop — extended) |
| **Files** | `src/axiom_core/evidence_promotion.py`, `tests/test_evidence_promotion.py` |
| **Workflow edge** | M2 hardening: idempotent intake, conflict detection, stale evidence quarantine |
| **Validation evidence** | Duplicate→no state change, conflict→quarantined, stale→quarantined, invalid→rejected |
| **Status** | active / implemented runtime behavior (merged) |
| **Duplicate/overlap** | Extension of PR #147 — same module |
| **Check before building near** | Evidence dedup or conflict resolution logic |

---

## PR #149 — Devin PR Self-Audit and CLI Testing Skill Update v1

| Field | Value |
|-------|-------|
| **Purpose** | Establish Devin operational guardrails: self-audit checklist, Purpose-to-Workflow reconciliation, CLI testing skill with M4/M2 verification checklists. |
| **Components** | `.agents/skills/testing-axiom-cli/SKILL.md` |
| **Files** | `.agents/skills/testing-axiom-cli/SKILL.md` |
| **Workflow edge** | Operational / PR quality gate — not runtime |
| **Validation evidence** | Skill file present with checklists |
| **Status** | active / support-only (merged) |
| **Duplicate/overlap** | None — operational skill, not runtime code |
| **Check before building near** | Any new Devin skill or PR audit protocol |

---

## PR #150

| Field | Value |
|-------|-------|
| **Purpose** | Unknown — this PR number appears in planning references but no repo-visible evidence of a distinct merged PR #150 was found separately from PR #153. May have been renumbered or superseded. |
| **Status** | unknown |

---

## PR #151 — Windows Artifact Path Compatibility Fix v1

| Field | Value |
|-------|-------|
| **Purpose** | Fix Windows artifact path containment: `is_within_sandbox` was failing on Windows due to path normalization differences. |
| **Components** | `axiom_core.artifact_paths` (is_within_sandbox) |
| **Files** | `src/axiom_core/artifact_paths.py`, `tests/test_artifact_paths.py` |
| **Workflow edge** | Cross-cutting: path safety for all artifact writers |
| **Validation evidence** | Pre-fix Windows probe exposed bug; fix verified on Ubuntu CI; post-PR #151 Windows revalidation remains pending |
| **Status** | active / implemented runtime behavior (merged) |
| **Duplicate/overlap** | None — fixes existing utility |
| **Check before building near** | Any artifact path validation or sandbox logic |

---

## PR #152 — Canonical Knowledge Base Repo Seed v1

| Field | Value |
|-------|-------|
| **Purpose** | Seed `docs/canonical_knowledge_base/` with 7 stable-named canonical documents (00–60). |
| **Components** | `docs/canonical_knowledge_base/` |
| **Files** | 7 Markdown files under `docs/canonical_knowledge_base/` |
| **Workflow edge** | Program 6 canonical custody — durable context source for all programs |
| **Validation evidence** | Docs-only; no tests needed |
| **Status** | active / docs (merged) |
| **Duplicate/overlap** | `30_Architectural_Principles.md` points to existing `axiom-doctrine.md` rather than forking |
| **Check before building near** | Any new canonical source or knowledge base location |

---

## PR #153 — CLI Validation Evidence Recorder v1

| Field | Value |
|-------|-------|
| **Purpose** | Run explicit, ordered plans of allowlisted CLI commands and write durable evidence bundles. |
| **Components** | `axiom_core.validation.cli_validation_recorder` (CLIValidationRecorder) |
| **Files** | `src/axiom_core/validation/cli_validation_recorder.py`, `tests/test_cli_validation_recorder.py`, `docs/validation_plans/` |
| **Workflow edge** | Traceability: plan → governed command execution → evidence bundle |
| **Validation evidence** | 26 tests; M4 PASSED 1/1, M2 PASSED 2/2; failure and unsafe-command blocking verified |
| **Status** | active / implemented runtime behavior — traceability-first; no consumer yet by design (merged) |
| **Duplicate/overlap** | Complementary to EvidenceRunner (3 fixed in-process validations) — not a replacement; governed by CommandRegistry |
| **Check before building near** | Any new CLI execution harness or validation recorder |

---

## PR #154 — Evidence Producer Inventory and Consumer Mapping v1

| Field | Value |
|-------|-------|
| **Purpose** | Inventory all evidence producers and map each to its current/missing consumer. Confirmed Model Health Evidence Consumer as next implementation target. |
| **Components** | `docs/architecture/integration/Evidence_Producer_Inventory_and_Consumer_Mapping_v1.md` |
| **Files** | `docs/architecture/integration/Evidence_Producer_Inventory_and_Consumer_Mapping_v1.md` |
| **Workflow edge** | Investigation — informed PR #156 target selection |
| **Validation evidence** | 80+ files inspected, 18 EVID-001 references mapped, 9 evidence-producing tiers documented |
| **Status** | active / investigation (merged) |
| **Duplicate/overlap** | None — inventory/reconciliation, not runtime |
| **Check before building near** | Any new evidence producer or consumer |

---

## PR #155 — Canonical Impact Ledger and Program Inventory Reconciliation v1

| Field | Value |
|-------|-------|
| **Purpose** | Reconcile 5 program inventories (Programs 0, 2, 5, 6, 7) into 16 cross-program impact clusters with 114 source IDs. |
| **Components** | `docs/canonical_knowledge_base/impact_ledger/` |
| **Files** | `docs/canonical_knowledge_base/impact_ledger/Canonical_Impact_Ledger.md`, `Program_Inventory_Reconciliation_PR155.md` |
| **Workflow edge** | Program 6 canonical custody — cross-program reconciliation reference |
| **Validation evidence** | Docs-only; 114 source IDs, 16 CIL clusters |
| **Status** | active / docs (merged) |
| **Caveats** | Program 3/4 out of scope (not pending). P6-CIF-022 excluded per operator clarification. |
| **Duplicate/overlap** | None |
| **Check before building near** | Any new program reconciliation or impact ledger entry |

---

## PR #156 — Model Health Evidence Consumer v1

| Field | Value |
|-------|-------|
| **Purpose** | Close the narrow Model Health readiness slice of EVID-001 by adding a state/evidence consumer for `axiom_capability_readiness.json`. |
| **Components** | `axiom_core.model_health_evidence` (ModelHealthReadinessConsumer) |
| **Files** | `src/axiom_core/model_health_evidence.py`, `tests/test_model_health_evidence.py` |
| **Workflow edge** | Evidence intake: readiness artifact → validate → dedup → accept/quarantine/reject → intake record |
| **Validation evidence** | 19 tests; accept → duplicate → conflict-quarantine → reject verified; confidence NOT mutated |
| **Status** | active / implemented runtime behavior (merged) |
| **What it proves** | Model Health readiness artifacts now have a real consumer (no longer orphaned). |
| **What it does NOT prove** | Real `execute_health_run` producer invocation not proven unless repo evidence exists. Does not revalidate Windows. `confidence_mutated=false` always — readiness does NOT route into confidence math. Whether readiness should influence confidence is an open Program 6 doctrine question. |
| **EVID-001 scope** | Closes EVID-001 for Model Health readiness slice only. Broader EVID-001 remains open. |
| **Duplicate/overlap** | Reuses intake/dedup conventions from PR #147/#148 |
| **Check before building near** | Any new readiness consumer or confidence mutator |
