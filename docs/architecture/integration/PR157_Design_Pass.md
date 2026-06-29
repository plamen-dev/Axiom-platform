# PR #157 Design Pass — Repo-Grounded Assessment

Answers the 10 required design questions from direct repo inspection, then
assesses each deliverable for duplication, scope, and feasibility.

---

## Design Question 1: What repo-visible systems already describe Axiom's architecture?

| System | Path | What it describes | Staleness risk |
|--------|------|-------------------|----------------|
| Architecture docs (55 files) | `docs/architecture/*.md` | Per-component design specs (one doc per subsystem) | Medium — doesn't include PR #143–#157 modules |
| Current Axiom File Set | `docs/architecture/current-axiom-file-set.md` | Static file tree map with brief annotations | **Stale** — reflects pre-PR #143 tree, missing ~15 modules |
| Evidence Producer Inventory (PR #154) | `docs/architecture/integration/Evidence_Producer_Inventory_and_Consumer_Mapping_v1.md` | Evidence producers, consumers, EVID-001 status | Current |
| M2/M3/M4 Validation Packets (PR #145) | `docs/architecture/integration/M2_*.md`, `M3_*.md`, `M4_*.md` | What each milestone must prove and validate | Current |
| Canonical KB (PR #152) | `docs/canonical_knowledge_base/` | Strategic context, org state, architectural principles, open investigations | Current |
| Impact Ledger (PR #155) | `docs/canonical_knowledge_base/impact_ledger/` | 16 cross-program impact clusters, 114 source IDs | Current |
| Behavior Change Ledger | `docs/logs/behavior-change-ledger.md` | 31 BHV entries recording runtime behavior changes | Current |
| PR Review Ledger | `docs/logs/pr-review-ledger.md` | PR audit entries (What Changed / Behavior / Tests / Risks) | Partial — covers older PRs #41–#45, not PRs #143–#157 |
| Runbooks (12 files) | `docs/runbooks/` | Operational procedures | Current |
| Self-Model + Gap Analysis (PRs #143/#144) | `src/axiom_core/self_model.py`, `self_model_gap_analysis.py` | Live repo self-discovery via CodebaseInventory → knowledge graph | Current (runtime) |
| CodebaseInventory | `src/axiom_core/codebase_inventory.py` | AST-level repo scan (files, modules, classes, functions, CLI commands) | Current (runtime) |
| Context Preflight (this PR) | `src/axiom_core/context_preflight.py` | Live 9-section repo state scan | Current (runtime) |

**Key finding:** The repo has multiple overlapping "self-awareness" systems but no single map that links components → aliases → PRs → workflow edges → status → duplication risk. The self-model (PR #143) provides module-level graph intelligence but not human-readable component-family grouping or alias detection.

## Design Question 2: What existing files already function as maps, ledgers, registries, or inventories?

- **`current-axiom-file-set.md`** — file tree map (stale)
- **`pr-review-ledger.md`** — PR audit trail (partial coverage)
- **`behavior-change-ledger.md`** — behavior history (current, 31 entries)
- **`Canonical_Impact_Ledger.md`** — cross-program impact routing (current)
- **`Evidence_Producer_Inventory_*.md`** — evidence flow map (current)
- **`command_registry.py`** — runtime command catalog (current, 369 entries)
- **`self_model.py` + `self_model_gap_analysis.py`** — runtime repo graph + gap detection (current)
- **`context_preflight.py`** — runtime 9-section scan (current, this PR)

## Design Question 3: What DeepWiki / Wiki-visible concepts correspond to actual source files?

**No DeepWiki source files exist in-repo.** DeepWiki is an external generated service. Its concepts (job/plan execution pipeline, prompt execution flow, capability system, orchestration/persistence, QA/evaluation) correspond to:

- Job/Plan pipeline → `schemas.py` (Job, NormalizedJob, Plan, ToolStep, QAReport), `orchestrator.py`
- Prompt execution → `prompt_resolver.py`, `input_normalization.py`
- Capability system → `capability_registry.py`, `capability_confidence.py`, `capability_*.py` (22 modules)
- Orchestration → `orchestrator.py`, `execution_chain_orchestrator.py`, `coding_session_orchestrator.py`
- QA/Evaluation → `schemas.py::QAReport`, `validation/evidence_runner.py`, `validation/cli_validation_recorder.py`

DeepWiki should be referenced as "external architectural view, useful but not authoritative" — not replicated.

## Design Question 4: Which concepts appear duplicated under different names?

Already documented in `Duplicate_Alias_Map_v0.md` (9 clusters). The highest-risk clusters:

1. **Job/Plan/WorkItem/TaskPacket** — 3 parallel "what to do" models
2. **Orchestrator variants** — 6+ classes with "Orchestrator" or "Runner" in the name
3. **Two failure classification modules** — `failure_classification_framework.py` + `runner/failure_classification.py`
4. **Evidence/report artifact formats** — QAReport, evidence.json, trace.json, report.json, validation_run.json, axiom_capability_readiness.json

## Design Question 5: Which concepts are genuinely distinct despite similar names?

- `Orchestrator` (Job→Plan→MCP) vs `ExecutionChainOrchestrator` (M4 7-stage ID flow) — different scopes
- `EvidencePromotionLoop` (M2 evidence→state) vs `ModelHealthReadinessConsumer` (readiness intake, no confidence mutation) — different artifact types and state effects
- `Local Runner` (shell harness) vs `CapabilityRunner` (capability execution with run-spine) vs `EvidenceRunner` (3 in-process validations) — different execution contexts
- `WorkQueue` (dataclass-based backlog) vs `WorkItemRegistry` (SQLite-persisted backlog) — different persistence models for similar purpose (this IS a duplication risk)

## Design Question 6: Which existing artifacts should be reused rather than replaced?

- **`self_model.py` + `self_model_gap_analysis.py`** — already provide live repo graph; System Atlas should reference these rather than build a parallel graph
- **`command_registry.py::command_names()`** — already reused by context-preflight for command counts
- **`CodebaseInventory.scan()`** — already provides AST-level module/class/function discovery
- **`Evidence_Producer_Inventory_*.md`** — already maps evidence topology; System Atlas should reference, not duplicate
- **`Canonical_Impact_Ledger.md`** — already clusters cross-program impacts; should be referenced

## Design Question 7: Which existing docs should be referenced rather than duplicated?

- **`current-axiom-file-set.md`** — the System Atlas should note it exists (stale) and either update it or reference it
- **`pr-review-ledger.md`** — the PR Purpose Map covers different fields (workflow edge, duplication risk, "check before building near") that the PR Review Ledger does not; they are complementary, not duplicative
- **`Evidence_Producer_Inventory_*.md`** — System Atlas should reference for evidence topology, not re-describe
- **Architecture docs** — System Atlas should reference per-component docs rather than summarize them

## Design Question 8: Which output should be generated live versus tracked as a durable reference document?

| Output | Live generated (gitignored) | Tracked reference (committed) | Rationale |
|--------|---------------------------|-------------------------------|-----------|
| Context Preflight | Yes | No | Changes with every commit; must be fresh |
| System Atlas | Yes | No | Should reflect current repo state, not a stale snapshot |
| PR Purpose Map | No | Yes | Curated per-PR analysis; changes only when PRs are added |
| Duplicate/Alias Map | No | Yes | Curated reconciliation; changes when new concepts are added or reconciled |
| Context Pack index | No | Yes | Lightweight index pointing to other resources |

## Design Question 9: Which parts should remain unknown because repo evidence is insufficient?

- **PR #150** — no repo-visible evidence of a distinct merged PR with this number
- **DeepWiki freshness** — no way to verify whether DeepWiki's overview reflects current or stale repo state
- **Several architecture docs** — 55 docs under `docs/architecture/`; not all have been verified against current code; some may describe unimplemented or superseded designs
- **WorkQueue vs WorkItemRegistry reconciliation** — both exist; unclear which is canonical
- **M3 runtime status** — no repo evidence of M3 runtime implementation (docs/validation only)
- **Full EVID-001 closure** — only M2 and Model Health slices closed; broader status unknown

## Design Question 10: What is the smallest implementation that prevents future PRs from starting blind?

The smallest useful implementation is:

1. **Context Preflight CLI** (already done) — live 9-section scan any developer/agent can run
2. **System Atlas** (live generated) — component-family map grouped by workflow edge, with aliases and status
3. **PR Purpose Map** (tracked) — PR-to-purpose index so future work knows what each PR did
4. **Duplicate/Alias Map** (tracked) — anti-duplication guide for the 9 highest-risk clusters
5. **Context Pack index** (tracked) — lightweight pointer to all the above

Items 1, 3, 4, 5 are already implemented. Item 2 (System Atlas) is the remaining piece.

---

## Anti-Duplication Assessment

### PR Purpose Map vs PR-Review Ledger

The PR-Review Ledger (`docs/logs/pr-review-ledger.md`) covers older PRs (#41–#45) with a "What Changed / Behavior / Tests / Risks" structure. The PR Purpose Map covers PRs #143–#156 with different fields: **workflow edge, duplicate/overlap, "check before building near."** The PR Purpose Map is an anti-duplication index; the PR Review Ledger is an audit trail. They are complementary. The PR Purpose Map does not duplicate the PR Review Ledger.

### Duplicate/Alias Map vs Canonical Impact Ledger

The Impact Ledger routes cross-program impact flags into 16 clusters (CIL-001..016). The Duplicate/Alias Map identifies 9 within-codebase concept clusters that risk name collision. Different purpose: one is program-impact routing, the other is anti-duplication guidance for code/component names. Not duplicative.

### System Atlas vs Self-Model / Gap Analysis

The Self-Model (PR #143) produces a module-level graph with import edges and dependency detection. The Gap Analysis (PR #144) finds missing/disconnected nodes. A System Atlas would group components into human-readable families with aliases, workflow edges, and status. The self-model is a graph database; the atlas is a human-readable map. **The atlas should reference the self-model as its underlying data source where practical, not rebuild it.**

### System Atlas vs Current Axiom File Set

`current-axiom-file-set.md` is a static file tree (stale, 135 lines, pre-PR #143). The System Atlas would be live-generated and group by component family rather than file tree. Not duplicative — but the atlas should note that `current-axiom-file-set.md` exists and is stale.

### System Atlas vs Evidence Producer Inventory

The Evidence Producer Inventory (PR #154) maps evidence producers → consumers → EVID-001 status. The System Atlas would include evidence topology as one section but covers broader component families (orchestrators, registries, knowledge, etc.). The atlas should reference the inventory for evidence details, not re-describe them.

### Context Pack vs Canonical KB 00_Readme

The canonical KB `00_Readme.md` describes the canonical KB structure. The Context Pack is an index of all context resources (canonical, integration, operational, live). Different scope. Not duplicative.

---

## Scope Assessment

| Deliverable | Status | Risk | Recommendation |
|-------------|--------|------|----------------|
| Context Preflight CLI | Done, tested 10/10 | None | Preserve as-is |
| PR Purpose Map | Written (PRs #143–#156, M1–M4 with nuance) | Low | Commit as tracked doc |
| Duplicate/Alias Map | Written (9 clusters) | Low | Commit as tracked doc |
| Context Pack index | Written (lightweight index) | None | Commit as tracked doc |
| System Atlas (live generated) | Not yet implemented | **Medium** — 18 component families need accurate status/alias detection; getting it wrong is worse than not having it | Implement as bounded live-generated artifact; hardcode known component families from repo inspection rather than attempting dynamic discovery of all 200+ modules |

**Recommendation:** The full scope is bounded and non-duplicative. Implement the System Atlas as a live-generated artifact that hardcodes the ~18 known component families (from this design inspection), references existing docs/tools for detail, and marks unknowns. This is achievable within PR #157 without becoming a rushed mega-map.

**If the System Atlas implementation grows beyond ~300 lines or requires dynamic component-family discovery (rather than hardcoded families from inspection), stop and propose a follow-up.**
