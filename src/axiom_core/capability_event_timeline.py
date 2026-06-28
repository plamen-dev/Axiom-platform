"""Capability Event Timeline Framework v1.

Capture everything that happened around a capability rather than only the PR
itself: PR lifecycle, CI, review, bug fixes, tests, artifacts, recordings,
screenshots, skills, warnings, and notes. Events are append-only and ordered
deterministically.

Non-goals: no GitHub ingestion, no Devin ingestion, no orchestration.
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityEventType(str, Enum):
    PR_CREATED = "pr_created"
    CI_GREEN = "ci_green"
    REVIEW_STARTED = "review_started"
    REVIEW_FINDING = "review_finding"
    BUG_FIXED = "bug_fixed"
    TEST_STARTED = "test_started"
    TEST_COMPLETED = "test_completed"
    ARTIFACT_CREATED = "artifact_created"
    VIDEO_RECORDED = "video_recorded"
    SCREENSHOT_CAPTURED = "screenshot_captured"
    SKILL_PROPOSED = "skill_proposed"
    SKILL_APPROVED = "skill_approved"
    PR_READY = "pr_ready"
    PR_MERGED = "pr_merged"
    WARNING = "warning"
    NOTE = "note"


_VALID_EVENT_TYPES = {t.value for t in CapabilityEventType}


# ---------------------------------------------------------------------------
# Reference / artifact models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityEventReference:
    """A reference from an event to an external entity.

    May point to files, commits, artifacts, screenshots, recordings, markdown
    reports, skills, or PR URLs.
    """

    reference_type: str = ""
    target: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_type": self.reference_type,
            "target": self.target,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityEventReference:
        return cls(
            reference_type=data.get("reference_type", ""),
            target=data.get("target", ""),
            label=data.get("label", ""),
        )


@dataclass
class CapabilityEventArtifact:
    """An artifact produced in connection with an event."""

    artifact_type: str = ""
    path: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "path": self.path,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityEventArtifact:
        return cls(
            artifact_type=data.get("artifact_type", ""),
            path=data.get("path", ""),
            description=data.get("description", ""),
        )


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


@dataclass
class CapabilityEvent:
    """A single append-only event in a capability's timeline."""

    event_id: str = ""
    global_capability_id: str = ""
    timestamp: str = ""
    event_sequence: int = 0
    worker: str = ""
    source: str = ""
    event_type: str = "note"
    summary: str = ""
    references: list[CapabilityEventReference] = field(default_factory=list)
    artifacts: list[CapabilityEventArtifact] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = str(uuid4())
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "global_capability_id": self.global_capability_id,
            "timestamp": self.timestamp,
            "event_sequence": self.event_sequence,
            "worker": self.worker,
            "source": self.source,
            "event_type": self.event_type,
            "summary": self.summary,
            "references": [r.to_dict() for r in self.references],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "raw_payload": dict(self.raw_payload),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Timeline / Summary / Evidence
# ---------------------------------------------------------------------------


@dataclass
class CapabilityEventTimeline:
    """An append-only, deterministically ordered collection of events."""

    timeline_id: str = ""
    global_capability_id: str = ""
    events: list[CapabilityEvent] = field(default_factory=list)
    event_count: int = 0
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.timeline_id:
            self.timeline_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeline_id": self.timeline_id,
            "global_capability_id": self.global_capability_id,
            "events": [e.to_dict() for e in self.events],
            "event_count": self.event_count,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass
