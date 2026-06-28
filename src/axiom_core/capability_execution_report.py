"""Capability Execution Report Framework v1.

Provides deterministic execution evidence on top of capability definitions,
inputs, and outputs. Records what actually happened during execution.

Non-goals: no capability execution engine, no autonomous scheduling,
no workflow orchestration.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityExecutionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


class CapabilityExecutionEventType(str, Enum):
    STARTED = "started"
    INPUT_VALIDATED = "input_validated"
    OUTPUT_GENERATED = "output_generated"
    WARNING = "warning"
    ERROR = "error"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityExecutionEvent:
    """An event that occurred during capability execution."""

    event_id: str = ""
    timestamp: str = ""
    event_type: str = "started"
    message: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = str(uuid4())
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "message": self.message,
        }


@dataclass
class CapabilityExecutionReport:
    """Report of a capability execution."""

    report_id: str = ""
    capability_id: str = ""
    execution_status: str = "created"
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    events: list[CapabilityExecutionEvent] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "capability_id": self.capability_id,
            "execution_status": self.execution_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "events": [e.to_dict() for e in self.events],
            "created_at": self.created_at,
        }


@dataclass
class CapabilityExecutionSummary:
    """Summary of execution events."""

    summary_id: str = ""
    report_id: str = ""
    event_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.summary_id:
            self.summary_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "report_id": self.report_id,
            "event_count": self.event_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityExecutionEvidence:
    """Evidence bundle for an execution."""

    evidence_id: str = ""
    report_id: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id:
            self.evidence_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "report_id": self.report_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_VALID_STATUSES = {s.value for s in CapabilityExecutionStatus}
_VALID_EVENT_TYPES = {t.value for t in CapabilityExecutionEventType}


class CapabilityExecutionReportEngine:
    """Manages capability execution reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_execution_reports"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, report_id: str) -> Path:
        target = (self._report_dir / report_id).resolve()
        sandbox = self._report_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        capability_id: str = "",
        execution_status: str = "succeeded",
        started_at: str = "",
        completed_at: str = "",
        duration_ms: int = 0,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create an execution report with events."""
        events = events or []

        if execution_status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid execution_status: {execution_status!r}. "
                f"Valid: {sorted(_VALID_STATUSES)}"
            )

        if not started_at:
            started_at = datetime.now(timezone.utc).isoformat()
        if not completed_at:
            completed_at = datetime.now(timezone.utc).isoformat()

        event_objects: list[CapabilityExecutionEvent] = []
        for ev_data in events:
            event_type = ev_data.get("event_type", "started")
            if event_type not in _VALID_EVENT_TYPES:
                raise ValueError(
                    f"Invalid event_type: {event_type!r}. " f"Valid: {sorted(_VALID_EVENT_TYPES)}"
                )
            event = CapabilityExecutionEvent(
                timestamp=ev_data.get("timestamp", ""),
                event_type=event_type,
                message=ev_data.get("message", ""),
            )
            event_objects.append(event)

        # Sort events by timestamp for deterministic ordering
        event_objects.sort(key=lambda e: e.timestamp)

        report = CapabilityExecutionReport(
            capability_id=capability_id,
            execution_status=execution_status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            events=event_objects,
        )

        # Compute summary
        warning_count = sum(
            1 for e in event_objects if e.event_type == CapabilityExecutionEventType.WARNING.value
        )
        error_count = sum(
            1 for e in event_objects if e.event_type == CapabilityExecutionEventType.ERROR.value
        )

        summary = CapabilityExecutionSummary(
            report_id=report.report_id,
            event_count=len(event_objects),
            warning_count=warning_count,
            error_count=error_count,
        )

        evidence = CapabilityExecutionEvidence(
            report_id=report.report_id,
            summary=self._generate_summary_text(report, summary),
        )

        self._persist_report(report, summary, evidence)
        self._write_evidence(report, summary)

        result = report.to_dict()
        result["summary"] = summary.to_dict()
        result["evidence"] = evidence.to_dict()
        return result

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._report_dir.exists():
            return reports

        sandbox = self._report_dir.resolve()
        for entry in self._report_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not is_within_sandbox(resolved, sandbox):
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
            raise ValueError(f"Execution report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(
        self,
        report: CapabilityExecutionReport,
        summary: CapabilityExecutionSummary,
        evidence: CapabilityExecutionEvidence,
    ) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["summary"] = summary.to_dict()
        data["evidence"] = evidence.to_dict()

        (report_dir / "report.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(
        self,
        report: CapabilityExecutionReport,
        summary: CapabilityExecutionSummary,
    ) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "capability_id": report.capability_id,
            "execution_status": report.execution_status,
            "started_at": report.started_at,
            "completed_at": report.completed_at,
            "duration_ms": report.duration_ms,
            "events": [e.to_dict() for e in report.events],
        }
        (evidence_dir / "capability_execution_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["summary"] = summary.to_dict()
        (evidence_dir / "capability_execution_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict() | {"summary": summary.to_dict()})
        (evidence_dir / "capability_execution_summary.md").write_text(md, encoding="utf-8")

        passed = report.execution_status in (
            CapabilityExecutionStatus.SUCCEEDED.value,
            CapabilityExecutionStatus.PARTIAL_SUCCESS.value,
        )
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "capability_id": report.capability_id,
            "execution_status": report.execution_status,
            "duration_ms": report.duration_ms,
            "event_count": summary.event_count,
            "warning_count": summary.warning_count,
            "error_count": summary.error_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary_text(
        report: CapabilityExecutionReport,
        summary: CapabilityExecutionSummary,
    ) -> str:
        return (
            f"Capability {report.capability_id} execution "
            f"{report.execution_status}: "
            f"{summary.event_count} events, "
            f"{summary.warning_count} warnings, "
            f"{summary.error_count} errors, "
            f"{report.duration_ms}ms"
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Execution Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Capability ID: {data.get('capability_id', '')}")
        lines.append(f"- Status: {data.get('execution_status', '')}")
        lines.append(f"- Started: {data.get('started_at', '')}")
        lines.append(f"- Completed: {data.get('completed_at', '')}")
        lines.append(f"- Duration: {data.get('duration_ms', 0)}ms")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        summary = data.get("summary", {})
        if summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(f"- Events: {summary.get('event_count', 0)}")
            lines.append(f"- Warnings: {summary.get('warning_count', 0)}")
            lines.append(f"- Errors: {summary.get('error_count', 0)}")
            lines.append("")

        events = data.get("events", [])
        if events:
            lines.append("## Event Timeline")
            lines.append("")
            for ev in events:
                etype = ev.get("event_type", "").upper()
                msg = ev.get("message", "")
                ts = ev.get("timestamp", "")
                lines.append(f"- [{etype}] {ts}: {msg}")
            lines.append("")

        return "\n".join(lines)
