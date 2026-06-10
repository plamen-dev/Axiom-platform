# Event-Driven Automation Planner

## Overview

The event-driven automation planner accepts project/model/change events,
determines which Axiom capabilities may need to respond, classifies
execution requirements, and generates a dry-run plan.

**This system does not auto-execute model mutations.** It detects, plans,
classifies, and recommends.

## Architecture

```
Event Source                  Planner                     Output
─────────────────────────────────────────────────────────────────────
file_watcher │                                          
manual CLI   ├─► AutomationEvent ─► plan_for_event() ─► AutomationPlan
future_acc   │        │                    │                   │
future_mcp   │        ▼                    ▼                   ▼
test         │   validate()        classify_lane()      policy_gate()
                                                               │
                                                               ▼
                                                    execute_plan_run()
                                                         │
                                                         ▼
                                                   Run Spine Artifacts
```

## Event Schema

```json
{
  "event_id": "evt_001",
  "event_type": "model_updated",
  "timestamp_utc": "2026-06-07T12:00:00+00:00",
  "project_id": "proj_abc",
  "model_path": "C:\\Projects\\Model.rvt",
  "changed_fields": ["grids", "levels"],
  "source": "test"
}
```

### Valid Event Types

| Event Type | Description |
|---|---|
| `model_updated` | Active model file was modified |
| `project_template_updated` | Project template changed |
| `linked_model_updated` | A linked model was updated |
| `ruleset_updated` | Validation/readiness ruleset changed |
| `new_model_registered` | A new model was added to the project |
| `revit_version_changed` | Revit version upgrade/change detected |

### Valid Sources

`manual`, `file_watcher`, `future_acc`, `future_mcp`, `test`

## Planner Output

```json
{
  "event_id": "evt_001",
  "recommended_actions": [
    {
      "capability_id": "model_health",
      "reason": "Model updated — re-evaluate health and readiness.",
      "recommended_mode": "health_check",
      "execution_lane": "desktop_revit",
      "approval_required": true,
      "risk_level": "low",
      "blocking_conditions": [],
      "next_step": "Run health_check for model_health"
    }
  ],
  "policy_decisions": [...]
}
```

## Impact Rules

| Event Type | Capabilities Triggered | Mode |
|---|---|---|
| `model_updated` | `model_health` | health_check |
| `project_template_updated` | `model_health` | health_check |
| `linked_model_updated` | `model_health` | health_check |
| `ruleset_updated` | `model_health`, `grid_creation` | health_check, dry_run |
| `new_model_registered` | `model_health` | health_check |
| `revit_version_changed` | `model_health`, `grid_creation` | health_check, dry_run |

## Policy Gate

Every recommended action passes through the policy gate before execution:

- **No high-risk action auto-executes** — always requires approval
- **No `execute` mode auto-executes** — always requires approval
- **Medium-risk actions** require approval
- **Low-risk health checks** still require approval (conservative default)
- **Dry-run is always recommended** before execution

## Integration with Run Spine

`execute_plan_run()` produces standard spine artifacts:

```
20260607_120000_automationplanner_plan/
  automation_plan.json
  automation_plan.md
  policy_gate.json
  run_metadata.json
  command_input.json
  execution_result.json
  external_calls.json
  dialog_events.json
  dialog_events.md
  ui_automation_risk.json
  artifact_manifest.json
  run_summary.md
```

Audit entries (started/completed) are appended to `axiom_command_log.jsonl`.

## Adding New Event Types

1. Add the event type to `VALID_EVENT_TYPES` in `automation_planner.py`.
2. Add impact rules to `_IMPACT_RULES` dictionary.
3. Add execution lane logic to `classify_execution_lane()` if needed.
4. Add tests.

## Adding New Capabilities

When a new capability is registered in the capability registry:

1. Add impact rules that reference the new `capability_id`.
2. Add lane classification logic for the new capability.
3. Verify the policy gate handles the capability's risk level correctly.

## Future Work

- File watcher integration (local file system events)
- ACC webhook integration (Autodesk Construction Cloud)
- MCP event intake endpoint
- Scheduled event generation
- Plan execution pipeline (from plan → approved → executed)
- Multi-runner dispatch (route actions to correct runner lane)