class CapabilityEventSummary:
    """Aggregate summary over a timeline's events."""

    summary_id: str = ""
    timeline_id: str = ""
    event_count: int = 0
    event_type_counts: dict[str, int] = field(default_factory=dict)
    first_timestamp: str = ""
    last_timestamp: str = ""
    duplicate_sequence_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.summary_id:
            self.summary_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "timeline_id": self.timeline_id,
            "event_count": self.event_count,
            "event_type_counts": dict(self.event_type_counts),
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "duplicate_sequence_count": self.duplicate_sequence_count,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityEventEvidence:
    """Evidence record for a capability event timeline."""

    evidence_id: str = ""
    timeline_id: str = ""
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
            "timeline_id": self.timeline_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CapabilityEventTimelineEngine:
    """Manages capability event timelines deterministically (append-only)."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_event_timeline"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def _safe_path(self, timeline_id: str) -> Path:
        target = (self._report_dir / timeline_id).resolve()
        sandbox = self._report_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {timeline_id!r}"
            )
        return target

    @staticmethod
    def _sort_key(event: CapabilityEvent) -> tuple:
        # Authoritative timeline ordering.
        return (
            event.timestamp,
            event.event_sequence,
            event.event_type,
            event.event_id,
        )

    @staticmethod
    def _build_event(data: dict[str, Any]) -> CapabilityEvent:
        event_type = data.get("event_type", "note")
        if event_type not in _VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type: {event_type!r}. "
                f"Valid: {sorted(_VALID_EVENT_TYPES)}"
            )
        summary = data.get("summary", "")
        if not summary or not summary.strip():
            raise ValueError("summary is required for an event")
        return CapabilityEvent(
            event_id=data.get("event_id", ""),
            global_capability_id=data.get("global_capability_id", ""),
            timestamp=data.get("timestamp", ""),
            event_sequence=int(data.get("event_sequence", 0)),
            worker=data.get("worker", ""),
            source=data.get("source", ""),
            event_type=event_type,
            summary=summary,
            references=[
                CapabilityEventReference.from_dict(r)
                for r in data.get("references", [])
            ],
            artifacts=[
                CapabilityEventArtifact.from_dict(a)
                for a in data.get("artifacts", [])
            ],
            raw_payload=dict(data.get("raw_payload", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    def _assemble(
        self, timeline: CapabilityEventTimeline
    ) -> dict[str, Any]:
        timeline.events.sort(key=self._sort_key)
        timeline.event_count = len(timeline.events)

        type_counts: dict[str, int] = {}
        seen_sequences: set[int] = set()
        duplicate_sequence_count = 0
        for e in timeline.events:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1
            if e.event_sequence in seen_sequences:
                duplicate_sequence_count += 1
            else:
                seen_sequences.add(e.event_sequence)
        type_counts = {k: type_counts[k] for k in sorted(type_counts)}

        summary = CapabilityEventSummary(
            timeline_id=timeline.timeline_id,
            event_count=timeline.event_count,
            event_type_counts=type_counts,
            first_timestamp=(
                timeline.events[0].timestamp if timeline.events else ""
            ),
            last_timestamp=(
                timeline.events[-1].timestamp if timeline.events else ""
            ),
            duplicate_sequence_count=duplicate_sequence_count,
        )

        report = dict(timeline.to_dict())
        report["summary"] = summary.to_dict()
        return report

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        global_capability_id: str = "",
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new event timeline from events."""
        events = events or []
        timeline = CapabilityEventTimeline(
            global_capability_id=global_capability_id
        )
        timeline.events = [self._build_event(e) for e in events]

        report = self._assemble(timeline)
        self._persist(report)
        self._write_evidence(report)
        return report

    def append(
        self, timeline_id: str, events: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Append events to an existing timeline (append-only; no removal)."""
        self._validate_id_segment(timeline_id, "timeline_id")
        existing = self._load_report(timeline_id)
        if existing is None:
            raise ValueError(f"Timeline not found: {timeline_id}")

        events = events or []
        timeline = CapabilityEventTimeline(
            timeline_id=existing["timeline_id"],
            global_capability_id=existing.get("global_capability_id", ""),
            created_at=existing.get("created_at", ""),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        # Preserve existing events verbatim (append-only).
        timeline.events = [
            self._build_event(e) for e in existing.get("events", [])
        ]
        timeline.events.extend(self._build_event(e) for e in events)

        report = self._assemble(timeline)
        self._persist(report)
        self._write_evidence(report)
        return report

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, timeline_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(timeline_id, "timeline_id")
        return self._load_report(timeline_id)

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

    def export_report(self, timeline_id: str, fmt: str = "markdown") -> str:
        self._validate_id_segment(timeline_id, "timeline_id")
        data = self._load_report(timeline_id)
        if data is None:
            raise ValueError(f"Timeline not found: {timeline_id}")
        fmt = (fmt or "markdown").lower()
        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        if fmt == "csv":
            return self._generate_export_csv(data)
        if fmt == "markdown":
            return self._generate_export_md(data)
        raise ValueError(
            f"Invalid export format: {fmt!r}. "
            "Valid: ['csv', 'json', 'markdown']"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: dict[str, Any]) -> None:
        report_dir = self._safe_path(report["timeline_id"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, timeline_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_path(timeline_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: dict[str, Any]) -> None:
        evidence_dir = self._safe_path(report["timeline_id"])
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "timeline_id": report["timeline_id"],
            "global_capability_id": report.get("global_capability_id", ""),
            "events": report.get("events", []),
        }
        (evidence_dir / "capability_event_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_event_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_event_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        (evidence_dir / "capability_event_timeline.csv").write_text(
            self._generate_export_csv(report), encoding="utf-8"
        )

        summary = report.get("summary", {})
        evidence = CapabilityEventEvidence(
            timeline_id=report["timeline_id"],
            summary=(
                f"{report.get('event_count', 0)} events, "
                f"{len(summary.get('event_type_counts', {}))} event types"
            ),
        )

        # A timeline passes when it has at least one event and no two events
        # share the same event_sequence (append-only monotonic integrity).
        event_count = report.get("event_count", 0)
        duplicate_sequence_count = summary.get("duplicate_sequence_count", 0)
        passed = event_count > 0 and duplicate_sequence_count == 0
        pass_fail = {
            "passed": passed,
            "timeline_id": report["timeline_id"],
            "evidence_id": evidence.evidence_id,
            "event_count": event_count,
            "duplicate_sequence_count": duplicate_sequence_count,
            "event_type_counts": dict(summary.get("event_type_counts", {})),
            "schema_version": report.get("schema_version", SCHEMA_VERSION),
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Exporters
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Event Timeline")
        lines.append("")
        lines.append(f"- Timeline ID: {data.get('timeline_id', '')}")
        lines.append(
            f"- Global Capability ID: {data.get('global_capability_id', '')}"
        )
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        summary = data.get("summary", {})
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Events: {data.get('event_count', 0)}")
        lines.append(
            f"- Duplicate Sequences: "
            f"{summary.get('duplicate_sequence_count', 0)}"
        )
        lines.append(f"- First: {summary.get('first_timestamp', '')}")
        lines.append(f"- Last: {summary.get('last_timestamp', '')}")
        lines.append("")

        type_counts = summary.get("event_type_counts", {})
        lines.append("## Event Type Counts")
        lines.append("")
        for event_type in sorted(type_counts):
            lines.append(f"- {event_type.upper()}: {type_counts[event_type]}")
        lines.append("")

        events = data.get("events", [])
        if events:
            lines.append("## Timeline")
            lines.append("")
            for e in events:
                seq = e.get("event_sequence", 0)
                etype = e.get("event_type", "").upper()
                ts = e.get("timestamp", "")
                summary_text = e.get("summary", "")
                lines.append(f"- [{seq}] {ts} [{etype}] {summary_text}")
                for ref in e.get("references", []):
                    rtype = ref.get("reference_type", "")
                    target = ref.get("target", "")
                    lines.append(f"    - ref ({rtype}): {target}")
                for art in e.get("artifacts", []):
                    atype = art.get("artifact_type", "")
                    path = art.get("path", "")
                    lines.append(f"    - artifact ({atype}): {path}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "event_sequence",
                "timestamp",
                "event_type",
                "event_id",
                "global_capability_id",
                "worker",
                "source",
                "summary",
                "reference_count",
                "artifact_count",
                "schema_version",
            ]
        )
        for e in data.get("events", []):
            writer.writerow(
                [
                    e.get("event_sequence", 0),
                    e.get("timestamp", ""),
                    e.get("event_type", ""),
                    e.get("event_id", ""),
                    e.get("global_capability_id", ""),
                    e.get("worker", ""),
                    e.get("source", ""),
                    e.get("summary", ""),
                    len(e.get("references", [])),
                    len(e.get("artifacts", [])),
                    e.get("schema_version", ""),
                ]
            )
        return buf.getvalue()
