# Local Audit and Run Spine

## Purpose

The run spine assigns every Axiom action a durable run ID, creates a standard
artifact folder, writes structured audit logs, records command metadata, and
captures execution/result information in machine-readable files.

This is foundational infrastructure. Every future Axiom capability must route
through the run spine.

## Artifact Folder Pattern

All run artifacts are stored under a configurable root:

- **Environment variable**: `AXIOM_ARTIFACTS_ROOT`
- **Default (relative)**: `artifacts`
- **Windows canonical**: `C:\Dev\Axiom\Artifacts`

Structure:

```
<artifacts_root>/Runs/
  <run_id>/
    run_metadata.json       # Run context and configuration
    command_input.json      # Raw input parameters
    parsed_intent.json      # (optional) Resolved intent
    execution_result.json   # Execution outcome
    validation_result.json  # (optional) Validation outcome
    error_result.json       # (only on failure) Error details
    external_calls.json     # External call declaration
    artifact_manifest.json  # File listing for the run folder
    run_summary.md          # Human-readable summary
```

## Run ID Format

```
YYYYMMDD_HHMMSS_<capability_snake>_<mode>
```

Example: `20260606_153012_grid_creation_dry_run`

## Command Audit Log

Location: `<artifacts_root>/audit/axiom_command_log.jsonl`

Each line is a JSON object:

```json
{
  "timestamp_utc": "2026-06-06T15:30:12+00:00",
  "run_id": "20260606_153012_grid_creation_dry_run",
  "source": "cli",
  "capability": "GridCreation",
  "mode": "dry_run",
  "risk_level": "low",
  "model_path": null,
  "model_path_redacted": null,
  "user": "builder",
  "input_summary": "{\"HorizontalCount\": 5}",
  "artifact_path": "artifacts/Runs/20260606_153012_grid_creation_dry_run",
  "status": "completed",
  "external_calls_made": false
}
```

Two entries per run: one at `started`, one at final status (`completed`/`failed`).

## External Call Declaration

Every run writes `external_calls.json`:

```json
{
  "external_calls_made": false,
  "services": [],
  "notes": "Local-only run. No external calls were made."
}
```

This is required for future trust posture. When a run makes external calls
(e.g., Revit pipe, future MCP), the declaration must list the services called.

## Run Metadata Schema

```json
{
  "run_id": "",
  "created_at_utc": "",
  "capability": "",
  "capability_version": "",
  "mode": "dry_run|execute|validate|diagnose",
  "source": "cli|revit_ui|test|future_mcp|future_copilot|scheduled",
  "status": "started|completed|failed|blocked",
  "artifact_path": "",
  "axiom_version": "",
  "revit_version": null,
  "model_path": null,
  "active_view": null,
  "active_view_type": null
}
```

Fields can be `null` if unavailable. The schema is stable.

## Run History

`axiom_core.run_spine.list_runs(limit=50)` discovers completed runs by scanning
`<artifacts_root>/Runs/*/run_metadata.json`, sorted most-recent-first.

## Integration

The `execute_run(context, executor=None)` function orchestrates the full
spine lifecycle:

1. Generate run ID
2. Create artifact folder
3. Write audit entry (started)
4. Write metadata + input
5. Call executor (or dry-run stub)
6. Write result or error files
7. Write external calls declaration
8. Update metadata status
9. Write manifest + summary
10. Write audit entry (final status)

If execution raises an exception, all artifacts are still produced with error
capture. Failures never silently disappear.

## Non-Goals (PR #31)

- No full MCP integration
- No UI
- No OAuth or cloud dependencies
- No telemetry emission
- No generalized workflow engine
- No broad new Revit capabilities
