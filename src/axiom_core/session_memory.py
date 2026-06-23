"""Session Memory Framework v1.

Provides deterministic short-term operational memory across a session on top of
the Recovery Execution and Execution Outcome frameworks. Where prior frameworks
each record one stage of a recovery loop, session memory preserves a compact,
ordered set of memory entries (attempts, outcomes, failures, recommendations,
recoveries, observations) referencing their source records, with evidence
bundles.

Non-goals: no long-term memory, no autonomous learning, no schedulers, no
approvals, no workflow routing, no merge behavior.
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

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SessionMemoryType(str, Enum):
    ATTEMPT = "attempt"
    OUTCOME = "outcome"
    FAILURE = "failure"
    RECOMMENDATION = "recommendation"
    RECOVERY = "recovery"
    OBSERVATION = "observation"


_VALID_TYPES = {t.value for t in SessionMemoryType}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SessionMemoryEntry:
    """A single short-term memory entry referencing a source record."""

    entry_id: str = ""
    memory_type: str = "observation"
    source_id: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.entry_id:
            self.entry_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "memory_type": self.memory_type,
            "source_id": self.source_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class SessionMemory:
    """An ordered collection of session memory entries."""

    memory_id: str = ""
    entries: list[SessionMemoryEntry] = field(default_factory=list)
    entry_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.memory_id:
            self.memory_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "entries": [e.to_dict() for e in self.entries],
            "entry_count": self.entry_count,
            "created_at": self.created_at,
        }


@dataclass
class SessionMemoryReport:
    """Report summarizing a session memory."""

    report_id: str = ""
    memory_id: str = ""
    entry_count: int = 0
    memory_type_counts: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    entries: list[SessionMemoryEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "memory_id": self.memory_id,
            "entry_count": self.entry_count,
            "memory_type_counts": dict(self.memory_type_counts),
            "created_at": self.created_at,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass
class SessionMemoryEvidence:
    """Evidence record for a session memory report."""

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


class SessionMemoryEngine:
    """Manages session memory reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "session_memory"
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
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Create a session memory report from a list of memory entries."""
        entries = entries or []

        entry_objects: list[SessionMemoryEntry] = []
        for e_data in entries:
            memory_type = e_data.get("memory_type", "observation")
            if memory_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid memory_type: {memory_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            source_id = e_data.get("source_id", "")
            if not source_id:
                raise ValueError("source_id is required for a session memory entry")
            entry_objects.append(
                SessionMemoryEntry(
                    memory_type=memory_type,
                    source_id=source_id,
                    summary=e_data.get("summary", ""),
                    created_at=e_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: chronological by created_at, then source_id,
        # then entry_id for stability.
        entry_objects.sort(key=lambda e: (e.created_at, e.source_id, e.entry_id))

        memory_type_counts: dict[str, int] = {}
        for e in entry_objects:
            memory_type_counts[e.memory_type] = (
                memory_type_counts.get(e.memory_type, 0) + 1
            )
        # Deterministic, sorted key ordering for reproducible output.
        memory_type_counts = {
            k: memory_type_counts[k] for k in sorted(memory_type_counts)
        }

        memory = SessionMemory(
            entries=entry_objects,
            entry_count=len(entry_objects),
        )

        report = SessionMemoryReport(
            memory_id=memory.memory_id,
            entry_count=len(entry_objects),
            memory_type_counts=memory_type_counts,
            entries=entry_objects,
        )

        self._persist(report)
        self._write_evidence(report)

        return report.to_dict()

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
            raise ValueError(f"Session memory report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: SessionMemoryReport) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
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

    def _write_evidence(self, report: SessionMemoryReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"entries": [e.to_dict() for e in report.entries]}
        (evidence_dir / "session_memory_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "session_memory_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "session_memory_summary.md").write_text(
            md, encoding="utf-8"
        )

        failure_count = report.memory_type_counts.get("failure", 0)
        evidence = SessionMemoryEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.entry_count} entries, "
                f"{len(report.memory_type_counts)} memory types, "
                f"{failure_count} failure entries"
            ),
        )

        # A session memory report passes when it records no failure entries.
        passed = failure_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "entry_count": report.entry_count,
            "memory_type_counts": dict(report.memory_type_counts),
            "failure_count": failure_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Session Memory Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Memory ID: {data.get('memory_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Memory Summary")
        lines.append("")
        lines.append(f"- Entries: {data.get('entry_count', 0)}")
        lines.append("")

        memory_type_counts = data.get("memory_type_counts", {})
        lines.append("## Type Counts")
        lines.append("")
        for memory_type in sorted(memory_type_counts):
            lines.append(f"- {memory_type.upper()}: {memory_type_counts[memory_type]}")
        lines.append("")

        entries = data.get("entries", [])
        if entries:
            lines.append("## Entries")
            lines.append("")
            for e in entries:
                memory_type = e.get("memory_type", "").upper()
                source_id = e.get("source_id", "")
                summary = e.get("summary", "")
                line = f"- [{memory_type}] {source_id}"
                if summary:
                    line += f" — {summary}"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)
