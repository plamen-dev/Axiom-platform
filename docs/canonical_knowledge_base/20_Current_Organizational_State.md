# Current Organizational State

| Field | Value |
|-------|-------|
| **Title** | Current Organizational State |
| **Status** | Seeded (v1) — program roster supported by directive; milestone/state details supported by repo evidence; live program staffing is **Source Needed** |
| **Owner / Responsible Program** | Program 7 — Engineering Operations |
| **Last Updated** | 2026-06-23 |
| **Source / Provenance** | PR #152 directive (program roster); `README.md` (validated milestone); `docs/logs/behavior-change-ledger.md`; `docs/architecture/integration/`; recent merged PRs #146–#151. |
| **Purpose** | Provide a durable snapshot of current programs, ownership boundaries, and where implementation stands. |

## Program roster and ownership

| Program | Charter | Owns | Does **not** own |
|---------|---------|------|------------------|
| Program 0 | Vision and Strategy | Strategic direction, canonical strategy | Doctrine custody, PR execution |
| Program 1 | PR Execution Factory | PR execution, task-packet production | The canonical knowledge base / doctrine |
| Program 2 | Autonomous Engineering OS | Engineering OS direction | Strategy authorship |
| Program 3 | Operator Cockpit Design | Operator UX/cockpit | Runtime capability logic |
| Program 4 | BIM Intelligence Platform | BIM intelligence | Local Runner / infra |
| Program 5 | Local Runner and Multi-Agent Infrastructure | Execution infra, Local Runner | Capability semantics, doctrine |
| Program 6 | Knowledge, Constitution, and Doctrine | Canonical knowledge base, doctrine | PR execution |
| Program 7 | Engineering Operations | Org-state, ops cadence | Strategy authorship |

> Boundary note: Program 1 owns PR execution and task-packet production, **not**
> the whole canonical knowledge base. Doctrine custody is Program 6.

## Validated capability milestone (repo evidence)

From `README.md`, validated using five Snowdon Towers source models
(architectural, electrical, HVAC, plumbing, structural):

- 5 Snowdon source models
- 278 successful full-plan category exports
- 0 duplicate export paths
- 6,444 unique parameter/property definitions
- 1,878 unique parameter names
- 1,748 imported runs
- 20/20 priority categories executed, 20/20 with definitions

## Current Revit capabilities

`CreateGrids`, `CreateLevels`, `InventoryModel`, `SetParameterValue`.

- `InventoryModel` is the base for Category / Parameter Discovery.
- `SetParameterValue` is the first Primitive Action Validation candidate. It is a
  registered, wired capability (`SetParameterValueCapability.cs`,
  `ParameterEditService.cs`, `docs/runbooks/set-parameter-value-runbook.md`,
  ledger BHV-023/BHV-024). Note: `README.md` currently lists only the first three
  capabilities and lags this canonical state — routed as RF-005 in
  `40_Open_Investigations.md`.

## Recent implementation state (merged PRs)

Recent merged sequence relevant to current state (see `docs/logs/pr-review-ledger.md`
and `behavior-change-ledger.md` for the authoritative trace):

- PR #146 — Execution Chain Orchestrator v1
- PR #147 — Evidence to Promotion Loop v1
- PR #148 — Evidence Promotion Safety Hardening v1 (BHV-027)
- PR #149 — Devin PR Self-Audit and CLI Testing Skill Update v1
- PR #150 — testing-axiom-cli skill: execution-chain + evidence-promotion checklists
- PR #151 — Windows Artifact Path Compatibility Fix v1 (BHV-028)

## Platform / compatibility state

- Current baseline: `baseline-001-revit-2024-capability-platform` (Revit 2024).
- Revit 2027 compatibility is kept isolated and must preserve the 2024 baseline
  unless explicitly merged.
- Artifact persistence is now Windows-compatible (PR #151); a true on-Windows
  re-run of the execution-chain / evidence-promotion CLIs by the operator is the
  remaining validation step (see `40_Open_Investigations.md`).

## Current Status / Source Needed

Live program staffing, current sprint/cycle commitments, and program-by-program
status beyond the repo-evidenced milestones above are **not repo-resident**.
Program 7 should supply the current operating snapshot via PR.
