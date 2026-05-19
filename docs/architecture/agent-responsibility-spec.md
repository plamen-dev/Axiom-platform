# Agent Responsibility Spec v1

## Core Rule

Agents coordinate. Capabilities execute. Services implement. The registry catalogs available capabilities.

## Current Operational Agents

### OrchestratorAgent

- receives prompt
- resolves intent
- selects capability through registry metadata
- prepares plan/tool steps
- coordinates execution and telemetry

### ExecutionAgent

- executes prepared tool steps
- calls pipe/client path
- returns structured ToolResult
- does not reason or select intent

### TelemetryAgent

- persists prompt, parameters, assumptions, result, errors, warnings, created IDs/count, and duration
- does not decide execution

## Deferred / Lightweight Agents

### GeometryAgent

Future: layout reasoning, extents, origin, spacing, room containment, duplicate geometry checks.

### KnowledgeAgent

Future: firm standards, playbooks, previous accepted assumptions, parameter defaults.

## Future Discipline Agents

ArchitecturalAgent, MechanicalAgent, ElectricalAgent, StructuralAgent, and similar agents should compose capabilities into workflows. They should not own low-level capabilities.

### Example: Future MechanicalAgent

A future MechanicalAgent should not own PlaceDiffusers. It should compose a workflow:

1. FindRooms
2. ResolveDiffuserTypes
3. CalculateDiffuserCounts
4. PlaceDiffusers
5. SetCFMParameters
6. ValidateSpacing
7. GenerateQAReport

Each step should map to a capability or deterministic service. The MechanicalAgent coordinates the sequence and assumptions.

## Ownership Model

- Agents = brains / coordinators
- Capabilities = hands / executable tools
- Services = deterministic implementation
- Registry = toolbox inventory
- ExecutionAgent = tool operator
- Adapters = bridges to external software (Revit, Inventor, etc.)

---

## Related Documents

- [Multi-Platform Capability Intelligence](multi-platform-capability-intelligence.md) — positions agents within the broader platform architecture
- [Capability Design Pattern](capability-design-pattern.md) — template for capabilities that agents coordinate
- [Capability Creation Checklist](capability-creation-checklist.md) — step-by-step process for adding capabilities
