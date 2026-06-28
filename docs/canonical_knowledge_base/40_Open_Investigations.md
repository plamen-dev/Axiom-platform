# Open Investigations

| Field | Value |
|-------|-------|
| **Title** | Open Investigations and Routed Follow-ups |
| **Status** | Seeded (v1) — live list; entries below are supported by repo evidence and recent program work |
| **Owner / Responsible Program** | Program 5 / Program 6 (by topic) |
| **Last Updated** | 2026-06-23 |
| **Source / Provenance** | Program 5 investigation work; PR #151; this canonical seed (PR #152). |
| **Purpose** | Track open investigations and content that must be supplied later, so gaps are explicit and routed rather than silently filled. |

## How to use this file

Each entry has: a short title, the responsible program, current status, and the
disposition (what unblocks it). Closed entries should be moved to the relevant
traceability ledger in `docs/logs/`, not kept here indefinitely.

## Open investigations

### OI-001 — Windows execution-chain / evidence-promotion operator re-run
- **Program:** 5
- **Status:** Open (code fix merged; on-Windows confirmation pending).
- **Context:** PR #151 fixed POSIX-only artifact path containment that false-failed
  on Windows. Ubuntu validation and `PureWindowsPath` regression tests pass.
- **Unblocks when:** the operator re-runs on Windows: `execution-chain-run`,
  `capability-evidence-apply`, Local Runner `git_status`/`ruff`, and the targeted
  `test_execution_chain_orchestrator` / `test_evidence_promotion` suites.

### OI-002 — Local Runner / Implementation Worker boundary reconciliation
- **Program:** 5
- **Status:** Open (investigation complete; no implementation authorized).
- **Context:** Investigation found substantial existing infrastructure and flagged
  overlapping orchestrator/runner concepts; a retry executor/counter and a
  task-packet consumer do not yet exist.
- **Unblocks when:** Program 0/5 approve a milestone sequence. The investigation
  report itself is **not repo-resident** (produced as a Devin operational artifact);
  if it should become canonical, route it in via a future docs PR.

### OI-003 — Devin operational evidence / object navigation
- **Program:** 5 / 6
- **Status:** Open (investigation complete; policy decision pending).
- **Context:** Existing structures cover most Devin operational data categories.
  Primary gaps: durability policy for external Devin URLs and large binary
  recordings; linkage of self-audit/reconciliation answers and retry sequences.
- **Unblocks when:** a decision on whether `artifacts/` is ephemeral or durable,
  plus a policy for external-link preservation.

## Routed follow-ups (canonical content not yet repo-resident)

| Ref | Missing content | Owner | Destination |
|-----|-----------------|-------|-------------|
| RF-001 | Full Program 0 strategic narrative (market framing, sequencing, metrics, horizons) | Program 0 | `10_Current_Strategic_Context.md` |
| RF-002 | Live program staffing and current cycle commitments | Program 7 | `20_Current_Organizational_State.md` |
| RF-003 | Durable organizational communications / decision log content | Program 0 / 7 | `50_Organizational_Communications.md` |
| RF-004 | Whether prior Program 5 investigation reports should be canonicalized | Program 5 / 6 | this file / new docs PR |
| RF-005 | `README.md` "Current Capabilities" lists only `CreateGrids`/`CreateLevels`/`InventoryModel` and omits `SetParameterValue`, which is a registered, wired capability (`SetParameterValueCapability.cs`, `ParameterEditService.cs`, `docs/runbooks/set-parameter-value-runbook.md`, ledger BHV-023/BHV-024). Canonical state is correct; README lags. | Program 4 / 7 | `README.md` (separate PR; out of scope for this docs seed) |

## Current Status / Source Needed

This list reflects investigations evidenced in the repo and recent program work
as of the seed date. Programs should add/close entries via PR.
