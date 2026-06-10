# UI Automation Risk Policy

## Axiom Fallback Ladder

Axiom uses a strict precedence order when interacting with Revit and external
systems. Each step down the ladder increases brittleness and risk.

| Priority | Method | Risk | Notes |
|----------|--------|------|-------|
| 1 | Official Revit API | None | Preferred. Stable, versioned, documented. |
| 2 | Revit API (undocumented/internal) | Low | Use only when official API lacks coverage. Document the gap. |
| 3 | APS / Cloud API | Low | For cloud-enabled workflows. Requires auth. |
| 4 | File / System API | Low–Medium | Direct file manipulation, registry reads. Safe if well-scoped. |
| 5 | UI Automation | High | Declared, logged, brittle fallback only. |

## UI Automation Risk Declaration

Every run produces `ui_automation_risk.json`:

```json
{
  "ui_automation_used": false,
  "ui_automation_reason": "",
  "official_api_available": null,
  "risk_level": "none|low|medium|high",
  "notes": ""
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `ui_automation_used` | bool | Whether any UI automation was used in this run |
| `ui_automation_reason` | string | Why UI automation was necessary |
| `official_api_available` | bool\|null | Whether an official API exists for this action |
| `risk_level` | enum | `none` \| `low` \| `medium` \| `high` |
| `notes` | string | Free-form context |

### Risk Levels

| Level | Definition |
|-------|------------|
| `none` | No UI automation used. Default for all runs. |
| `low` | Auto-dismissed a known, safe dialog (e.g., save prompt). |
| `medium` | Interacted with a UI element that could change between versions. |
| `high` | Used SendKeys/Win32 to interact with unknown or third-party dialogs. |

## Policy Rules

1. **Default is no UI automation.** Every run defaults to
   `ui_automation_used: false`.

2. **Declaration required.** If UI automation is used, the risk declaration
   must be written with a reason and risk level.

3. **Official API first.** If an official API exists for the same action,
   UI automation is not justified. Document why the API cannot be used if
   it is impractical (e.g., requires Revit restart).

4. **Known dialogs only.** Auto-dismiss is permitted only for dialogs with
   a registered `known_dialog_id` and documented safe-dismiss behavior.

5. **Never bypass security.** Do not auto-click Autodesk security prompts,
   license dialogs, or authentication windows.

6. **Never automate Desktop Connector broadly.** Narrow, safe hooks for
   Desktop Connector sync status are acceptable only if explicitly validated
   and documented.

7. **Log everything.** All UI automation interactions must be recorded in
   `dialog_events.json` with full context.

## Known Scenarios

### Desktop Connector Sync Dialog

Desktop Connector has no public API for sync status queries. When a sync
dialog blocks Revit automation:

- **Current behavior:** Log as `unknown_ui_blocker`, severity `blocking`,
  classify as `BLOCKED_BY_DIALOG`.
- **Future option:** Narrow SendKeys dismiss if validated safe. Would require
  `ui_automation_used: true`, `risk_level: "high"`,
  `official_api_available: false`.

### Save/Backup Prompts

Known Revit save prompts during batch operations:

- **Current behavior:** Log as `dialog_opened`, severity `info` or `warning`.
- **Future option:** Auto-dismiss with `known_dialog_id: "revit_save_prompt"`,
  risk level `low`.

## Integration with Failure Classification

When UI automation fails or a dialog cannot be dismissed:

- `error_type: "BLOCKED_BY_DIALOG"` in `error_result.json`
- Integrates with `EvidenceOutcome.BLOCKED` taxonomy
- Retry logic (future) can check `dialog_events.json` to determine if
  the same dialog is likely to recur
