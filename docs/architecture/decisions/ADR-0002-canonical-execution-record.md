# ADR-0002 — Canonical execution record for the chain

**Status:** PROPOSED (awaiting Chief Architect approval). Retirement action is **pending furnace evidence**.
**Decision owner:** Plamen (Chief Architect). Drafted by: Devin (Assistant Architect).
**Serves objective:** one captured evidence record for the real SetParameterValue loop.

## Context
Two execution-record concepts coexist:
- `ExecutionReport` (`src/axiom_core/execution_report.py`) — terminal record of the M4 execution chain.
- `ExecutionTrace` (`src/axiom_core/persistence.py`) — SQLite job→trace persistence from the initial foundation.

## Evidence
| Lane | `ExecutionReport` | `ExecutionTrace` (persistence) |
|------|-------------------|--------------------------------|
| **Code** | Chain-terminal report referencing result + artifact + evidence (Stage 7). | SQLite persistence of job→trace records; general job store. |
| **Runtime (canonical chain)** | **Wired**: `execution_chain_orchestrator.py:49` imports `ExecutionReportEngine`; `:521` instantiates it; `:303,:725-733` build Stage-7 links. | **Not** imported by `execution_chain_orchestrator.py`. |
| **PR history** | Introduced PR #142 (repo-local, 2026-06-27). | Introduced by the initial-foundation commit (repo bootstrap, 2025-12-13). |
| **Tests** | `tests/test_execution_report.py`, exercised via `tests/test_execution_chain_orchestrator.py`. | `tests/test_persistence.py`. |
| **Artifacts** | Chain evidence + `capability_execution_reports/` present. | SQLite DB store. |
| **Real Revit loop** | Intended terminal record — **pending furnace evidence**. | None on the chain path. |

These are **duplicate-candidates by concept** (both are "execution records") but serve different layers: `ExecutionReport` is the chain's structured terminal artifact; `ExecutionTrace` is an older general-purpose SQLite job store.

## Decision (proposed)
1. **`ExecutionReport` is CANONICAL** as the execution chain's terminal record and the record the real SetParameterValue loop will emit.
2. **`ExecutionTrace`/`persistence.py` is retained as an ADAPTER / general job store**, not the chain record, and is **not** classified legacy — it is active for its own path.
3. No merge of the two models under this ADR. If the real loop needs SQLite-durable chain records, add an explicit `ExecutionReport → persistence` adapter rather than reviving `ExecutionTrace` as the chain terminal.

## Pending furnace evidence
Whether `ExecutionTrace` participates in the real loop's durability path is decided after Phase 1. Until then it is **active/adapter**, retirement not proposed.

## Consequences
- The real loop's evidence bundle is anchored on `ExecutionReport`; navigability (Phase 2) links from `ExecutionReport` outward.
- No code deleted or merged under this ADR.
