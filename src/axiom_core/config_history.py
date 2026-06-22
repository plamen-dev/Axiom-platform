"""Configuration Change History Framework v1.

Provides deterministic change history capabilities on top of configuration
execution and rollback. Preserves a traceable history of configuration
lifecycle events.

Non-goals: no autonomous auditing, no schedulers, no workflow engines,
no external logging systems, no uncontrolled mutation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationChangeEventType(str, Enum):
    CONFIG_LOADED = "config_loaded"
    CONFIG_VALIDATED = "config_validated"
    REPAIR_RECOMMENDED = "repair_recommended"
    EXPLANATION_GENERATED = "explanation_generated"
    EXECUTION_COMPLETED = "execution_completed"
    ROLLBACK_COMPLETED = "rollback_completed"
    NO_ACTION = "no_action"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationChangeEvent:
    """A single configuration lifecycle event."""

    event_id: str = ""
    config_id: str = ""
    event_type: str = ""
    source_id: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "config_id": self.config_id,
            "event_type": self.event_type,
            "source_id": self.source_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationChangeHistory:
    """A history of configuration lifecycle events."""

    history_id: str = ""
    config_id: str = ""
    events: list[ConfigurationChangeEvent] = field(default_factory=list)
    event_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.history_id:
            self.history_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        self.event_count = len(self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "history_id": self.history_id,
            "config_id": self.config_id,
            "events": [e.to_dict() for e in self.events],
            "event_count": self.event_count,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationChangeHistoryReport:
    """Report summarizing a configuration change history."""

    report_id: str = ""
    config_id: str = ""
    timeline_summary: str = ""
    event_count: int = 0
    history: ConfigurationChangeHistory | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "config_id": self.config_id,
            "timeline_summary": self.timeline_summary,
            "event_count": self.event_count,
            "history": self.history.to_dict() if self.history else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# History engine
# ---------------------------------------------------------------------------


class ConfigurationChangeHistoryEngine:
    """Builds configuration change history deterministically."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._history_dir = self._artifacts_root / "config_history"
        self._history_dir.mkdir(parents=True, exist_ok=True)

    def _safe_history_path(self, report_id: str) -> Path:
        target = (self._history_dir / report_id).resolve()
        sandbox = self._history_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def create_history(
        self,
        config: dict[str, Any] | None = None,
        validation_report: dict[str, Any] | None = None,
        repair_report: dict[str, Any] | None = None,
        execution_result: dict[str, Any] | None = None,
        rollback_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a configuration change history from lifecycle artifacts."""
        config_id = ""
        if config:
            config_id = config.get("config_id", "")
        elif validation_report:
            config_id = validation_report.get("config_id", "")
        elif repair_report:
            config_id = repair_report.get("config_id", "")

        events: list[ConfigurationChangeEvent] = []

        if config:
            events.append(ConfigurationChangeEvent(
                config_id=config_id,
                event_type=ConfigurationChangeEventType.CONFIG_LOADED.value,
                source_id=config.get("config_id", ""),
                summary=f"Configuration loaded: {config.get('entry_count', 0)} entries",
            ))

        if validation_report:
            valid = validation_report.get("valid", False)
            events.append(ConfigurationChangeEvent(
                config_id=config_id,
                event_type=ConfigurationChangeEventType.CONFIG_VALIDATED.value,
                source_id=validation_report.get("report_id", ""),
                summary=f"Validation {'passed' if valid else 'failed'}: "
                        f"{validation_report.get('error_count', 0)} errors, "
                        f"{validation_report.get('warning_count', 0)} warnings",
            ))

        if repair_report:
            events.append(ConfigurationChangeEvent(
                config_id=config_id,
                event_type=ConfigurationChangeEventType.REPAIR_RECOMMENDED.value,
                source_id=repair_report.get("report_id", ""),
                summary=f"Repair recommended: "
                        f"{repair_report.get('repairable_count', 0)} repairable, "
                        f"{repair_report.get('unrepairable_count', 0)} unrepairable",
            ))

        if execution_result:
            status = execution_result.get("status", "unknown")
            events.append(ConfigurationChangeEvent(
                config_id=config_id,
                event_type=ConfigurationChangeEventType.EXECUTION_COMPLETED.value,
                source_id=execution_result.get("result_id", ""),
                summary=f"Execution completed: status={status}",
            ))

        if rollback_result:
            status = rollback_result.get("status", "unknown")
            events.append(ConfigurationChangeEvent(
                config_id=config_id,
                event_type=ConfigurationChangeEventType.ROLLBACK_COMPLETED.value,
                source_id=rollback_result.get("result_id", ""),
                summary=f"Rollback completed: status={status}",
            ))

        if not events:
            events.append(ConfigurationChangeEvent(
                config_id=config_id,
                event_type=ConfigurationChangeEventType.NO_ACTION.value,
                source_id="",
                summary="No configuration lifecycle events recorded",
            ))

        history = ConfigurationChangeHistory(
            config_id=config_id,
            events=events,
        )

        timeline_summary = self._build_timeline_summary(history)

        report = ConfigurationChangeHistoryReport(
            config_id=config_id,
            timeline_summary=timeline_summary,
            event_count=history.event_count,
            history=history,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    def _build_timeline_summary(
        self,
        history: ConfigurationChangeHistory,
    ) -> str:
        event_types = [e.event_type for e in history.events]
        return (
            f"Configuration lifecycle: {history.event_count} events recorded. "
            f"Types: {', '.join(event_types)}."
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._history_dir.exists():
            return reports

        sandbox = self._history_dir.resolve()
        for entry in self._history_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
                continue
            report_file = entry / "report.json"
            if not report_file.exists():
                continue
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
                reports.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        reports.sort(key=lambda r: r.get("created_at", ""))
        return reports

    def export_report(self, report_id: str) -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"History report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationChangeHistoryReport) -> None:
        report_dir = self._safe_history_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_history_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationChangeHistoryReport) -> str:
        evidence_dir = self._safe_history_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report.report_id,
            "config_id": report.config_id,
            "event_count": report.event_count,
            "event_types": (
                [e.event_type for e in report.history.events]
                if report.history else []
            ),
        }
        (evidence_dir / "config_history_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "config_history_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_history_summary.md").write_text(
            md, encoding="utf-8",
        )

        pass_fail = {
            "passed": report.event_count > 0,
            "report_id": report.report_id,
            "config_id": report.config_id,
            "event_count": report.event_count,
            "status": "succeeded" if report.event_count > 0 else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Configuration Change History Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Config ID: {data.get('config_id', '')}")
        lines.append(f"- Event count: {data.get('event_count', 0)}")
        lines.append(f"- Summary: {data.get('timeline_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        history = data.get("history")
        if history:
            events = history.get("events", [])
            if events:
                lines.append("## Timeline")
                lines.append("")
                for i, event in enumerate(events, 1):
                    lines.append(
                        f"{i}. [{event.get('event_type', '').upper()}] "
                        f"{event.get('summary', '')}"
                    )
                    if event.get("source_id"):
                        lines.append(f"   Source: {event['source_id']}")
                lines.append("")

        return "\n".join(lines)
