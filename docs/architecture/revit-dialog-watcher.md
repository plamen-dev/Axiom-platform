# Revit Dialog Watcher

## Purpose

The Dialog Watcher detects and logs dialog/modal interference during Revit
automation runs. It provides visibility into UI events that may block or
degrade unattended execution without attempting to auto-dismiss unknown dialogs.

## Architecture

```
┌─────────────────┐     ┌────────────────┐     ┌──────────────────┐
│  Run Spine      │────▶│ DialogWatcher  │────▶│ Artifact Folder  │
│  (execute_run)  │     │ (accumulates   │     │  dialog_events.* │
│                 │     │  events)       │     │  ui_automation_*  │
└─────────────────┘     └────────────────┘     └──────────────────┘
```

### Integration with Run Spine

Every `execute_run()` call produces dialog artifacts:

- **With a `DialogWatcher`**: The watcher's accumulated events are written.
  If any event has `severity="blocking"`, the run is failed with
  `BLOCKED_BY_DIALOG`.
- **Without a `DialogWatcher`**: Default empty artifacts are written (no
  events, no UI automation risk).

## Artifacts Produced

| File | Description |
|------|-------------|
| `dialog_events.json` | Structured event log |
| `dialog_events.md` | Human-readable summary |
| `ui_automation_risk.json` | UI automation risk declaration |

## Dialog Event Schema

```json
{
  "run_id": "20260607_...",
  "events": [
    {
      "timestamp_utc": "2026-06-07T12:00:00+00:00",
      "event_type": "dialog_opened|modal_detected|unknown_ui_blocker",
      "title": "File Not Found",
      "text": "The linked model could not be located.",
      "severity": "info|warning|blocking",
      "known_dialog_id": "revit_file_not_found_001",
      "action_taken": "none|logged|auto_dismissed|failed_run",
      "screenshot_path": null
    }
  ]
}
```

### Event Types

| Type | Description |
|------|-------------|
| `dialog_opened` | A standard dialog appeared |
| `modal_detected` | A modal window blocked interaction |
| `unknown_ui_blocker` | Unknown UI element preventing automation |

### Severity Levels

| Level | Effect |
|-------|--------|
| `info` | Logged only, no effect on run |
| `warning` | Logged, run continues but may be degraded |
| `blocking` | Run fails with `BLOCKED_BY_DIALOG` |

## Failure Classification

`BLOCKED_BY_DIALOG` integrates with the existing outcome taxonomy
(`EvidenceOutcome.BLOCKED` in `evidence_runner.py`). It is a specific
sub-classification identifying the cause of blockage.

When a `DialogWatcher` contains a blocking event:
1. The run status becomes `"failed"`.
2. An `error_result.json` is written with `error_type: "BLOCKED_BY_DIALOG"`.
3. The audit log records the failure.

## Screenshot Placeholder

The `screenshot_path` field in `DialogEvent` is a hook for future screenshot
capture. Current implementation records the path if provided by the caller
but does not capture screenshots automatically. Future work:

- Win32 screen capture when a blocking dialog is detected.
- Save to the run artifact folder.
- Reference in the event record.

## Usage

```python
from axiom_core.dialog_watcher import DialogWatcher, DialogEvent
from axiom_core.run_spine import RunContext, execute_run

# Create watcher and record events during execution
watcher = DialogWatcher(run_id="placeholder")

# In a real Revit session, events would be recorded by a monitoring thread
watcher.record_event(DialogEvent(
    event_type="dialog_opened",
    title="Save File",
    severity="info",
    action_taken="auto_dismissed",
    known_dialog_id="revit_save_prompt",
))

# Pass to run spine
ctx = RunContext(capability="GridCreation", dialog_watcher=watcher)
result = execute_run(ctx)
```

## Future Work

- Win32/COM dialog monitoring thread for unattended Revit sessions.
- Known dialog registry with safe auto-dismiss rules.
- Desktop Connector dialog detection.
- Integration with failure retry logic.
