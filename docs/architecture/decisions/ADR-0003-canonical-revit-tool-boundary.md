# ADR-0003 — Canonical Revit tool boundary

**Status:** PROPOSED (awaiting Chief Architect approval). MCP role is **pending furnace evidence**.
**Decision owner:** Plamen (Chief Architect). Drafted by: Devin (Assistant Architect).
**Serves objective:** the real C#/Revit execution edge the SetParameterValue loop crosses.

## Context
Two "tool boundary" concepts coexist:
- Named-pipe bridge: `src/axiom_core/pipe_client.py` + `src/axiom_core/automation_bridge.py` → C# `AxiomPipeServer` / `PromptDispatcher`.
- MCP layer: `src/axiom_core/mcp_layer.py`.

## Evidence
| Lane | Pipe bridge (`pipe_client` + `automation_bridge`) | `mcp_layer.py` |
|------|---------------------------------------------------|----------------|
| **Code** | Real named-pipe transport to the Revit C# add-in; explicit `simulate`/mock fallback so it is unit-testable off-Windows (`automation_bridge.py:22,113,290-294`). | Mock/simulated MCP surface from the initial foundation. |
| **Runtime** | The path that reaches real Revit when `simulate=False` on Windows. | No real external transport. |
| **PR history** | Bridge vertical slice = repo-local PR #2 (`pipe_client`), later hardened; C# add-in tracked separately. | Initial-foundation commit (2025-12-13). |
| **Tests** | Bridge driver unit-tested via mock injection. | MCP-surface tests. |
| **Artifacts** | Windows probe captured artifacts under `artifacts\probe_runs` (Plamen machine, attested). | None real. |
| **Real Revit loop** | Substrate proven on Windows (lane 2, attested); real mutation **pending furnace evidence** (lane 3). | Not on the real path — **pending furnace evidence** on whether MCP has any real role. |

## Decision (proposed)
1. **The named-pipe bridge is the CANONICAL real Revit tool boundary** for the SetParameterValue loop; the loop runs it with `simulate=False` on Windows.
2. **`mcp_layer.py` is NOT the real Revit boundary.** Its status is **duplicate-candidate / pending furnace evidence** — do not retire it yet (per knowledge: MCP integration is not to be started/expanded unless explicitly requested; keep Axiom local-first).
3. Off-Windows, `simulate=True` remains the only supported mode; no real-Revit claims may be made from Ubuntu/Devin.

## Pending furnace evidence
The real-mutation leg (lane 3) is unproven. This ADR fixes *which* boundary to drive; it does not claim the boundary has been exercised end-to-end. MCP's fate is revisited only if a real need appears.

## Consequences
- Phase 1b drives `pipe_client`/`automation_bridge` with `simulate=False` on the Windows+Revit machine.
- No MCP work initiated; no code deleted under this ADR.
