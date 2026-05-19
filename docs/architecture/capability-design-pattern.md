# Capability Design Pattern v1

## Purpose

Define the repeatable pattern every Axiom capability should follow after the CreateGrids baseline.

## Capability Definition Template

Each capability should define:

- name
- description
- parameter model
- required parameters
- optional parameters
- defaults and assumptions
- validation rules
- simulation behavior
- Revit execution behavior
- result format
- telemetry requirements
- tests
- known limitations

## Current Validated Capability

`CreateGrids`

Status: validated baseline, with future geometry and variable-spacing refinements expected.

## Planned Next Capability

`CreateLevels`

Reason: simple deterministic second capability that proves the framework can support more than one Revit action without expanding into discipline workflows.

## Ownership Rule

Capabilities belong to the capability layer/registry, not to OrchestratorAgent, ExecutionAgent, KnowledgeAgent, or discipline agents.

Agents coordinate. Capabilities execute. Services implement. Adapters connect.

---

## Related Documents

- [Multi-Platform Capability Intelligence](multi-platform-capability-intelligence.md) — platform-level architecture showing how capabilities fit into the multi-product vision
- [Capability Creation Checklist](capability-creation-checklist.md) — operational checklist for adding new capabilities
- [Agent Responsibility Spec](agent-responsibility-spec.md) — agent roles and coordination rules
