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

## 2. Source-of-Truth Rule

This ledger is a **working reconciliation tool**, not canonical truth. Final canonical
updates to documents `10`–`60` require Program 6 classification and appropriate review
per `00_Readme.md` update policy. Until classified, entries here are provisional.

## 3. Ledger Status

- Programs received: **0, 2, 5, 6, 7**
- Programs pending: **3, 4** (inventories not received; entries must not be invented)
- Classification authority: **Program 6**
- Strategic synthesis: **Program 0** (where strategy/milestone/product affected)
- Operational review: **Program 7** (where Devin/worker/process affected)

## 4. How to Use This Ledger

1. Find the cluster relevant to your concern.
2. Check the proposed classification and recommended handling.
3. If you are the owner program, review and confirm or reclassify.
4. When a batch of items is ready, create a canonical maintenance PR (not one per flag).
5. Mark items `Closed` when the canonical update PR is merged.

## 5. Proposed Classification Labels

| Label | Meaning |
|-------|---------|
| No Canonical Change | Already captured or not canonical material |
| Traceability Only | Record in traceability ledger; no canonical doc edit |
| Light Update | Typo, link, date, status — trivial PR |
| Open Investigation | Needs more evidence before classification |
| Doctrine Candidate | May become doctrine; requires Program 6 evaluation |
| Communication Record | Record in `50_Organizational_Communications.md` |
| Reasoning QA Candidate | May become QA gate; requires Program 7/6 evaluation |
| Immediate Canonical Update | Clear, uncontroversial update ready now |
| Targeted Review Required | Needs specific program owner review |
| Program Owner Review Required | Needs the listed program to confirm |

## 6. Reconciled Ledger

