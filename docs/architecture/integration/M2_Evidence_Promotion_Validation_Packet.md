# M2 Validation Packet — Evidence to Promotion Loop

Milestone: M2 (`40_Open_Investigations.md` INV-04) · Role: **hooks + test matrix** (does not delay M4)
Prior evidence: PR #144 Self-Model Gap Analysis — EVID-001
Source hierarchy: Program 0 directive (PR #144) → Operational Integration Plan / Integration
Dependency Graph → `10_Current_Strategic_Context.md`, `30_Architectural_Principles.md`,
`40_Open_Investigations.md`, `60_Reasoning_Quality_Assurance.md` → current repository evidence.

## 1. Likely next PR title

**Integration PR — Evidence-to-State Loop v1** (after M4)

## 2. The finding this packet preserves (evidence orphaning)

PR #144 gap **EVID-001** (`artifact_or_evidence_producers_without_consumers`):
`axiom_core.model_health` produces evidence/readiness output but has **no visible downstream
consumer** in the self-model. This is the "evidence orphaning" failure in
`60_Reasoning_Quality_Assurance.md` (Observed Basis #8 / P7-RQA-06): artifacts and pass/fail
output are preserved **without changing capability state, readiness, confidence, or promotion.**

**This packet does NOT design a promotion system or promotion doctrine.** It defines tests that
determine whether evidence can change capability state/readiness/confidence/promotion **using
existing structures first**.

## 3. Files / modules to inspect

| Module | Existing structure to reuse |
|---|---|
| `src/axiom_core/global_capability_registry.py` | `GlobalCapabilityRegistryEngine`; `GlobalCapabilityStatus` (`proposed`/`open`/`merged`/`closed`/`superseded`); `GlobalCapabilityValidationSummary` (`new_tests`, `total_tests`, `skipped_tests`, `ruff_clean`, `ci_status`); `GlobalCapabilityEvidence` + `_write_evidence()`; `GlobalCapabilityEntry.status` |
| `src/axiom_core/capability_confidence.py` | `CapabilityConfidenceEngine.create(...)`; `CapabilityConfidenceFactors`; `CapabilityConfidenceLevel` (`very_low`…`very_high`); `_compute_score`, `_level_from_score` |
| `src/axiom_core/model_health.py` | `ModelHealth`, `CapabilityReadiness`, `HealthRunResult` (the EVID-001 producer whose output must become a consumer input) |

## 4. Expected producer/consumer link

```
run evidence (pass/fail bundle, e.g. GlobalCapabilityValidationSummary / model_health HealthRunResult)
        │  (currently orphaned — EVID-001)
        ▼
CapabilityConfidenceEngine.create(factors derived from evidence)  ─►  confidence score / level change
        └─► (optionally) GlobalCapabilityEntry.status / readiness change, keyed by capability id
```

## 5. Smallest implementation that validates the milestone

A thin **evidence-intake hook** that maps one run's pass/fail bundle onto existing engines:
derive `CapabilityConfidenceFactors` from the validation summary and call
`CapabilityConfidenceEngine.create(...)`, linking the resulting confidence/evidence record to a
`global_capability_id`. No new registry, no new evidence object, no promotion doctrine.

## 6. Test matrix / hooks (exact pass/fail)

| # | Hook | Pass criterion | Fail criterion |
|---|---|---|---|
| H1 | Passing evidence raises confidence | Confidence score after intake **> baseline** (or level moves up), as a function of the evidence factors | Score unchanged or hard-coded |
| H2 | Failing evidence does not raise confidence | Failing/low-coverage bundle yields score **≤ baseline** (or level down) | Failing evidence still raises score |
| H3 | Evidence is linked, not orphaned | Resulting confidence/evidence record references the **real** `global_capability_id` | Record has no capability linkage (EVID-001 persists) |
| H4 | State/promotion responds to evidence | A capability state, readiness flag, or promotion counter **changes as a function of evidence** | State is static / set independently of evidence |
| H5 | Determinism | Same evidence → same score/level | Non-deterministic output |

## 7. Validation evidence expected from the implementation PR

- Tests H1–H5 green (fixtures: one passing bundle, one failing bundle).
- A before/after assertion: a capability's confidence level (or status/readiness) **differs**
  purely because evidence was ingested — demonstrating evidence changes state.
- Re-run gap analysis: EVID-001 producer now has a downstream consumer edge (orphan cleared).
- Full `pytest -q` green; `ruff` clean.

## 8. Relationship to M4 (why this does not block M4)

M4 proves **id flow** through the chain; it does not require evidence→state propagation to be
validated. No PR #144 evidence shows M4 cannot be validated without M2. M2 consumes the kind of
artifact/evidence M4's terminal stage produces, so M2 naturally follows M4.

## 9. Unresolved questions (routed — NOT designed here)

| Question | Route |
|---|---|
| Full promotion doctrine / promotion eligibility rules | **Program 6** (doctrine) |
| Confidence model architecture (factor weighting, thresholds) | **Program 2** / **Program 7** |
| Evidence-to-promotion loop scope and triggers | INV-04 / **Program 0** sequencing |
| Execution-graph invalidation / re-synthesis on new evidence | INV-08 / **Program 2** |
