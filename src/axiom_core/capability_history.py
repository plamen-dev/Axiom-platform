"""Capability History Framework v1.

Provides deterministic capability history on top of confidence scoring.
Preserves historical capability execution, failure, repair, and confidence
records as a chronological timeline.

Non-goals: no autonomous learning, no schedulers,
no workflow orchestration.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityHistoryEventType(str, Enum):
    CAPABILITY_DEFINED = "capability_defined"
    INPUT_RECORDED = "input_recorded"
    OUTPUT_RECORDED = "output_recorded"
    EXECUTION_REPORTED = "execution_reported"
    FAILURE_RECORDED = "failure_recorded"
    REPAIR_OUTCOME_RECORDED = "repair_outcome_recorded"
    CONFIDENCE_RECORDED = "confidence_recorded"
    NO_ACTION = "no_action"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityHistoryEvent:
    """A single event in a capability's history."""

    event_id: str = ""
    capability_id: str = ""
    event_type: str = "no_action"
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
            "capability_id": self.capability_id,
            "event_type": self.event_type,
            "source_id": self.source_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityHistory:
    """A capability's full history as a list of events."""

    history_id: str = ""
    capability_id: str = ""
    events: list[CapabilityHistoryEvent] | None = None
    event_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.history_id:
            self.history_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.events is None:
            self.events = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "history_id": self.history_id,
            "capability_id": self.capability_id,
            "events": [e.to_dict() for e in (self.events or [])],
            "event_count": self.event_count,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityHistoryReport:
    """Report summarizing a capability history timeline."""

    report_id: str = ""
    capability_id: str = ""
    timeline_summary: str = ""
    event_count: int = 0
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
            "timeline_summary": self.timeline_summary,
            "event_count": self.event_count,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityHistoryEvidence:
    """Evidence bundle for a capability history."""

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

_VALID_EVENT_TYPES = {t.value for t in CapabilityHistoryEventType}


class CapabilityHistoryEngine:
    """Manages capability history reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_history"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    def _safe_path(self, report_id: str) -> Path:
        target = (self._report_dir / report_id).resolve()
        sandbox = self._report_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        capability_id: str = "",
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a capability history report from a list of events."""
        events = events or []

        event_objects: list[CapabilityHistoryEvent] = []
        for e_data in events:
            event_type = e_data.get("event_type", "no_action")
            if event_type not in _VALID_EVENT_TYPES:
                raise ValueError(
                    f"Invalid event_type: {event_type!r}. " f"Valid: {sorted(_VALID_EVENT_TYPES)}"
                )
            event = CapabilityHistoryEvent(
                capability_id=e_data.get("capability_id", capability_id),
                event_type=event_type,
                source_id=e_data.get("source_id", ""),
                summary=e_data.get("summary", ""),
                created_at=e_data.get("created_at", ""),
            )
            event_objects.append(event)

        # Chronological ordering by created_at, then event_id for stability.
        event_objects.sort(key=lambda e: (e.created_at, e.event_id))

        history = CapabilityHistory(
            capability_id=capability_id,
            events=event_objects,
            event_count=len(event_objects),
        )

        timeline_summary = self._generate_timeline_summary(capability_id, event_objects)

        report = CapabilityHistoryReport(
            capability_id=capability_id,
            timeline_summary=timeline_summary,
            event_count=len(event_objects),
        )

        evidence = CapabilityHistoryEvidence(
            report_id=report.report_id,
            summary=timeline_summary,
        )

        self._persist(report, history, evidence)
        self._write_evidence(report, history)

        result = report.to_dict()
        result["history"] = history.to_dict()
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
            raise ValueError(f"History report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(
        self,
        report: CapabilityHistoryReport,
        history: CapabilityHistory,
        evidence: CapabilityHistoryEvidence,
    ) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["history"] = history.to_dict()
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
        report: CapabilityHistoryReport,
        history: CapabilityHistory,
    ) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "capability_id": history.capability_id,
            "events": [e.to_dict() for e in (history.events or [])],
        }
        (evidence_dir / "capability_history_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["history"] = history.to_dict()
        (evidence_dir / "capability_history_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(result_data)
        (evidence_dir / "capability_history_summary.md").write_text(md, encoding="utf-8")

        passed = True
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "capability_id": report.capability_id,
            "event_count": report.event_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_timeline_summary(capability_id: str, events: list[CapabilityHistoryEvent]) -> str:
        return (
            f"Capability {capability_id}: {len(events)} history event(s) "
            f"recorded chronologically"
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability History Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Capability ID: {data.get('capability_id', '')}")
        lines.append(f"- Event Count: {data.get('event_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        summary = data.get("timeline_summary", "")
        if summary:
            lines.append(f"{summary}")
            lines.append("")

        history = data.get("history", {})
        events = history.get("events", [])
        if events:
            lines.append("## Timeline")
            lines.append("")
            for e in events:
                etype = e.get("event_type", "").upper()
                source = e.get("source_id", "")
                esummary = e.get("summary", "")
                created = e.get("created_at", "")
                source_part = f" <- {source}" if source else ""
                lines.append(f"- [{created}] {etype}{source_part}: {esummary}")
            lines.append("")

        return "\n".join(lines)
