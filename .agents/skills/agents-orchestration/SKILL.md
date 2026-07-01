---
name: agents-orchestration
description: Operate and verify the Axiom agents layer (orchestrator, execution, geometry, knowledge, telemetry agents). Use when testing or changing agent coordination/routing behavior under src/axiom_core/agents/.
---

# Agents / orchestration

**status: scaffold** — populate sections the first time verified operational knowledge exists for this domain (same PR as the change; see `.agents/skills/README.md`).

## Domain

Agents coordinate; capabilities execute. Source: `src/axiom_core/agents/` (`orchestrator_agent.py`, `execution_agent.py`, `geometry_agent.py`, `knowledge_agent.py`, `telemetry_agent.py`), routing in `src/axiom_core/capability_routing.py` / `capability_selection.py`.

Boundary rules: do not move capability ownership into OrchestratorAgent or ExecutionAgent; capabilities are registered executable units that agents route/coordinate. Do not add discipline agents unless explicitly instructed.

## Commands

_(to be populated)_

## Registry pointers

- Capability registration: `src/axiom_core/capability_registry.py`, `global_capability_registry.py`.

## Verification checklists

_(to be populated)_

## Tests

Targeted test files under `tests/` matching the agent/routing module changed. Full pytest only at PR checkpoints.

## Notes / gotchas

_(to be populated)_
