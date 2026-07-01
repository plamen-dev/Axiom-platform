# ADR-0001 — Canonical execution-attempt engine

**Status:** PROPOSED (awaiting Chief Architect approval). Retirement action is **pending furnace evidence**.
**Decision owner:** Plamen (Chief Architect). Drafted by: Devin (Assistant Architect).
**Serves objective:** naming THE canonical chain to drive real Revit SetParameterValue through.

## Context
Two modules both export a class named `ExecutionAttemptEngine`, a textbook "same terminology, different concept" duplicate:
- `src/axiom_core/execution_attempt.py` ("v1")
- `src/axiom_core/execution_attempt_v2.py` ("v2")

## Evidence
| Lane | v1 `execution_attempt.py` | v2 `execution_attempt_v2.py` |
|------|---------------------------|------------------------------|
| **Code** | Tracks attempts on top of the **Work Prioritization Framework**. Docstring non-goal: "no execution engine, no worker orchestration, no autonomous execution." lowercase status enum. | Tracks attempts on top of the **Execution Step / Plan / Capability Knowledge Graph**. Docstring: "distinct from the v1 module … kept separate to preserve that existing behavior." UPPERCASE status enum. |
| **Runtime (canonical chain)** | **Not** imported by `execution_chain_orchestrator.py`. | **Imported and wired** into the M4 chain: `execution_chain_orchestrator.py:47` → `from axiom_core.execution_attempt_v2 import ExecutionAttemptEngine`. |
| **CLI** | `execution-attempt-create/show/export` (main.py:16250+). | `execution-attempt-v2-create/show/export` (main.py:21395+). |
| **PR history** | Introduced PR #111 (repo-local, 2026-06-22), on Work Prioritization. | Introduced PR #139 (repo-local, 2026-06-24), on Execution Step. |
| **Tests** | `tests/test_execution_attempt.py`. | `tests/test_execution_attempt_v2.py`. |
| **Artifacts** | Own path; no `artifacts/execution_attempt/` present in workspace. | `artifacts/execution_attempt_v2/` **present** (has produced output). |
| **Real Revit loop** | None. | None yet — **pending furnace evidence**. |

Both are **observational/declarative record layers** — neither actually executes anything. The concept overlap is *attempt-tracking*; the difference is the *upstream anchor* (Work Prioritization vs Execution Step).

## Decision (proposed)
1. **v2 (`execution_attempt_v2.py`) is CANONICAL** for the execution chain — it is the one wired into the M4 orchestrator that the real loop will traverse.
2. **v1 (`execution_attempt.py`) is a RETIRE CANDIDATE**, contingent on furnace evidence. Rationale: it anchors to Work Prioritization, which is not on the SetParameterValue loop path; and it collides on the `ExecutionAttemptEngine` name, which is a live source of confusion.
3. **Immediate, non-destructive step (safe now):** resolve the class-name collision by referring to v2 as the canonical `ExecutionAttemptEngine` in docs/atlas; do **not** delete or rename source yet.

## Pending furnace evidence
Before v1 is deleted/retired, the Phase 1 real loop must confirm the closed SetParameterValue path never depends on a Work-Prioritization-anchored attempt record. If it does, v1 is reclassified **adapter**, not retire.

## Consequences
- The loop is driven through v2 only; no ambiguity about which attempt engine records the real run.
- No code deleted under this ADR. Deletion requires a follow-up, per-ADR approval **after** Phase 1.
