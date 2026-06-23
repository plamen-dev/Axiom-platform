"""Recovery Execution Framework v1.

Provides deterministic tracking of attempted recovery execution on top of the
Recovery Recommendation Framework. Where a recovery recommendation records
*what should be done* about a failure, a recovery execution records *what was
attempted* and *its result*: an execution type, status, summary, and a
reference back to the originating recommendation, with evidence bundles.

Non-goals: no autonomous repair execution, no schedulers, no worker
orchestration, no autonomous execution, no approvals, no workflow routing,
no merge behavior.
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


class RecoveryExecutionType(str, Enum):
    RETRY_EXECUTED = "retry_executed"
    REPAIR_EXECUTED = "repair_executed"
    ROLLBACK_EXECUTED = "rollback_executed"
    ESCALATION_RECORDED = "escalation_recorded"
    INVESTIGATION_RECORDED = "investigation_recorded"
    NO_ACTION = "no_action"


class RecoveryExecutionStatus(str, Enum):
    CREATED = "created"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"
    CANCELLED = "cancelled"


_VALID_TYPES = {t.value for t in RecoveryExecutionType}
_VALID_STATUSES = {s.value for s in RecoveryExecutionStatus}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RecoveryExecution:
    """A single attempted recovery execution for a recommendation."""

    execution_id: str = ""
    recommendation_id: str = ""
    execution_type: str = "no_action"
    status: str = "created"
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.execution_id:
            self.execution_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "recommendation_id": self.recommendation_id,
            "execution_type": self.execution_type,
            "status": self.status,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class RecoveryExecutionReport:
    """Report summarizing a set of recovery executions."""

    report_id: str = ""
    execution_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    partial_success_count: int = 0
    cancelled_count: int = 0
    created_at: str = ""
    executions: list[RecoveryExecution] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "execution_count": self.execution_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "partial_success_count": self.partial_success_count,
            "cancelled_count": self.cancelled_count,
            "created_at": self.created_at,
            "executions": [e.to_dict() for e in self.executions],
        }


@dataclass
class RecoveryExecutionEvidence:
    """Evidence record for a recovery execution report."""

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


class RecoveryExecutionEngine:
    """Manages recovery execution reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "recovery_executions"
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

    def create(self, executions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Create a recovery execution report from a list of executions."""
        executions = executions or []

        execution_objects: list[RecoveryExecution] = []
        for e_data in executions:
            execution_type = e_data.get("execution_type", "no_action")
            if execution_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid execution_type: {execution_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            status = e_data.get("status", "created")
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status!r}. Valid: {sorted(_VALID_STATUSES)}"
                )
            recommendation_id = e_data.get("recommendation_id", "")
            if not recommendation_id:
                raise ValueError(
                    "recommendation_id is required for a recovery execution"
                )
            execution_objects.append(
                RecoveryExecution(
                    recommendation_id=recommendation_id,
                    execution_type=execution_type,
                    status=status,
                    summary=e_data.get("summary", ""),
                    created_at=e_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: chronological by created_at, then
        # recommendation_id, then execution_id for stability.
        execution_objects.sort(
            key=lambda e: (e.created_at, e.recommendation_id, e.execution_id)
        )

        succeeded = sum(1 for e in execution_objects if e.status == "succeeded")
        failed = sum(1 for e in execution_objects if e.status == "failed")
        partial = sum(
            1 for e in execution_objects if e.status == "partial_success"
        )
        cancelled = sum(1 for e in execution_objects if e.status == "cancelled")

        report = RecoveryExecutionReport(
            execution_count=len(execution_objects),
            succeeded_count=succeeded,
            failed_count=failed,
            partial_success_count=partial,
            cancelled_count=cancelled,
            executions=execution_objects,
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
            raise ValueError(f"Recovery execution report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: RecoveryExecutionReport) -> None:
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

    def _write_evidence(self, report: RecoveryExecutionReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"executions": [e.to_dict() for e in report.executions]}
        (evidence_dir / "recovery_execution_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "recovery_execution_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "recovery_execution_summary.md").write_text(
            md, encoding="utf-8"
        )

        evidence = RecoveryExecutionEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.execution_count} executions, "
                f"{report.succeeded_count} succeeded, "
                f"{report.failed_count} failed"
            ),
        )

        # A recovery execution report passes when no execution failed.
        passed = report.failed_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "execution_count": report.execution_count,
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

        lines.append("# Recovery Execution Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Status Counts")
        lines.append("")
        lines.append(f"- Executions: {data.get('execution_count', 0)}")
        lines.append(f"- Succeeded: {data.get('succeeded_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(f"- Partial Success: {data.get('partial_success_count', 0)}")
        lines.append(f"- Cancelled: {data.get('cancelled_count', 0)}")
        lines.append("")

        executions = data.get("executions", [])

        if executions:
            type_counts: dict[str, int] = {}
            for e in executions:
                exec_type = e.get("execution_type", "no_action")
                type_counts[exec_type] = type_counts.get(exec_type, 0) + 1

            lines.append("## Type Counts")
            lines.append("")
            for exec_type in sorted(type_counts):
                lines.append(f"- {exec_type.upper()}: {type_counts[exec_type]}")
            lines.append("")

            lines.append("## Executions")
            lines.append("")
            for e in executions:
                exec_type = e.get("execution_type", "").upper()
                status = e.get("status", "").upper()
                recommendation_id = e.get("recommendation_id", "")
                summary = e.get("summary", "")
                line = f"- [{status}] [{exec_type}] {recommendation_id}"
                if summary:
                    line += f" — {summary}"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)
