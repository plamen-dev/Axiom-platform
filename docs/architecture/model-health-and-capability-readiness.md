# Model Health and Capability Readiness Engine

## Purpose

Produces a local model health/readiness report for the active Revit model. The
engine answers two questions per run:

1. **Model health** — what is the current state of the model (element counts,
   warnings, view context, worksharing, staleness)?
2. **Capability readiness** — for each registered capability, is the model
   READY, WARNING, BLOCKED, or UNKNOWN for that capability?

This is not a full QA/QC engine. It is a lightweight, extensible gate that
capabilities query before execution.

## Artifact outputs

Each health/readiness run produces four health-specific files plus the standard
run spine artifacts (PR #31):

```
<artifacts_root>/Runs/<run_id>/
    axiom_environment_report.json
    axiom_model_health.json
    axiom_model_health.md
    axiom_capability_readiness.json
    run_metadata.json          (spine)
    command_input.json         (spine)
    execution_result.json      (spine)
    external_calls.json        (spine)
    artifact_manifest.json     (spine)
    run_summary.md             (spine)
```

## Model health schema

```json
{
  "generated_at_utc": "2026-06-07T12:00:00+00:00",
  "checker_version": "1.0.0",
  "ruleset_version": "1.0.0",
  "revit_version": "2024",
  "model_path": "C:\\Projects\\Test.rvt",
  "model_path_redacted": "C:/Projects/Test.rvt",
  "model_last_modified_utc": null,
  "active_document_title": "Test",
  "active_view_name": "Level 1",
  "active_view_type": "FloorPlan",
  "worksharing_enabled": null,
  "linked_model_count": null,
  "level_count": 3,
  "grid_count": 0,
  "room_count": null,
  "space_count": null,
  "warning_count": 5,
  "cad_import_count": null,
  "cad_link_count": null,
  "view_template_count": null,
  "sheet_count": null,
  "stale_status": "current"
}
```

Fields that cannot be safely retrieved are `null`. The schema is stable —
consumers should tolerate null values.

## Capability readiness schema

```json
{
  "capability": "GridCreation",
  "capability_version": "1.0.0",
  "readiness": "READY",
  "risk_level": "medium",
  "dry_run_available": true,
  "execute_available": true,
  "blocking_conditions": [],
  "warnings": [],
  "required_user_decisions": [],
  "recommended_next_actions": []
}
```

### Readiness levels

| Level     | Meaning                                     |
|-----------|---------------------------------------------|
| `READY`   | All checks pass. Capability can execute.    |
| `WARNING` | Capability can execute but with caveats.    |
| `BLOCKED` | Cannot execute until conditions are fixed.  |
| `UNKNOWN` | No readiness check registered.              |

## GridCreation readiness logic

| Condition                            | Result    |
|--------------------------------------|-----------|
| No active document                   | BLOCKED   |
| 3D/Section/Elevation/Schedule view   | BLOCKED   |
| Unknown or non-plan view type        | WARNING   |
| Revit version unavailable            | WARNING   |
| Existing grids in model              | WARNING   |
| All checks pass                      | READY     |

## Adding readiness checks for new capabilities

Register a check function that accepts `ModelHealth` and returns
`CapabilityReadiness`:

```python
from axiom_core.model_health import (
    CapabilityReadiness,
    ModelHealth,
    register_readiness_check,
)

def _my_capability_readiness(health: ModelHealth) -> CapabilityReadiness:
    blocking = []
    warnings = []
    # ... capability-specific logic ...
    readiness = "BLOCKED" if blocking else ("WARNING" if warnings else "READY")
    return CapabilityReadiness(
        capability="MyCap",
        readiness=readiness,
        blocking_conditions=blocking,
        warnings=warnings,
    )

register_readiness_check("MyCap", _my_capability_readiness)
```

## Environment report

The environment report captures the execution context:

```json
{
  "generated_at_utc": "",
  "axiom_version": "0.1.0",
  "python_version": "3.12.8",
  "platform_system": "Windows",
  "platform_release": "10",
  "platform_machine": "AMD64",
  "revit_version": "2024",
  "revit_connected": true
}
```

## Run spine integration

Health runs use the PR #31 run spine building blocks directly:

- `generate_run_id("ModelHealth", "diagnose")` for the run ID
- Standard audit JSONL entries (started + completed/failed)
- All spine artifact files produced alongside health files
- Failures still produce all artifacts (error durability)

The run appears in `list_runs()` alongside other spine-governed runs.

## Path redaction policy

Axiom's trust posture requires that user-specific path segments are redacted
in audit and summary artifacts. The single source of truth for path redaction
is `run_spine.redact_path()`.

**Which files may contain full (unredacted) local paths and why:**

| File                      | Contains unredacted path? | Reason                                               |
|---------------------------|---------------------------|------------------------------------------------------|
| `run_metadata.json`       | Yes (`model_path`)        | Machine-readable reference needed for re-execution.  |
| `axiom_model_health.json` | Yes (`model_path`)        | Full diagnostic snapshot; also carries `model_path_redacted`. |
| `command_input.json`      | No (redacted)             | Audit-facing summary; uses redacted path.            |
| `axiom_command_log.jsonl` | Yes (`model_path`)        | Audit log carries both `model_path` and `model_path_redacted`; consumers should prefer the redacted variant. |
| `axiom_model_health.md`   | No (redacted)             | Human-readable report uses `model_path_redacted`.    |
| `run_summary.md`          | No (redacted)             | Human-readable summary uses redacted path.           |

Files that retain the unredacted `model_path` are local-only run artifacts
stored in the user's own artifact directory. They are never transmitted
externally. The `model_path_redacted` field is always populated alongside
the raw path so consumers can choose the appropriate variant.

## Non-goals

- Full model QA/QC
- Dashboard or UI
- Global/portfolio metrics
- MEP-specific readiness checks (future)
- Cloud sync
- Revit Start Page injection
