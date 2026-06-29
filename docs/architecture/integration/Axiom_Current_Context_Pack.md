# Axiom Current Context Pack

Index of context, reconciliation, and self-awareness resources available to
Programs 0/1/2/5/6/7, Devin task packets, and future architecture-sensitive PRs.

This file is a **tracked static index** — it points to live and static sources.
It is not the live source of truth; run `axiom context-preflight` for the
current repo-derived state.

Last updated: PR #157 (Axiom Context Preflight, PR Purpose Map, and Live System Atlas v0).

---

## Live Context (Generated, Gitignored)

| Resource | How to access |
|----------|---------------|
| **Context Preflight Report** | `poetry run axiom context-preflight` → `artifacts/context_preflight/<run_id>/context_preflight.json` + `.md` |
| **System Atlas** | `poetry run axiom context-preflight` → `artifacts/context_preflight/<run_id>/system_atlas.json` + `.md` |
| **Context Basis Template** | Included in context-preflight JSON output under `context_basis_template` — paste into PR bodies |

These artifacts reflect the repo at the time of generation. They are gitignored
and not committed.

---

## Tracked Reference Documents (Committed, Versioned)

| Resource | Path |
|----------|------|
| **PR Purpose Map** | `docs/architecture/integration/PR_Purpose_Map_v0.md` |
| **Duplicate / Alias Map** | `docs/architecture/integration/Duplicate_Alias_Map_v0.md` |
| **Evidence Producer Inventory** | `docs/architecture/integration/Evidence_Producer_Inventory_and_Consumer_Mapping_v1.md` |
| **M2 Evidence Promotion Packet** | `docs/architecture/integration/M2_Evidence_Promotion_Validation_Packet.md` |
| **M3 Purpose Layer Packet** | `docs/architecture/integration/M3_Purpose_Layer_Validation_Packet.md` |
| **M4 Execution Chain Packet** | `docs/architecture/integration/M4_Execution_Chain_Validation_Packet.md` |
| **Integration README** | `docs/architecture/integration/README.md` |

---

## Canonical Knowledge Base (Committed, Versioned)

| Resource | Path |
|----------|------|
| **KB Readme** | `docs/canonical_knowledge_base/00_Readme.md` |
| **Strategic Context** | `docs/canonical_knowledge_base/10_Current_Strategic_Context.md` |
| **Organizational State** | `docs/canonical_knowledge_base/20_Current_Organizational_State.md` |
| **Architectural Principles** | `docs/canonical_knowledge_base/30_Architectural_Principles.md` |
| **Open Investigations** | `docs/canonical_knowledge_base/40_Open_Investigations.md` |
| **Organizational Communications** | `docs/canonical_knowledge_base/50_Organizational_Communications.md` |
| **Reasoning Quality Assurance** | `docs/canonical_knowledge_base/60_Reasoning_Quality_Assurance.md` |

---

## Canonical Impact Ledger (Committed, Versioned)

| Resource | Path |
|----------|------|
| **Canonical Impact Ledger** | `docs/canonical_knowledge_base/impact_ledger/Canonical_Impact_Ledger.md` |
| **Program Inventory Reconciliation** | `docs/canonical_knowledge_base/impact_ledger/Program_Inventory_Reconciliation_PR155.md` |

---

## Operational Logs (Committed, Versioned)

| Resource | Path |
|----------|------|
| **Behavior Change Ledger** | `docs/logs/behavior-change-ledger.md` |
| **PR Review Ledger** | `docs/logs/pr-review-ledger.md` |

---

## Runbooks (Committed, Versioned)

| Resource | Path |
|----------|------|
| **Local Runner** | `docs/runbooks/local-runner-runbook.md` |
| **Validation Loop** | `docs/runbooks/validation-loop-runbook.md` |
| **Evidence Log Maintenance** | `docs/runbooks/evidence-log-maintenance.md` |
| **Behavior Regression** | `docs/runbooks/behavior-regression-runbook.md` |
| **PR Evidence Snapshot** | `docs/runbooks/pr-evidence-snapshot-runbook.md` |
| **Grid Learning Loop** | `docs/runbooks/grid-learning-loop-runbook.md` |
| **Model Inventory** | `docs/runbooks/model-inventory-runbook.md` |
| **Set Parameter Value** | `docs/runbooks/set-parameter-value-runbook.md` |
| **Revit 2027 Compatibility** | `docs/runbooks/revit-2027-compatibility-runbook.md` |
| **Revit Multi-Version** | `docs/runbooks/revit-multi-version-runbook.md` |
| **Windows Revit Build/Test** | `docs/runbooks/windows-revit-build-test-runbook.md` |
| **Windows Self-Hosted Runner** | `docs/runbooks/windows-revit-self-hosted-runner.md` |

---

## Usage Protocol

1. **Before any architecture-sensitive PR:** run `poetry run axiom context-preflight` and paste the Context Basis template into the PR body.
2. **Before adding a new component:** check the Duplicate/Alias Map for existing overlaps.
3. **Before building near an existing system:** check the PR Purpose Map for what each PR does and its "check before building near" guidance.
4. **For evidence topology:** check the Evidence Producer Inventory.
5. **For cross-program impact:** check the Canonical Impact Ledger.
