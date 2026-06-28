# Canonical Impact Ledger

| Field | Value |
|-------|-------|
| **Status** | Working ledger (v1) — provisional classifications; Program 6 owns final classification |
| **Owner** | Program 1 (ledger maintenance) / Program 6 (classification authority) |
| **Last Updated** | 2026-06-23 |
| **Source** | PR #155 — reconciliation of Program 0, 2, 5, 6, 7 inventories + PR #146–#154 execution context |

## 1. Purpose

This ledger reconciles Canonical Impact Flags surfaced during the M4/M2/M3 integration
work, Canonical Knowledge Base seed (PR #152), and cross-program review cycles into a
single working list. It enables Program 6 to classify final canonical impacts in batches
rather than forcing one PR per flag.

PR #152 seeded canonical structure but did not fully backfill all Canonical Impact Flags.
This PR creates a traceability/reconciliation layer, not final canonical classification.

## 2. Source-of-Truth Rule

This ledger is a **working reconciliation tool**, not canonical truth. Final canonical
updates to documents `10`–`60` require Program 6 classification and appropriate review
per `00_Readme.md` update policy. Until classified, entries here are provisional.

## 3. Status

- Programs reconciled: **0, 2, 5, 6, 7**
- Programs out of scope: **3, 4** (not part of this reconciliation cycle)
- Source IDs preserved: P0-CIF-001..022, P2-CIF-001..025, P5-CIF-001..020, P6-CIF-001..030, P7-CIF-001..017
- Classification authority: **Program 6**
- Strategic synthesis: **Program 0**
- Architecture/evidence semantics: **Program 2**
- Infrastructure/Local Runner: **Program 5**
- Operational review: **Program 7**

## 4. How to Use This Ledger

1. Find the cluster relevant to your concern.
2. Check the proposed classification and recommended handling.
3. If you are the owner program, review and confirm or reclassify.
4. When a batch of items is ready, create a canonical maintenance PR (not one per flag).
5. Mark items `Closed` when the canonical update PR is merged.

## 5. Reconciled Ledger

### CIL-001 — Canonical Source-of-Truth and Library Mirror Boundary

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-001 |
| **Cluster** | Canonical source-of-truth and Library mirror boundary |
| **Short Title** | Repo canonical source vs ChatGPT Library mirrors; stable filenames; clean-source/traceability separation |
| **Source Program Flag IDs** | P0-CIF-009, P2-CIF-011, P2-CIF-025, P6-CIF-001, P6-CIF-003, P6-CIF-004, P7-CIF-008 |
| **Source Programs** | P0, P2, P6, P7 |
| **Affected Canonical Documents** | 00_Readme; 30 |
| **Proposed Classification** | Light Update / Communication Record / Reasoning QA Candidate |
| **Current Capture Status** | Mostly captured in 00_Readme.md rules 1–6 (PR #152); P6-AP-10 in Doc 30 |
| **Recommended Handling** | Program 6 classification; likely batch later if PR #152 did not already capture fully |
| **Owner** | Program 6 |
| **Review Tier** | Light |
| **Evidence Summary** | PR #152 00_Readme.md source-of-truth rules; all 5 programs converged on repo-canonical-source rule; P2-CIF-025 confirms clean-source/traceability pattern |
| **Open Questions** | Whether PR #152 fully captured this cluster or needs light follow-up |
| **Status** | Open — awaiting Program 6 classification |

### CIL-002 — Canonical Impact Ledger and Batching Workflow

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-002 |
| **Cluster** | Canonical Impact Ledger and batching workflow |
| **Short Title** | Flag accumulation, reconciliation, classification, and batching — do not create one PR per flag |
| **Source Program Flag IDs** | P0-CIF-010, P0-CIF-022, P2-CIF-012, P6-CIF-002, P6-CIF-005, P6-CIF-023, P7-CIF-009 |
| **Source Programs** | P0, P2, P6, P7 |
| **Affected Canonical Documents** | 00_Readme |
| **Proposed Classification** | Immediate Reconciliation / Traceability Infrastructure / Reasoning QA Candidate |
| **Current Capture Status** | This PR implements the ledger/reconciliation layer; 00_Readme.md rule 6 defines batching |
| **Recommended Handling** | This PR should implement the ledger/reconciliation layer; do not update every canonical document from this PR |
| **Owner** | Program 6 final classification; Program 1 reconciliation |
| **Review Tier** | Targeted |
| **Evidence Summary** | PR #155 (this PR); 00_Readme.md rule 6; P0-CIF-022 notes PR #152 may not have captured all flags |
| **Open Questions** | None — this PR is the implementation |
| **Status** | In progress (this PR) |

### CIL-003 — M4 Execution-Chain Proof and Integration Phase Transition

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-003 |
| **Cluster** | M4 execution-chain proof and Integration Phase transition |
| **Short Title** | PR #146 vertical slice; Execution Graph vs Execution Run; Integration Phase confirmed; Synthesizer not complete |
| **Source Program Flag IDs** | P0-CIF-001, P0-CIF-006, P2-CIF-001, P2-CIF-007, P2-CIF-008, P6-CIF-019 |
| **Source Programs** | P0, P2, P6 |
| **Affected Canonical Documents** | 10; 20; 30 |
| **Proposed Classification** | Targeted Review Required / Strategic Update Candidate / Traceability |
| **Current Capture Status** | Partially captured in Doc 10 M4 section, Doc 20 Execution Run section, BHV-026 |
| **Recommended Handling** | Batch later; do not overclaim Execution Graph Synthesizer completion |
| **Owner** | Program 0 and Program 2; Program 6 classification |
| **Review Tier** | Targeted |
| **Evidence Summary** | PR #146 execution-chain orchestrator; M4 validation packet; Execution Graph vs Execution Run distinguished in Doc 20 v3 |
| **Open Questions** | Whether runtime ID-flow pattern warrants Doc 20 update |
| **Status** | Open — awaiting batch classification |

### CIL-004 — M2 Evidence-to-State Proof and Evidence-Safety Hardening

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-004 |
| **Cluster** | M2 evidence-to-state proof and evidence-safety hardening |
| **Short Title** | PR #147 narrow M2 proof; PR #148 duplicate/conflict handling; readiness thresholds not doctrine |
| **Source Program Flag IDs** | P0-CIF-007, P0-CIF-008, P2-CIF-002, P2-CIF-003, P2-CIF-004, P6-CIF-006, P6-CIF-007, P6-CIF-008, P7-CIF-003, P7-CIF-015 |
| **Source Programs** | P0, P2, P6, P7 |
| **Affected Canonical Documents** | 30 (P6-AP-07); 40 |
| **Proposed Classification** | Open Investigation / Reasoning QA Candidate / Targeted Review Required |
| **Current Capture Status** | Partially captured in BHV-026/027; readiness thresholds not in Doc 30 |
| **Recommended Handling** | Track as evidence-safety cluster; PR #148 hardening is implementation evidence; readiness thresholds must not become doctrine without classification |
| **Owner** | Program 1 implementation evidence; Program 2 architecture; Program 6 classification; Program 7 operational QA |
| **Review Tier** | Targeted |
| **Evidence Summary** | PR #147 narrow M2 slice; PR #148 duplicate/conflict/accumulation tests; BHV-027 |
| **Open Questions** | How duplicate/conflicting evidence should be handled canonically; whether readiness thresholds need formal classification |
| **Status** | Open — evidence-safety cluster |

### CIL-005 — EVID-001 Partial Closure and Remaining Evidence Producer Gaps

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-005 |
| **Cluster** | EVID-001 partial closure and remaining evidence producer gaps |
| **Short Title** | Narrow M2 slice closed; model-health and other producers remain open/partially consumed |
| **Source Program Flag IDs** | P2-CIF-005, P2-CIF-017, P5-CIF-010, P5-CIF-012, P5-CIF-017, P6-CIF-009, P6-CIF-025, P7-CIF-004, plus PR #154 |
| **Source Programs** | P2, P5, P6, P7 |
| **Affected Canonical Documents** | 40 |
| **Proposed Classification** | Open Investigation / Targeted Review Required |
| **Current Capture Status** | Partially captured in OI-001 area and PR #154 evidence producer inventory |
| **Recommended Handling** | Mark EVID-001 as partially closed, not globally closed; use PR #154 to decide next implementation |
| **Owner** | Program 2 architecture; Program 6 classification; Program 1 implementation sequencing |
| **Review Tier** | Targeted |
| **Evidence Summary** | PR #154 evidence producer inventory; model_health.py orphaned output; pass_fail.json producers lack confidence consumer |
| **Open Questions** | Whether to add EVID-001 as formal OI entry in Doc 40; which evidence types should affect confidence |
| **Status** | Open — EVID-001 NOT globally closed |

### CIL-006 — CLI Validation Evidence Recorder and Durable Validation Proof

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-006 |
| **Cluster** | CLI Validation Evidence Recorder and durable validation proof |
| **Short Title** | PR #153 Axiom-native validation bundles; validation evidence vs state-changing evidence |
| **Source Program Flag IDs** | P0-CIF-014, P2-CIF-009, P2-CIF-023, P5-CIF-017, P6-CIF-025, P7-CIF-006 |
| **Source Programs** | P0, P2, P5, P6, P7 |
| **Affected Canonical Documents** | None directly |
| **Proposed Classification** | Traceability / Open Investigation / Reasoning QA Candidate |
| **Current Capture Status** | Captured in BHV-029; PR #153 validation recorder implemented |
| **Recommended Handling** | Track as durable evidence infrastructure; do not treat validation bundles as state-changing evidence until a consumer is explicitly implemented |
| **Owner** | Program 1 and Program 7; Program 2 if state update behavior is later added |
| **Review Tier** | Light |
| **Evidence Summary** | PR #153; 26 tests; CLI smoke M4 + M2 plans; BHV-029 |
| **Open Questions** | Whether validation bundles should eventually become state-update inputs |
| **Status** | Open — consumer deferred |

### CIL-007 — Runtime Relationship Awareness vs Static Import Metrics

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-007 |
| **Cluster** | Runtime relationship awareness vs static import metrics |
| **Short Title** | Executable relationships over structural inventory; connection theater avoidance; forced imports |
| **Source Program Flag IDs** | P0-CIF-004, P0-CIF-005, P0-CIF-013, P2-CIF-010, P6-CIF-026 |
| **Source Programs** | P0, P2, P6 |
| **Affected Canonical Documents** | 30 (P6-AP-09) |
| **Proposed Classification** | Doctrine Candidate / Reasoning QA Candidate / Open Investigation |
| **Current Capture Status** | Partially captured in Doc 30 P6-AP-09 |
| **Recommended Handling** | Batch later after runtime relationship implementation evidence; avoid connection theater and forced imports |
| **Owner** | Program 2 architecture; Program 6 classification |
| **Review Tier** | Targeted |
| **Evidence Summary** | Doc 30 P6-AP-09; PR #144 gap analysis; PR #154 orphaned producers (some may be audit-only) |
| **Open Questions** | How to reduce gap-analysis false positives; whether runtime relationship awareness needs implementation before classification |
| **Status** | Open — awaiting implementation evidence |

### CIL-008 — Local Runner / Implementation-Worker / Retry Boundary

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-008 |
| **Cluster** | Local Runner / implementation-worker / retry boundary |
| **Short Title** | Runner/orchestrator overlaps; retry executor gap; task-packet consumer gap; evidence-linking gaps; worker interchangeability deferred |
| **Source Program Flag IDs** | P0-CIF-019, P2-CIF-020, P2-CIF-021, P5-CIF-001, P5-CIF-002, P5-CIF-003, P5-CIF-004, P5-CIF-005, P5-CIF-006, P5-CIF-009, P5-CIF-011, P5-CIF-013, P5-CIF-014, P5-CIF-015, P5-CIF-018, P5-CIF-019, P5-CIF-020, P6-CIF-017, P6-CIF-018, P7-CIF-012, P7-CIF-013 |
| **Source Programs** | P0, P2, P5, P6, P7 |
| **Affected Canonical Documents** | 40 (OI-002) |
| **Proposed Classification** | Open Investigation / Targeted Review Required / Program Owner Review Required |
| **Current Capture Status** | OI-002 investigation complete; no implementation authorized |
| **Recommended Handling** | Route to Program 5 for infrastructure review; do not implement retry/worker behavior until existing runners/orchestrators are reconciled |
| **Owner** | Program 5 infrastructure; Program 2 architecture; Program 7 operations; Program 0 if sequencing changes |
| **Review Tier** | Full |
| **Evidence Summary** | OI-002; Local Runner existing code; runner/orchestrator overlaps identified; retry executor/counter do not exist; P5-CIF-011 failure classification taxonomy overlap |
| **Open Questions** | Program 0/5 milestone sequencing; whether retry executor is in scope; runner consolidation timing |
| **Status** | Open — awaiting Program 5 review |

### CIL-009 — Windows / Cloud / Local Execution Evidence Lanes

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-009 |
| **Cluster** | Windows / cloud / local execution evidence lanes |
| **Short Title** | PR #151 Windows path fix; Devin cloud vs CLI local vs Windows Local Runner evidence distinction |
| **Source Program Flag IDs** | P0-CIF-020, P2-CIF-022, P5-CIF-007, P5-CIF-008, P5-CIF-016, P6-CIF-024, P7-CIF-007 |
| **Source Programs** | P0, P2, P5, P6, P7 |
| **Affected Canonical Documents** | 40 (OI-001) |
| **Proposed Classification** | Traceability / Open Investigation / Reasoning QA Candidate |
| **Current Capture Status** | BHV-028 captured; OI-001 awaits operator Windows re-run |
| **Recommended Handling** | Track as operational/infrastructure evidence; do not treat Devin cloud proof, Devin CLI local proof, and Windows Local Runner proof as equivalent; do not treat Windows path compatibility as doctrine |
| **Owner** | Program 5 infrastructure; Program 7 operations |
| **Review Tier** | Targeted |
| **Evidence Summary** | PR #151; 5072 tests passed; PureWindowsPath regression tests; Windows probe plan produced |
| **Open Questions** | Whether to formalize evidence-lane separation; operator Windows re-run still pending |
| **Status** | Open — awaiting operator action |

### CIL-010 — Devin Operational QA

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-010 |
| **Cluster** | Devin operational QA |
| **Short Title** | Compute mode; pre-review self-audit; Purpose-to-Workflow Reconciliation; PR naming; role-boundary discipline; object navigation |
| **Source Program Flag IDs** | P0-CIF-003, P0-CIF-015, P0-CIF-016, P0-CIF-017, P2-CIF-013, P2-CIF-014, P2-CIF-024, P6-CIF-010, P6-CIF-011, P6-CIF-029, P6-CIF-030, P7-CIF-001, P7-CIF-002, P7-CIF-005, P7-CIF-014, P7-CIF-017 |
| **Source Programs** | P0, P2, P6, P7 |
| **Affected Canonical Documents** | 60 |
| **Proposed Classification** | Reasoning QA Candidate / Communication Record / Traceability |
| **Current Capture Status** | Partially captured in Doc 60; compute mode and reconciliation gate used in directives but not formalized |
| **Recommended Handling** | Keep operational unless repeated evidence proves it belongs in Document 60; P6-CIF-030 suggests routing unresolved issues to Doc 40 |
| **Owner** | Program 7 operations; Program 1 task-packet execution; Program 6 classification if repeated |
| **Review Tier** | Targeted |
| **Evidence Summary** | Doc 60 Reasoning QA framework; compute mode used in PRs #151–#155; P7-CIF-017 object navigation evidence usability |
| **Open Questions** | Whether compute mode and reconciliation gate belong in Doc 60; whether unresolved issues should be routed to Doc 40 |
| **Status** | Open — awaiting Program 7/6 classification |

### CIL-011 — GPR / Global Work Identifier

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-011 |
| **Cluster** | GPR / global work identifier |
| **Short Title** | Global Axiom work sequence vs repo-local GitHub PR numbers; convention only, not implemented |
| **Source Program Flag IDs** | P0-CIF-018, P2-CIF-019, P6-CIF-012, P7-CIF-010 |
| **Source Programs** | P0, P2, P6, P7 |
| **Affected Canonical Documents** | None |
| **Proposed Classification** | Open Investigation / Communication Record / Traceability |
| **Current Capture Status** | Not implemented; used as convention only |
| **Recommended Handling** | Mark as unimplemented; do not create a GPR registry in this PR |
| **Owner** | Program 1 and Program 7 for operational need; Program 6 classification; Program 0 if operating model changes |
| **Review Tier** | Light |
| **Evidence Summary** | GPR numbers (e.g., "PR #155") used in commit/PR titles; no registry exists |
| **Open Questions** | Whether GPR should become a formal ledger |
| **Status** | Open — GPR is NOT implemented |

### CIL-012 — README / SetParameterValue Capability Drift

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-012 |
| **Cluster** | README / SetParameterValue capability drift |
| **Short Title** | SetParameterValue canonical-current but README lags; documentation/source-of-truth drift |
| **Source Program Flag IDs** | P0-CIF-021, P2-CIF-018, P6-CIF-014, P7-CIF-011 |
| **Source Programs** | P0, P2, P6, P7 |
| **Affected Canonical Documents** | README.md; 20 |
| **Proposed Classification** | Traceability / Reasoning QA Candidate / Open Investigation |
| **Current Capture Status** | RF-005 tracks this in Doc 40 |
| **Recommended Handling** | Track as RF-005 / documentation drift; do not treat README as authoritative over implementation/canonical evidence |
| **Owner** | Program 1 for concrete documentation correction; Program 6 if source-of-truth issue repeats |
| **Review Tier** | Light |
| **Evidence Summary** | SetParameterValueCapability.cs, ParameterEditService.cs, runbook, BHV-023/024; README lists only 3 capabilities |
| **Open Questions** | Who owns README update |
| **Status** | Open — separate Light Update PR recommended |

### CIL-013 — M3 / M5 / Future Milestone Sequencing

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-013 |
| **Cluster** | M3 / M5 / future milestone sequencing |
| **Short Title** | M3 needed before mature evidence interpretation; M5 non-mutating and deferred; stabilization before semantic expansion |
| **Source Program Flag IDs** | P0-CIF-002, P0-CIF-011, P0-CIF-012, P2-CIF-006, P2-CIF-015, P2-CIF-016, P6-CIF-013, P6-CIF-027, P6-CIF-028, P7-CIF-016 |
| **Source Programs** | P0, P2, P6, P7 |
| **Affected Canonical Documents** | 10 |
| **Proposed Classification** | Strategic Review / Open Investigation / Traceability |
| **Current Capture Status** | Partially captured in Doc 10 M2/M3/M5 sections |
| **Recommended Handling** | Route to Program 0 for sequencing; keep M3 as next after stabilization; keep M5 non-mutating and deferred; evidence weighting with M3 semantics must not become promotion doctrine |
| **Owner** | Program 0 strategic synthesis; Program 2 architecture; Program 6 classification |
| **Review Tier** | Full |
| **Evidence Summary** | Doc 10 v2 milestone sections; P6-CIF-013 construction-phase marker; P6-CIF-027/028 trace/evidence index before mature M5 |
| **Open Questions** | Whether evidence index is M5 prerequisite; whether canonical repo seed slipped past M3 scope |
| **Status** | Open — Program 0 sequencing |

### CIL-014 — Primary/Mirror Repo State and Merge-State Mismatch

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-014 |
| **Cluster** | Primary/mirror repo state and merge-state mismatch |
| **Short Title** | Primary/mirror repo or active-main mismatch can mislead PR planning and self-model analysis |
| **Source Program Flag IDs** | P6-CIF-015, P6-CIF-016 |
| **Source Programs** | P6 |
| **Affected Canonical Documents** | None directly |
| **Proposed Classification** | Open Investigation / Reasoning QA Candidate / Traceability |
| **Current Capture Status** | Not formally captured |
| **Recommended Handling** | Track unless repeated repo-state mismatches affect PR planning or canonical accuracy; verify repo state before making assumptions |
| **Owner** | Program 7 operational repo-state process; Program 1 PR verification |
| **Review Tier** | Light |
| **Evidence Summary** | P6-CIF-015 primary/mirror alignment; P6-CIF-016 ExecutionReport merge-state mismatch |
| **Open Questions** | Whether this needs a formal process or is one-off |
| **Status** | Open — tracking |

### CIL-015 — Axiom / Capital Boundary

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-015 |
| **Cluster** | Axiom / Capital boundary |
| **Short Title** | Axiom and Capital must remain separate; do not mix paths, assumptions, examples, or project context |
| **Source Program Flag IDs** | P6-CIF-021 |
| **Source Programs** | P6 |
| **Affected Canonical Documents** | All potentially |
| **Proposed Classification** | Already Captured / No Immediate Action / Reasoning QA Candidate if violated |
| **Current Capture Status** | Captured in knowledge notes and project boundaries |
| **Recommended Handling** | Mark captured unless future PRs or prompts violate the boundary |
| **Owner** | Program 0 and Program 6; Program 7 for operational checks |
| **Review Tier** | None |
| **Evidence Summary** | Knowledge note "Axiom-platform project boundaries and repo rules"; no violations detected |
| **Open Questions** | None currently |
| **Status** | Captured — monitor for violations |

### CIL-016 — Learning Events Remain Candidate, Not Accepted Architecture

| Field | Value |
|-------|-------|
| **Ledger ID** | CIL-016 |
| **Cluster** | Learning Events remain candidate, not accepted architecture |
| **Short Title** | Learning Events useful as candidate concept but not accepted first-class architecture |
| **Source Program Flag IDs** | P6-CIF-020 |
| **Source Programs** | P6 |
| **Affected Canonical Documents** | 20; 30 |
| **Proposed Classification** | Open Investigation / Traceability |
| **Current Capture Status** | Not formally captured as decision |
| **Recommended Handling** | No action unless implementation evidence appears |
| **Owner** | Program 6 and Program 2 |
| **Review Tier** | Light |
| **Evidence Summary** | Learning Events referenced in review traceability but deferred during review cycles |
| **Open Questions** | None currently — deferred until implementation evidence |
| **Status** | Open — deferred |

## 6. Excluded / Not Carried Forward

| Source ID | Title | Reason |
|-----------|-------|--------|
| P6-CIF-022 | Program 3 and Program 4 Canonical Coverage Gaps | Superseded by operator clarification: Program 3 and Program 4 were not part of this Canonical Impact Flag inventory cycle and should not be represented as pending or missing. |

Program 3 and Program 4 were outside the scope of this reconciliation cycle and are not represented in this ledger.

## 7. Routing Rules

| Condition | Route to |
|-----------|----------|
| Affects strategy, milestones, product direction | Program 0 |
| Affects architecture, state model, evidence semantics | Program 2 |
| Affects Local Runner, infrastructure, multi-agent | Program 5 |
| Affects doctrine, constitutional, canonical classification | Program 6 |
| Affects Devin ops, review QA, compute mode, worker process | Program 7 |
| PR execution, implementation sequencing | Program 1 |

## 8. Review Tiers

| Tier | When to use | Approver |
|------|-------------|----------|
| None | Already captured; no action needed | N/A |
| Light | Traceability record or trivial update | File owner |
| Targeted | Substantive change to one file | Responsible program |
| Full | Cross-program or doctrine-level | Program 0 + Program 6 |

## 9. Non-Goals

- This ledger does not rewrite doctrine.
- This ledger does not broadly update canonical documents 10–60.
- This ledger does not classify every flag as final doctrine.
- This ledger does not implement GPR.
- This ledger does not treat Devin compute mode as doctrine.
- This ledger does not treat Windows path compatibility as doctrine.
- This ledger does not treat readiness thresholds as promotion doctrine.
- This ledger does not treat Program 7 operational sequencing as Program 0 strategic approval.
- This ledger does not treat README as authoritative over implementation/canonical state.
- This ledger does not treat every disconnected component as canonical impact.
- This ledger does not confuse traceability with doctrine.
- Program 3 and Program 4 are out of scope for this reconciliation cycle.
- This ledger does not perform one canonical update per flag.
