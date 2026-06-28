"""Execution Outcome Framework v1.

Provides deterministic representation of the outcomes produced by execution
attempts, on top of the Execution Attempt Framework. Where an attempt records
*that* work was tried (type, status, duration), an outcome records *what
resulted* from that attempt: its outcome type, status, and a summary, with
evidence bundles.

Non-goals: no execution engine, no schedulers, no worker orchestration,
no autonomous execution, no approvals, no workflow routing, no merge behavior.
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


class ExecutionOutcomeType(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL_SUCCESS = "partial_success"
    CANCELLED = "cancelled"
    NO_ACTION = "no_action"


class ExecutionOutcomeStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


_VALID_TYPES = {t.value for t in ExecutionOutcomeType}
_VALID_STATUSES = {s.value for s in ExecutionOutcomeStatus}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionOutcome:
    """A single recorded outcome produced by an execution attempt."""

    outcome_id: str = ""
    attempt_id: str = ""
    outcome_type: str = "success"
    status: str = "completed"
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.outcome_id:
            self.outcome_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "attempt_id": self.attempt_id,
            "outcome_type": self.outcome_type,
            "status": self.status,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class ExecutionOutcomeReport:
    """Report summarizing a set of execution outcomes."""

    report_id: str = ""
    outcome_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    partial_count: int = 0
    cancelled_count: int = 0
    created_at: str = ""
    outcomes: list[ExecutionOutcome] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "outcome_count": self.outcome_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "partial_count": self.partial_count,
            "cancelled_count": self.cancelled_count,
            "created_at": self.created_at,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


@dataclass
class ExecutionOutcomeEvidence:
    """Evidence record for an execution outcome report."""

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


class ExecutionOutcomeEngine:
    """Manages execution outcome reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_outcomes"
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

    def create(self, outcomes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Create an execution outcome report from a list of outcomes."""
        outcomes = outcomes or []

        outcome_objects: list[ExecutionOutcome] = []
        for o_data in outcomes:
            outcome_type = o_data.get("outcome_type", "success")
            if outcome_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid outcome_type: {outcome_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            status = o_data.get("status", "completed")
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status!r}. Valid: {sorted(_VALID_STATUSES)}"
                )
            attempt_id = o_data.get("attempt_id", "")
            if not attempt_id:
                raise ValueError("attempt_id is required for an execution outcome")
            outcome_objects.append(
                ExecutionOutcome(
                    attempt_id=attempt_id,
                    outcome_type=outcome_type,
                    status=status,
                    summary=o_data.get("summary", ""),
                    created_at=o_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: chronological by created_at, then attempt_id,
        # then outcome_id for stability.
        outcome_objects.sort(
            key=lambda o: (o.created_at, o.attempt_id, o.outcome_id)
        )

        success = sum(1 for o in outcome_objects if o.outcome_type == "success")
        failure = sum(1 for o in outcome_objects if o.outcome_type == "failure")
        partial = sum(
            1 for o in outcome_objects if o.outcome_type == "partial_success"
        )
        cancelled = sum(1 for o in outcome_objects if o.outcome_type == "cancelled")

        report = ExecutionOutcomeReport(
            outcome_count=len(outcome_objects),
            success_count=success,
            failure_count=failure,
            partial_count=partial,
            cancelled_count=cancelled,
            outcomes=outcome_objects,
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
            raise ValueError(f"Execution outcome report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: ExecutionOutcomeReport) -> None:
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

    def _write_evidence(self, report: ExecutionOutcomeReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"outcomes": [o.to_dict() for o in report.outcomes]}
        (evidence_dir / "execution_outcome_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_outcome_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "execution_outcome_summary.md").write_text(
            md, encoding="utf-8"
        )

        evidence = ExecutionOutcomeEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.outcome_count} outcomes, "
                f"{report.success_count} success, "
                f"{report.failure_count} failure"
            ),
        )

        # An outcome report passes when no outcome is a failure.
        passed = report.failure_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "outcome_count": report.outcome_count,
            "success_count": report.success_count,
            "failure_count": report.failure_count,
            "partial_count": report.partial_count,
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

        lines.append("# Execution Outcome Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Status Counts")
        lines.append("")
        lines.append(f"- Outcomes: {data.get('outcome_count', 0)}")
        lines.append(f"- Success: {data.get('success_count', 0)}")
        lines.append(f"- Failure: {data.get('failure_count', 0)}")
        lines.append(f"- Partial: {data.get('partial_count', 0)}")
        lines.append(f"- Cancelled: {data.get('cancelled_count', 0)}")
        lines.append("")

        outcomes = data.get("outcomes", [])
        if outcomes:
            lines.append("## Outcomes")
            lines.append("")
            for o in outcomes:
                outcome_type = o.get("outcome_type", "").upper()
                status = o.get("status", "").upper()
                attempt_id = o.get("attempt_id", "")
                summary = o.get("summary", "")
                line = f"- [{outcome_type}] [{status}] {attempt_id}"
                if summary:
                    line += f" — {summary}"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)
