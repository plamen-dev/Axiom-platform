# Multi-Runner Strategy

## Overview

Axiom capabilities require different execution environments. Not every task
needs desktop Revit (which consumes an Autodesk license). The multi-runner
strategy classifies actions into execution lanes so future dispatchers can
route work to the correct runner.

## Execution Lanes

| Lane | Description | License Impact | Examples |
|---|---|---|---|
| `desktop_revit` | Requires an active Revit instance | Consumes Autodesk license | GridCreation, LevelCreation, model mutation, live health check |
| `aps` | Uses Autodesk Platform Services (cloud) | API quota only | Future cloud-based model queries, Design Automation |
| `non_revit_data` | Works on local data/artifacts only | None | Report generation, artifact queries, health from prior extracted data |
| `unknown` | Cannot be classified yet | Unknown | New/unregistered capabilities |

## Classification Logic

```
classify_execution_lane(capability_id, mode) → lane

Rules:
1. Model health from prior extracted data → non_revit_data
2. Report generation from artifacts → non_revit_data
3. Any live model mutation or Revit interaction → desktop_revit
4. Health check on active model → desktop_revit
5. Project setup / parameter mutation → desktop_revit
6. Unknown → unknown
```

## Current Classification Map

| Capability | Mode | Lane |
|---|---|---|
| `grid_creation` | execute | desktop_revit |
| `grid_creation` | dry_run | desktop_revit |
| `grid_creation` | health_check | desktop_revit |
| `model_health` | health_check | desktop_revit |
| `model_health` | dry_run | desktop_revit |
| `model_health_report` | health_check | non_revit_data |
| `report_generation` | any | non_revit_data |
| `artifact_query` | any | non_revit_data |
| `project_setup` | any | desktop_revit |
| `set_parameter_value` | any | desktop_revit |

## Licensing Implications

- **desktop_revit** tasks open a Revit instance and consume a seat license.
  These should be batched, scheduled during low-usage windows, or deferred
  when possible.
- **aps** tasks use cloud API quotas but no desktop license.
- **non_revit_data** tasks have no licensing cost and can run freely.

## Integration with Automation Planner

The automation planner calls `classify_execution_lane()` for every
recommended action. The lane is included in both:

1. The `AutomationPlan` output (`execution_lane` field per action)
2. The policy gate decision (future: different approval rules per lane)

## Future Work

- **Runner dispatch**: Route actions to the correct runner based on lane
- **License-aware scheduling**: Defer desktop_revit tasks when seats are
  limited
- **APS runner**: Cloud-based model processing via Design Automation
- **Hybrid strategies**: Start with non_revit_data analysis, escalate to
  desktop_revit only if mutation is needed
- **Cost tracking**: Track license-hours consumed per lane

## Adding New Lanes

1. Add the lane constant to `automation_planner.py` (`LANE_*` and `VALID_LANES`).
2. Update `classify_execution_lane()` with routing logic.
3. Document the lane in this file.
4. Add tests for the new classification.
