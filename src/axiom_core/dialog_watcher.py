"""Axiom Revit Dialog Watcher and UI-Automation Risk Logging.

Detects and logs dialog/modal interference during Revit automation runs.
Produces per-run artifacts:

    dialog_events.json   — structured event log
    dialog_events.md     — human-readable summary
    ui_automation_risk.json — risk declaration

This module does NOT auto-dismiss unknown dialogs or implement broad UI
automation. Its purpose is visibility, classification, and artifact capture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

BLOCKED_BY_DIALOG = "BLOCKED_BY_DIALOG"
"""Failure classification when a run is blocked by a dialog or modal window.

Integrates with the existing EvidenceOutcome.BLOCKED taxonomy — this is a
specific sub-classification identifying *why* the run was blocked.
"""

# ---------------------------------------------------------------------------
# Valid enum values (for documentation and future validation)
# ---------------------------------------------------------------------------

VALID_EVENT_TYPES = frozenset({"dialog_opened", "modal_detected", "unknown_ui_blocker"})
VALID_SEVERITIES = frozenset({"info", "warning", "blocking"})
VALID_ACTIONS = frozenset({"none", "logged", "auto_dismissed", "failed_run"})
VALID_RISK_LEVELS = frozenset({"none", "low", "medium", "high"})


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DialogEvent:
    """One dialog/UI event observed during a run."""

    timestamp_utc: str = ""
    event_type: str = "dialog_opened"  # dialog_opened | modal_detected | unknown_ui_blocker
    title: str = ""
    text: str = ""
    severity: str = "info"  # info | warning | blocking
    known_dialog_id: str | None = None
    action_taken: str = "none"  # none | logged | auto_dismissed | failed_run
    screenshot_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "event_type": self.event_type,
            "title": self.title,
            "text": self.text,
            "severity": self.severity,
            "known_dialog_id": self.known_dialog_id,
            "action_taken": self.action_taken,
            "screenshot_path": self.screenshot_path,
        }


@dataclass
class DialogEventsRecord:
    """All dialog events for a single run."""

    run_id: str
    events: list[DialogEvent] = field(default_factory=list)

    @property
    def has_blocking_event(self) -> bool:
        """True if any event has severity 'blocking'."""
        return any(e.severity == "blocking" for e in self.events)

    @property
    def failure_classification(self) -> str | None:
        """Return BLOCKED_BY_DIALOG if any blocking event, else None."""
        if self.has_blocking_event:
            return BLOCKED_BY_DIALOG
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "events": [e.to_dict() for e in self.events],
        }


@dataclass
class UIAutomationRisk:
    """UI automation risk declaration for a run."""

    ui_automation_used: bool = False
    ui_automation_reason: str = ""
    official_api_available: bool | None = None
    risk_level: str = "none"  # none | low | medium | high
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ui_automation_used": self.ui_automation_used,
            "ui_automation_reason": self.ui_automation_reason,
            "official_api_available": self.official_api_available,
            "risk_level": self.risk_level,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Dialog Watcher
# ---------------------------------------------------------------------------


class DialogWatcher:
    """Accumulates dialog events during a run and writes artifacts.

    Usage::

        watcher = DialogWatcher(run_id="20260607_...")
        watcher.record_event(DialogEvent(
            event_type="dialog_opened",
            title="File Not Found",
            severity="blocking",
        ))
        watcher.write_artifacts(folder)
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._events: list[DialogEvent] = []

    @property
    def events(self) -> list[DialogEvent]:
        """All recorded events."""
        return list(self._events)

    @property
    def has_blocking_event(self) -> bool:
        """True if any recorded event is blocking."""
        return any(e.severity == "blocking" for e in self._events)

    @property
    def failure_classification(self) -> str | None:
        """BLOCKED_BY_DIALOG if blocking, else None."""
        if self.has_blocking_event:
            return BLOCKED_BY_DIALOG
        return None

    def record_event(self, event: DialogEvent) -> None:
        """Record a dialog event, auto-populating timestamp if empty."""
        if not event.timestamp_utc:
            event.timestamp_utc = datetime.now(timezone.utc).isoformat()
        self._events.append(event)

    def get_record(self) -> DialogEventsRecord:
        """Return the full events record."""
        return DialogEventsRecord(run_id=self.run_id, events=list(self._events))

    def write_artifacts(
        self,
        folder: Path,
        ui_risk: UIAutomationRisk | None = None,
    ) -> tuple[Path, Path, Path]:
        """Write dialog_events.json, dialog_events.md, and ui_automation_risk.json.

        Returns tuple of (events_json_path, events_md_path, risk_json_path).
        """
        if ui_risk is None:
            ui_risk = UIAutomationRisk()

        record = self.get_record()
        events_json_path = _write_dialog_events_json(folder, record)
        events_md_path = _write_dialog_events_md(folder, record)
        risk_json_path = _write_ui_automation_risk(folder, ui_risk)

        return events_json_path, events_md_path, risk_json_path


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict[str, Any]) -> None:
    # Local helper — intentionally not imported from run_spine to avoid
    # circular dependency (run_spine imports dialog_watcher).
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def _write_dialog_events_json(folder: Path, record: DialogEventsRecord) -> Path:
    """Write dialog_events.json."""
    p = folder / "dialog_events.json"
    _write_json(p, record.to_dict())
    return p


def _write_dialog_events_md(folder: Path, record: DialogEventsRecord) -> Path:
    """Write dialog_events.md — human-readable summary."""
    lines = [
        f"# Dialog Events: {record.run_id}",
        "",
    ]

    if not record.events:
        lines.append("No dialog events were observed during this run.")
    else:
        lines.append(f"**Total events:** {len(record.events)}")
        blocking = [e for e in record.events if e.severity == "blocking"]
        if blocking:
            lines.append(f"**Blocking events:** {len(blocking)}")
            lines.append(f"**Failure classification:** {BLOCKED_BY_DIALOG}")
        lines.append("")
        lines.append("## Events")
        lines.append("")
        for i, event in enumerate(record.events, 1):
            lines.append(f"### Event {i}")
            lines.append(f"- **Time:** {event.timestamp_utc}")
            lines.append(f"- **Type:** {event.event_type}")
            lines.append(f"- **Title:** {event.title or '(none)'}")
            if event.text:
                lines.append(f"- **Text:** {event.text}")
            lines.append(f"- **Severity:** {event.severity}")
            if event.known_dialog_id:
                lines.append(f"- **Known dialog:** {event.known_dialog_id}")
            lines.append(f"- **Action:** {event.action_taken}")
            if event.screenshot_path:
                lines.append(f"- **Screenshot:** {event.screenshot_path}")
            lines.append("")

    lines.append("")
    p = folder / "dialog_events.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _write_ui_automation_risk(folder: Path, risk: UIAutomationRisk) -> Path:
    """Write ui_automation_risk.json."""
    p = folder / "ui_automation_risk.json"
    _write_json(p, risk.to_dict())
    return p


# ---------------------------------------------------------------------------
# Convenience: write default (no-dialog, no-risk) artifacts
# ---------------------------------------------------------------------------


def write_default_dialog_artifacts(folder: Path, run_id: str) -> tuple[Path, Path, Path]:
    """Write default dialog/UI-risk artifacts for a clean run (no events).

    Call this from run spine orchestration to ensure every run has the
    required dialog_events.json, dialog_events.md, and ui_automation_risk.json
    even when no dialogs were observed.
    """
    watcher = DialogWatcher(run_id=run_id)
    return watcher.write_artifacts(folder)
