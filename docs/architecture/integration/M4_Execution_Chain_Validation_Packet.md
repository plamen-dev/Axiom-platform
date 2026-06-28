# M4 Validation Packet — One Capability Through the Full Execution Chain

Milestone: M4 (`40_Open_Investigations.md` INV-03) · Status: **next executable target**
Prior evidence: PR #144 Self-Model Gap Analysis (CHAIN-001..005, REC-002)
Source hierarchy: Program 0 directive (PR #144) → Operational Integration Plan / Integration
Dependency Graph → `10_Current_Strategic_Context.md`, `20_Current_Organizational_State.md`,
`30_Architectural_Principles.md`, `40_Open_Investigations.md` → current repository evidence.

## 1. Likely next PR title

**Integration PR #146 — Execution Chain Orchestrator v1**

## 2. The finding this packet preserves (nominal, not executable)

The execution chain is **declared but unwired**. All six stage modules exist on `main`, but
the self-model contains **zero import edges** between consecutive stages. Each stage's
docstring says it "consumes upstream read-only" — that is documentation, not executable
linkage. **Docstring-level "read-only consumption" is NOT sufficient.** M4 must prove that
each stage consumes the prior stage's **real identifier or recorded output**.

PR #144 evidence (re-run on current `main`, 158 modules / 275 edges, `declared_but_unwired_chains` = 5):

| Transition | Modules (both exist) | Import edge today | gap_id |
|---|---|---|---|
| ExecutionPlan → ExecutionStep | `execution_plan` ↔ `execution_step` | none (either direction) | CHAIN (Plan→Step) |
| ExecutionStep → ExecutionAttempt | `execution_step` ↔ `execution_attempt_v2` | none | CHAIN (Step→Attempt) |
| ExecutionAttempt → ExecutionResult | `execution_attempt_v2` ↔ `execution_result` | none | CHAIN (Attempt→Result) |
| ExecutionResult → ExecutionArtifact | `execution_result` ↔ `execution_artifact` | none | CHAIN (Result→Artifact) |
| ExecutionArtifact → ExecutionReport | `execution_artifact` ↔ `execution_report` | none | CHAIN (Artifact→Report) |

Terminal stage: `Evidence → Report / State Update`. `execution_report.py` **is present on
`main`** (PR #142, `dc99c70`), so `ExecutionReport` is the real terminal stage — the PR #144
"module not present" flag was a branch-timing artifact and is resolved.

## 3. Files / modules to inspect

| Module | What to inspect |
|---|---|
| `src/axiom_core/execution_plan.py` | `ExecutionPlan.plan_id`; `ExecutionPlanStep` |
| `src/axiom_core/execution_step.py` | `ExecutionStep.step_id`; `ExecutionStepReferenceType` (`PLAN`, …); `reference_id`, `reference_type`, `reference_value` |
| `src/axiom_core/execution_attempt_v2.py` | `ExecutionAttempt.attempt_id`; `ExecutionAttemptReferenceType` (`STEP`, `PLAN`, …) |
| `src/axiom_core/execution_result.py` | `ExecutionResult.result_id`; `ExecutionResultReferenceType` (`ATTEMPT`, `STEP`, …) |
| `src/axiom_core/execution_artifact.py` | `ExecutionArtifact.artifact_id`; `ExecutionArtifactReferenceType` (`RESULT`, `ATTEMPT`, …) |
| `src/axiom_core/execution_report.py` | `ExecutionReport.report_id`, `section_id`; `ExecutionReportReferenceType` (`RESULT`, `ARTIFACT`, …) |

## 4. Existing engines reused (no new object model)

The id-flow hooks **already exist**. Every stage already has a `*Reference` dataclass with
`reference_type` / `reference_value` / `reference_id`, and every `*ReferenceType` enum already
names its upstream stage. M4 is **wiring, not new objects**:

| Downstream stage | Upstream reference type already in enum |
|---|---|
| `ExecutionStep` | `PLAN` |
| `ExecutionAttempt` | `STEP` (and `PLAN`) |
| `ExecutionResult` | `ATTEMPT` (and `STEP`) |
| `ExecutionArtifact` | `RESULT` (and `ATTEMPT`) |
| `ExecutionReport` | `RESULT`, `ARTIFACT` (and `ATTEMPT`) |

## 5. Expected producer/consumer links

```
Plan.plan_id ─► Step(ref PLAN=plan_id) ─► Attempt(ref STEP=step_id) ─► Result(ref ATTEMPT=attempt_id)
   ─► Artifact(ref RESULT=result_id) ─► Report(ref RESULT=result_id, ARTIFACT=artifact_id)
```
"Producer" = stage that emits an id; "consumer" = next stage that records that **real** id as a
typed reference (not a freshly minted placeholder, not a docstring).

## 6. Smallest implementation that validates the milestone

A **thin orchestrator** (e.g. `src/axiom_core/execution_chain_orchestrator.py`) that drives one
capability once through all six stages, passing each stage the prior stage's real id:

```python
plan = ExecutionPlan(...)                         # plan_id = P
step = ExecutionStep(...); step.add_reference(PLAN, value=plan.plan_id)        # consume P
attempt = ExecutionAttempt(...); attempt.add_reference(STEP, value=step.step_id)
result = ExecutionResult(...); result.add_reference(ATTEMPT, value=attempt.attempt_id)
artifact = ExecutionArtifact(...); artifact.add_reference(RESULT, value=result.result_id)
report = ExecutionReport(...)
report.add_reference(RESULT, value=result.result_id)
report.add_reference(ARTIFACT, value=artifact.artifact_id)
```

The orchestrator's import of the six stage modules also creates the **structural import edges**
that PR #144's gap analyzer measures, so `declared_but_unwired_chains` shrinks as a side effect
of real wiring (the edge is a consequence of consuming the id, not a cosmetic import).

## 7. Capability candidate decision table

The slice needs **one capability** to drive through the chain. M4's goal (per Execution Chain
Discipline) is a **deterministic** proof of real id flow — runnable in CI without external
runtime.

| Candidate | Real availability | Narrow | Produces evidence | Produces artifact/report | External runtime dep | Deterministic-slice fit | Verdict |
|---|---|---|---|---|---|---|---|
| **Internal capability** — `self-model-build` / `code-inventory` (M1, merged, CLI-exposed) | Yes | Yes (single purpose) | Yes (graph/relationship reports, counts) | Yes (JSON + Markdown export, per PR #144) | **None** (pure repo scan) | **High** — fully deterministic, runs in CI | **RECOMMENDED slice subject** |
| `SetParameterValue` (Revit primitive) | Named in registry; execution needs Revit | Yes | Only via Revit live run | Yes, once run | **Hard** dep on Revit live runtime | Low — non-deterministic, not CI-runnable | Strategic real-world target; **deferred** as slice subject until Revit live validation is in scope |
| `InventoryModel` (full) | Yes, but **guarded/blocked by default** | No (broad) | Yes | Yes | Revit runtime | Low — broad + guarded | **REJECTED** — too broad, guarded, runtime-bound |

**Justification (repository evidence).** M4 validates *chain wiring and id flow*, not Revit
behavior. `SetParameterValue` is the strategically-anchored first Primitive Action Validation
candidate, but its hard Revit-runtime dependency makes it unsuitable as the **deterministic**
M4 slice subject; using it would couple a chain-wiring proof to a non-deterministic external
runtime (violating the deterministic-slice requirement and `30_Architectural_Principles.md`
P6-AP-01 evidence-gating). The merged M1 internal capability already produces real ids,
evidence, and JSON+Markdown artifacts deterministically, so it is the correct subject for the
first chain trace. `SetParameterValue` remains the natural **next** subject once the wired
chain is carried into Revit live validation (routed below). `InventoryModel` is rejected as a
slice subject (broad and guarded — see Axiom architecture boundary rules).

## 8. Exact pass/fail criteria

For each transition `Upstream → Downstream`:

1. `downstream.references` contains a reference where
   `reference_type == <UpstreamType>` **and**
   `reference_value == upstream.<upstream_id_field>` (the real id, asserted by equality — not a
   non-empty check, not a fresh uuid). **FAIL** if the value is empty, a placeholder, or a
   re-minted id.
2. Re-running the self-model + gap analyzer after wiring shows the corresponding
   `declared_but_unwired_chains` entry **removed** (import edge now exists). **FAIL** if
   `declared_but_unwired_chains` count is unchanged for the wired transition(s).

End-to-end (whole chain):

3. Given the final `report_id`, the references resolve **backwards** to the originating
   `plan_id` (Report→{Result,Artifact}→…→Plan) — one complete trace. **FAIL** if any hop cannot
   be resolved from recorded references.
4. The terminal `ExecutionReport` carries references to the **real** `result_id` and
   `artifact_id` produced in the same run.

## 9. Validation evidence expected from PR #146

- A test asserting **id equality** across each of the five transitions (table in §8.1).
- A gap-analysis diff: `declared_but_unwired_chains` drops from **5** toward **0** for wired
  transitions (proves the edge is real, generated by Axiom, not asserted).
- One end-to-end trace test resolving `report_id → … → plan_id`.
- Full `poetry run pytest -q` green; `ruff check src/ tests/` clean.
- CLI smoke (if a command is added): run the orchestrator once, emit the trace.

## 10. Unresolved questions (routed — NOT designed here)

| Question | Route |
|---|---|
| Minimum viable Execution Graph Synthesizer design | INV-01 / **Program 2** |
| Organizational State contents & schema | INV-02 / **Program 2** |
| Should wiring be a direct module import vs. a registry/orchestrator indirection (and how that interacts with the import-edge metric)? | **Program 2** (architecture) — packet picks import+id for the smallest validatable slice |
| When does the wired chain carry `SetParameterValue` into Revit live validation? | **Program 0** (sequencing) + **Program 5** (infra) |
| Measuring executable relationship density as a metric | INV-07 / **Program 7** |

This packet does **not** define a new execution architecture, evidence architecture, or
synthesizer. It defines the smallest wiring that turns one declared transition into an
executable one and how to prove it.
