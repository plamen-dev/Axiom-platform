# Workflow Knowledge Registry

## Strategic Purpose

Transforms founder expertise into structured knowledge. Engineering workflows
are one of the future moats — capturing the decision sequences, rules, and
data flows that make BIM automation reliable.

## Scope

Captures engineering workflows as first-class knowledge objects with:
- Ordered steps (deterministic sequence)
- Typed inputs and outputs per step
- Step dependencies (including cycles — metadata only, no execution)
- Rules governing workflow behavior (priority-ordered)

## Data Model

### WorkflowDefinition

| Field | Type | Description |
|-------|------|-------------|
| `workflow_id` | string | Unique identifier |
| `workflow_name` | string | Human-readable name |
| `description` | string | What this workflow does |
| `status` | active/draft/deprecated | Lifecycle status |
| `version` | string | Semantic version |
| `metadata` | dict | Additional key-value data |
| `steps` | list[WorkflowStep] | Ordered steps |
| `rules` | list[WorkflowRule] | Governing rules |

### WorkflowStep

| Field | Type | Description |
|-------|------|-------------|
| `step_id` | string | Unique step identifier |
| `step_name` | string | Step label |
| `step_order` | int | Execution order (deterministic) |
| `description` | string | What this step does |
| `inputs` | list[WorkflowInput] | Required/optional inputs |
| `outputs` | list[WorkflowOutput] | Produced outputs |
| `depends_on` | list[string] | Step IDs this depends on |

### WorkflowInput / WorkflowOutput

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Parameter name |
| `description` | string | What it represents |
| `required` | bool | (Input only) Whether mandatory |

### WorkflowRule

| Field | Type | Description |
|-------|------|-------------|
| `rule_id` | string | Unique rule identifier |
| `rule_name` | string | Rule label |
| `condition` | string | When this rule applies |
| `action` | string | What to do |
| `priority` | int | Evaluation order (lower = higher priority) |
| `notes` | string | Additional context |

## Example Workflows

### MEP Load Calculation

```
Room Name → Room Type → Occupancy → Lighting Load → Receptacle Load → HVAC Load
```

### Grid Layout to Sheets

```
Grid Layout → Levels → Views → Sheets
```

## Persistence

SQLite tables:
- `workflow_definitions` — workflow metadata
- `workflow_steps` — ordered steps with inputs/outputs
- `workflow_rules` — priority-ordered rules

## CLI

```bash
# Human-readable table
axiom workflows

# Filter by name
axiom workflows --name "Grid"

# Include deprecated
axiom workflows --include-deprecated

# Machine-readable JSON
axiom workflows --json-output
```

## Python API

```python
from axiom_core.workflow_registry import (
    WorkflowDefinition, WorkflowStep, WorkflowInput,
    WorkflowOutput, WorkflowRule, WorkflowKnowledgeRegistry,
)

registry = WorkflowKnowledgeRegistry()

wf = WorkflowDefinition(
    workflow_name="MEP Load Calculation",
    steps=[
        WorkflowStep(step_name="Room Name", step_order=1,
                     inputs=[WorkflowInput(name="room_schedule")],
                     outputs=[WorkflowOutput(name="room_name")]),
        WorkflowStep(step_name="Room Type", step_order=2,
                     inputs=[WorkflowInput(name="room_name")],
                     outputs=[WorkflowOutput(name="room_type")]),
        # ... more steps
    ],
    rules=[
        WorkflowRule(rule_name="Min Area", condition="area < 50",
                     action="warn", priority=1),
    ],
)
registry.register_workflow(wf)
```

## Non-Goals

- No execution engine
- No planners or schedulers
- No automation triggers
- No learning or adaptation
- No UI or visualization

## Future Layers

Once the registry is stable, future PRs may add:
- Workflow versioning with diff tracking
- Cross-reference with Knowledge Object Model (PR #37)
- Provenance linking (PR #38) for each workflow
- Capability mapping (which capabilities implement which steps)
- Workflow composition (combining sub-workflows)
