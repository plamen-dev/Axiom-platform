"""Execution Attempt Framework v1.

Provides deterministic tracking of attempts to execute prioritized work, on
top of the Work Prioritization Framework. Records each attempt's type, status,
and duration, with evidence bundles.

Non-goals: no execution engine, no schedulers, no worker orchestration,
no autonomous execution.
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


class ExecutionAttemptType(str, Enum):
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    REPAIR = "repair"
    REVIEW = "review"
    REPORTING = "reporting"
    OTHER = "other"


class ExecutionAttemptStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"
    CANCELLED = "cancelled"


_VALID_TYPES = {t.value for t in ExecutionAttemptType}
_VALID_STATUSES = {s.value for s in ExecutionAttemptStatus}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionAttempt:
    """A single recorded attempt to execute a work item."""

    attempt_id: str = ""
    work_id: str = ""
    priority_result_id: str = ""
    attempt_type: str = "implementation"
    status: str = "created"
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.attempt_id:
            self.attempt_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "work_id": self.work_id,
            "priority_result_id": self.priority_result_id,
            "attempt_type": self.attempt_type,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class ExecutionAttemptReport:
    """Report summarizing a set of execution attempts."""

    report_id: str = ""
    attempt_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    partial_success_count: int = 0
    cancelled_count: int = 0
    created_at: str = ""
    attempts: list[ExecutionAttempt] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "attempt_count": self.attempt_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "partial_success_count": self.partial_success_count,
            "cancelled_count": self.cancelled_count,
            "created_at": self.created_at,
            "attempts": [a.to_dict() for a in self.attempts],
        }


@dataclass
class ExecutionAttemptEvidence:
    """Evidence record for an execution attempt report."""

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


class ExecutionAttemptEngine:
    """Manages execution attempt reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_attempts"
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

    def create(self, attempts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Create an execution attempt report from a list of attempts."""
        attempts = attempts or []

        attempt_objects: list[ExecutionAttempt] = []
        for a_data in attempts:
            attempt_type = a_data.get("attempt_type", "implementation")
            if attempt_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid attempt_type: {attempt_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            status = a_data.get("status", "created")
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status!r}. Valid: {sorted(_VALID_STATUSES)}"
                )
            work_id = a_data.get("work_id", "")
            if not work_id:
                raise ValueError("work_id is required for an execution attempt")
            duration_ms = int(a_data.get("duration_ms", 0))
            if duration_ms < 0:
                raise ValueError("duration_ms must not be negative")
            attempt_objects.append(
                ExecutionAttempt(
                    work_id=work_id,
                    priority_result_id=a_data.get("priority_result_id", ""),
                    attempt_type=attempt_type,
                    status=status,
                    started_at=a_data.get("started_at", ""),
                    completed_at=a_data.get("completed_at", ""),
                    duration_ms=duration_ms,
                    summary=a_data.get("summary", ""),
                    created_at=a_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: chronological by created_at, then started_at,
        # then attempt_id for stability.
        attempt_objects.sort(
            key=lambda a: (a.created_at, a.started_at, a.attempt_id)
        )

        succeeded = sum(1 for a in attempt_objects if a.status == "succeeded")
        failed = sum(1 for a in attempt_objects if a.status == "failed")
        partial = sum(1 for a in attempt_objects if a.status == "partial_success")
        cancelled = sum(1 for a in attempt_objects if a.status == "cancelled")

        report = ExecutionAttemptReport(
            attempt_count=len(attempt_objects),
            succeeded_count=succeeded,
            failed_count=failed,
            partial_success_count=partial,
            cancelled_count=cancelled,
            attempts=attempt_objects,
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
            raise ValueError(f"Execution attempt report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: ExecutionAttemptReport) -> None:
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

    def _write_evidence(self, report: ExecutionAttemptReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"attempts": [a.to_dict() for a in report.attempts]}
        (evidence_dir / "execution_attempt_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_attempt_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "execution_attempt_summary.md").write_text(
            md, encoding="utf-8"
        )

        evidence = ExecutionAttemptEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.attempt_count} attempts, "
                f"{report.succeeded_count} succeeded, "
                f"{report.failed_count} failed"
            ),
        )

        # An attempt report passes when no attempt failed.
        passed = report.failed_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "attempt_count": report.attempt_count,
            "succeeded_count": report.succeeded_count,
            "failed_count": report.failed_count,
            "partial_success_count": report.partial_success_count,
            "cancelled_count": report.cancelled_count,
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

        lines.append("# Execution Attempt Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Status Counts")
        lines.append("")
        lines.append(f"- Attempts: {data.get('attempt_count', 0)}")
        lines.append(f"- Succeeded: {data.get('succeeded_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(f"- Partial Success: {data.get('partial_success_count', 0)}")
        lines.append(f"- Cancelled: {data.get('cancelled_count', 0)}")
        lines.append("")

        attempts = data.get("attempts", [])
        if attempts:
            lines.append("## Attempts")
            lines.append("")
            for a in attempts:
                attempt_type = a.get("attempt_type", "").upper()
                status = a.get("status", "").upper()
                work_id = a.get("work_id", "")
                duration = a.get("duration_ms", 0)
                lines.append(
                    f"- [{attempt_type}] [{status}] {work_id} "
                    f"({duration} ms)"
                )
            lines.append("")

        return "\n".join(lines)