### Cluster 1 — Canonical Source-of-Truth and Library Mirror Boundary

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-001 | Repo canonical source wins over ChatGPT Library | P1-ACC-09, P2-ACC-08, P6-ACC-04/05, P7-ACC-10/11, P6-MOD-07, P6-CONST-04 | P0, P2, P5, P6, P7 | 00_Readme | No Canonical Change | Captured in 00_Readme.md source-of-truth rules (PR #152) | None — already repo-resident | Program 6 | None | PR #152 00_Readme.md rules 1–3 | Overlaps with stable-filename rule (CIL-002) | None | None | Captured |
| CIL-002 | Stable filenames (no _v# suffixes) | P6-MOD-07, P6-CONST-04, P5-FINAL-01/02, P6-FINAL-01/02, P7-FINAL-01/02 | P5, P6, P7 | 00_Readme | No Canonical Change | Captured in 00_Readme.md rule 4 | None — already repo-resident | Program 6 | None | PR #152 00_Readme.md rule 4 | Related to CIL-001 | None | None | Captured |
| CIL-003 | Canonical source / traceability separation | P1-ACC-09, P2-ACC-08, P5-FINAL-01/05, P6-ACC-04, P6-CONST-04, P7-FINAL-04 | P0, P2, P5, P6, P7 | 00_Readme; 30 | No Canonical Change | Captured in 00_Readme.md traceability section and P6-AP-10 in Doc 30 | None — strongest cross-program consensus item | Program 6 | None | All 5 programs converged independently | None | None | None | Captured |
| CIL-004 | Canonical Impact Flag batching workflow | P6-MOD-06, 00_Readme rule 6 | P6 | 00_Readme | No Canonical Change | Captured in 00_Readme.md rule 6 and review policy | None — this ledger is the implementation | Program 6 | None | 00_Readme.md rule 6 | None | None | None | Captured |
| CIL-005 | PR #152 completeness — seed did not backfill all flags | P1 PR execution context | P1 | 00_Readme; 40 | Traceability Only | Partially captured via RF-001..RF-005 in Doc 40 | Acknowledge in this ledger; do not treat as failure | Program 1 | Light | PR #152 was a seed, not a backfill | None | Whether a follow-up canonical maintenance PR is needed | Program 6 review | Open |

### Cluster 2 — M4 Execution-Chain Proof and Integration Phase Transition

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-006 | M4 as major behavioral integration proof | P1-ACC-05, P2-ACC-05, P7-ACC-06, P0-MOD-02, P0-MOD-04 | P0, P1, P2, P7 | 10 | No Canonical Change | Captured in Doc 10 M4 section (v2) | None — consensus already in Doc 10 | Program 0 | None | PR #146 execution-chain orchestrator; all programs converged | None | None | None | Captured |
| CIL-007 | Execution Graph vs Execution Run distinction | P5-MOD-02, P7-ACC-07 | P2, P5, P7 | 20 | No Canonical Change | Captured in Doc 20 (v3) Execution Run section | None — already distinguished | Program 2 | None | Doc 20 v3 review traceability; P5-MOD-02 accepted | None | None | None | Captured |
| CIL-008 | Integration Phase is current strategic phase | P1-ACC-01, P2-ACC-01, P6-ACC-02, P7-ACC-02 | P0, P1, P2, P6, P7 | 10 | No Canonical Change | Captured in Doc 10 Current Strategic Phase | None — strongest consensus | Program 0 | None | All programs converged | None | None | None | Captured |
| CIL-009 | Runtime ID-flow and persisted disk resolution | P1 PR #146 execution context | P1, P2 | 30 | Traceability Only | Partially captured via M4 validation packet | Record in behavior-change ledger (BHV-026); not a doc-level update | Program 1 | Light | PR #146 execution-chain orchestrator | May overlap CIL-006 | Whether runtime ID-flow needs Doc 20 update | Program 2 review | Open |

### Cluster 3 — M2 Evidence-to-State Proof and Evidence-Safety Hardening

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-010 | PR #147 narrow M2 evidence-to-state proof | P1 PR execution, BHV-026/027 | P1, P2 | 30 (P6-AP-07) | No Canonical Change | Captured in M2 validation packet and behavior ledger BHV-026 | None — evidence already feeds state for execution-chain slice | Program 1 | None | PR #147; tests H1-H5 | Related to CIL-011 | None | None | Captured |
| CIL-011 | PR #148 duplicate/conflict evidence safety | BHV-027 | P1 | 30 (P6-AP-07) | Traceability Only | Captured in behavior ledger BHV-027 | Record as hardening; not a new principle | Program 1 | Light | PR #148; duplicate/conflict/accumulation tests | Related to CIL-010 | None | None | Captured |
| CIL-012 | EVID-001 partial closure — narrow M2 slice only | EVID-001, BHV-027 line 491, PR #154 | P1, P2 | 40 | Targeted Review Required | Partially captured in OI-001 area and PR #154 inventory | Update Doc 40 to note EVID-001 status after PR #154 | Program 1 / P6 | Targeted | PR #154 evidence producer inventory confirms model_health orphan | None | Whether to add EVID-001 as formal OI entry | Program 6 classify | Open |
| CIL-013 | Readiness threshold interpretation is not doctrine | P6-MOD-11, classification rules | P6 | 30 | No Canonical Change | Not in danger — Doc 30 does not contain readiness thresholds | None — classification rule prevents overclaiming | Program 6 | None | No readiness thresholds in Doc 30 | None | None | None | Not applicable |

### Cluster 4 — CLI Validation Evidence Recorder and Durable Validation Proof

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-014 | PR #153 CLI validation evidence recorder | BHV-029 | P1 | None directly | Traceability Only | Captured in behavior ledger BHV-029 | No canonical doc change; traceability record sufficient | Program 1 | Light | PR #153; 26 tests; CLI smoke M4 + M2 plans | None | None | None | Captured |
| CIL-015 | Validation artifact vs state-changing evidence distinction | P6-AP-07, PR #154 Sec 2 | P1, P2, P6 | 30 | No Canonical Change | Captured in Doc 30 P6-AP-07 ("evidence must feed state") and PR #154 inventory | None — distinction already articulated | Program 6 | None | PR #154 distinguishes read-only, lifecycle, and state-mutating consumers | None | None | None | Captured |
| CIL-016 | Axiom-native evidence vs Devin/manual screenshots | OI-003 | P5, P6 | 40 | Open Investigation | Captured in OI-003 (durability policy pending) | Awaits policy decision per OI-003 | Program 5 / P6 | Targeted | OI-003 investigation complete; policy decision pending | None | Durability policy for external Devin URLs and recordings | Program 5/6 decision | Open |

### Cluster 5 — Evidence Producer/Consumer Mapping and EVID-001 Residual Scope

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-017 | Model-health label — confirmed producer with orphaned output | PR #154 Sec 2 Producer 3 | P1, P2 | None directly | Traceability Only | Captured in PR #154 inventory | No canonical doc change; implementation follow-up separate | Program 1 | Light | model_health.py produces axiom_capability_readiness.json; server_tools read-only | Related to CIL-012 | None | Implementation PR pending Program 0 approval | Open |
| CIL-018 | pass_fail.json producers lack confidence consumer | PR #154 Sec 2 Producers 4-5 | P1, P2 | None directly | Open Investigation | Captured in PR #154 inventory | Needs doctrine decision on which evidence types affect confidence | Program 2 / P6 | Targeted | EvidenceRunner + CapabilityRunner produce pass_fail.json; scanned by CapStateReg but no confidence path | Related to CIL-012 | Whether all pass_fail outcomes should affect confidence | Program 6 doctrine decision | Open |
| CIL-019 | Current consumer vs missing consumer mapping | PR #154 Sec 3 | P1 | None directly | Traceability Only | Captured in PR #154 evidence inventory | No canonical doc change; working reference for implementation | Program 1 | None | PR #154 Consumer Mapping table | None | None | None | Captured |

### Cluster 6 — Runtime Relationship Awareness vs Static Import Metrics

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-020 | Executable relationships > structural inventory | P6-AP-09, P0-MOD-06, P2-ACC-12, P2-MOD-06, P5-ACC-14 | P0, P2, P5, P6 | 30 | No Canonical Change | Captured in Doc 30 P6-AP-09 | None — principle already codified | Program 6 | None | All programs converged on this principle | None | None | None | Captured |
| CIL-021 | Gap-analysis false positives and connection theater | P1 PR execution context, PR #154 Sec 6 | P1, P2 | None directly | Traceability Only | Partially captured in PR #154 Sec 6 (Candidate E) and OI-002 | Avoid forced static imports; validated runtime executable relationships | Program 2 | Light | PR #144 gap analysis identified orphaned producers; some may be audit-only (not real gaps) | Related to CIL-020 | How to reduce gap-analysis false positives | Future investigation | Open |

### Cluster 7 — Local Runner / Implementation-Worker / Retry Boundary

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-022 | Local Runner / implementation-worker boundary | OI-002, P5-BOUND-02, P5-MOD-10 | P5 | 40 | No Canonical Change | Captured in OI-002 (investigation complete; no implementation authorized) | Preserve OI-002 as open until Program 0/5 approve | Program 5 | None | Investigation complete; overlapping concepts identified | None | Program 0/5 milestone sequence approval | Program 5 review | Open |
| CIL-023 | Retry recommendation vs retry executor gap | OI-002 | P5 | None directly | Open Investigation | Identified in investigation but not repo-resident | Needs separate investigation or implementation PR when approved | Program 5 | Targeted | Retry executor and counter do not yet exist | Related to CIL-022 | Whether retry executor is in scope for current phase | Program 0 sequencing | Open |
| CIL-024 | No Program 1 task-packet consumer | OI-002 | P1, P5 | None directly | Traceability Only | Identified in investigation | Not a canonical doc change; implementation gap | Program 1 / P5 | Light | Task-packet consumer not built | Related to CIL-022 | Whether this is M-next or deferred | Program 0 sequencing | Open |

### Cluster 8 — Windows / Cloud / Local Execution Evidence Lanes

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-025 | Windows artifact path compatibility fix | BHV-028, OI-001 | P1, P5 | 40 (OI-001) | No Canonical Change | Captured in BHV-028 and OI-001 | Code fix merged (PR #151); OI-001 awaits Windows re-run | Program 5 | None | PR #151; 5072 tests passed; PureWindowsPath regression tests added | None | Operator Windows re-run still pending | Operator action | Open |
| CIL-026 | Devin cloud vs local vs Windows evidence lanes | P5 probe context | P5, P7 | None directly | Open Investigation | Partially captured in OI-001 and Program 5 probe plan | Environment-specific proof boundaries need doc when evidence | Program 5 | Targeted | Windows probe plan produced; cloud/local separation identified | Related to CIL-025 | Whether to formalize evidence-lane separation | Program 5 investigation | Open |

### Cluster 9 — Devin Operational QA

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-027 | Recommended Devin Compute Mode | P7 directive context | P7 | 60 | Reasoning QA Candidate | Referenced in PR directives; not formalized in Doc 60 | Evaluate whether compute-mode guidance belongs in Doc 60 or remains directive-only | Program 7 / P6 | Targeted | Used in PR #151, #152, #153, #154, #155 directives | None | Is compute mode doctrine or operational guidance? | Program 7/6 classify | Open |
| CIL-028 | Pre-review self-audit gate | P7 directive context, Doc 60 | P7 | 60 | No Canonical Change | Partially captured in Doc 60 Reasoning QA | Doc 60 already contains self-audit principles; specific per-PR checklists remain in directives | Program 7 | None | Doc 60 Reasoning QA framework | None | None | None | Captured |
| CIL-029 | Purpose-to-Workflow Reconciliation gate | P7 directive context | P7 | 60 | Reasoning QA Candidate | Referenced in PR directives; not formalized in Doc 60 | Evaluate whether reconciliation gate belongs in Doc 60 | Program 7 / P6 | Targeted | Used in all recent PR directives | Related to CIL-028 | Whether to formalize or keep as directive-only | Program 7/6 classify | Open |
| CIL-030 | Testing-axiom-cli skill updates | PR #149, #150 | P1, P7 | None | No Canonical Change | Captured in repo `.agents/skills/` | Not canonical doc material; operational tooling | Program 1 | None | Skill file updated; not canonical | None | None | None | Captured |
| CIL-031 | PR naming and merge-material discipline | P1 directive context | P1, P7 | None | Traceability Only | Operational practice; not canonical | Record as operational convention, not doctrine | Program 1 / P7 | None | PR naming convention observed across PRs #146–#155 | None | None | None | Not applicable |

### Cluster 10 — GPR / Global Work Identifier

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-032 | GPR distinction — global Axiom sequence vs GitHub PR numbers | P1 directive context | P1, P7 | None | Traceability Only | Not implemented; used as convention only | Preserve as traceability-only convention; do not implement registry | Program 1 | None | GPR numbers (e.g., "PR #155") used in commit/PR titles but no registry exists | None | Whether GPR should become a formal ledger | Program 0/7 decision | Open |

### Cluster 11 — README / SetParameterValue Capability Drift

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-033 | README lags behind SetParameterValue implementation | RF-005, Devin Review PR #152 | P1, P4, P7 | README.md; 20 | Light Update | Captured in RF-005 (Doc 40) | Separate PR to update README; canonical state (Doc 20) is correct | Program 4 / P7 | Light | SetParameterValueCapability.cs, ParameterEditService.cs, runbook, BHV-023/024 exist; README lists only 3 capabilities | None | Who owns README update | Program 4/7 PR | Open |

### Cluster 12 — M3 / M5 / Future Milestone Sequencing

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-034 | M3 semantic context needed before mature evidence interpretation | P1-ACC-06/07, P2-ACC-06, P7-ACC-07/08 | P0, P1, P2, P7 | 10 | No Canonical Change | Captured in Doc 10 M2/M3 sections with active-risk language | None — M3 preserved as active milestone | Program 0 | None | All programs converged; Doc 10 v2 includes risk language | Related to CIL-035 | None | None | Captured |
| CIL-035 | M5 deferred — needs stronger integration evidence first | P1-ACC-08, P7-ACC-09 | P0, P1, P7 | 10 | No Canonical Change | Captured in Doc 10 M5 section | None — M5 kept cautious | Program 0 | None | Doc 10 v2; caution against premature abstraction | Related to CIL-034 | None | None | Captured |
| CIL-036 | Trace/evidence index before mature M5 | P2-ARCH-03/05 | P2 | None directly | Open Investigation | Not formally captured | Future investigation when M5 approaches | Program 2 | Targeted | Organizational State underdefined (P2-ARCH-03) | None | Whether evidence index is M5 prerequisite | Program 0 sequencing | Open |

### Cluster 13 — Program Coverage Gaps

| CIL ID | Short Title | Source Program Flag IDs | Source Programs | Affected Docs | Proposed Classification | Current Capture Status | Recommended Handling | Owner | Review Tier | Evidence Summary | Duplicate/Overlap | Open Questions | Next Action | Status |
|--------|-------------|------------------------|-----------------|---------------|------------------------|----------------------|---------------------|-------|-------------|-----------------|-------------------|----------------|-------------|--------|
| CIL-037 | Program 3 inventory not received | None | N/A | All potentially | Program Owner Review Required | Not received | Do not invent; mark pending; request when ready | Program 3 | Targeted | No inventory submitted | None | When will Program 3 submit? | Request from Program 3 | Pending |
| CIL-038 | Program 4 inventory not received | None | N/A | All potentially | Program Owner Review Required | Not received | Do not invent; mark pending; request when ready | Program 4 | Targeted | No inventory submitted | None | When will Program 4 submit? | Request from Program 4 | Pending |

## 7. Open Addenda / Missing Inventories

| Program | Status | Expected Content Areas |
|---------|--------|----------------------|
| Program 3 — Operator Cockpit Design | **Not received** | UI/UX canonical impacts, operator workflow, cockpit architecture |
| Program 4 — BIM Intelligence Platform | **Not received** | Revit capabilities, BIM workflow, capability promotion, README ownership |

These will be added as addenda when received. Do not invent content for missing programs.

## 8. Routing Rules

| Condition | Route to |
|-----------|----------|
| Affects strategy, milestones, product direction | Program 0 |
| Affects architecture, state model, evidence semantics | Program 2 |
| Affects Local Runner, infrastructure, multi-agent | Program 5 |
| Affects doctrine, constitutional, canonical classification | Program 6 |
| Affects Devin ops, review QA, compute mode, worker process | Program 7 |
| Affects README, capabilities, Revit workflow | Program 4 |
| Affects operator UI/cockpit | Program 3 |
| PR execution, implementation sequencing | Program 1 |

## 9. Review Tiers

| Tier | When to use | Approver |
|------|-------------|----------|
| None | Already captured; no action needed | N/A |
| Light | Traceability record or trivial update | File owner |
| Targeted | Substantive change to one file | Responsible program |
| Full | Cross-program or doctrine-level | Program 0 + Program 6 |

## 10. Non-Goals

- This ledger does not rewrite doctrine.
- This ledger does not broadly update canonical documents 10–60.
- This ledger does not classify every flag as final doctrine.
- This ledger does not implement GPR.
- This ledger does not treat Devin compute mode as doctrine.
- This ledger does not treat readiness thresholds as promotion doctrine.
- This ledger does not invent Program 3 or Program 4 inventories.
- This ledger does not perform one canonical update per flag.
