"""Failure Classification Framework v1.

Provides deterministic classification of failures produced by execution
outcomes, on top of the Execution Outcome Framework. Where an outcome records
*what resulted* from an attempt, a failure classification records *why* a
failed outcome failed, organizing failures into reusable types, categories, and
severities, with evidence bundles.

Non-goals: no repair engine, no schedulers, no worker orchestration,
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

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FailureType(str, Enum):
    VALIDATION_FAILURE = "validation_failure"
    TEST_FAILURE = "test_failure"
    REVIEW_FAILURE = "review_failure"
    EXECUTION_FAILURE = "execution_failure"
    CONFIGURATION_FAILURE = "configuration_failure"
    UNKNOWN_FAILURE = "unknown_failure"


class FailureCategory(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    LOGIC = "logic"
    ENVIRONMENT = "environment"
    DATA = "data"
    UNKNOWN = "unknown"


class FailureSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


_VALID_TYPES = {t.value for t in FailureType}
_VALID_CATEGORIES = {c.value for c in FailureCategory}
_VALID_SEVERITIES = {s.value for s in FailureSeverity}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FailureClassification:
    """A single classification of a failed execution outcome."""

    classification_id: str = ""
    outcome_id: str = ""
    failure_type: str = "unknown_failure"
    category: str = "unknown"
    severity: str = "error"
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.classification_id:
            self.classification_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification_id": self.classification_id,
            "outcome_id": self.outcome_id,
            "failure_type": self.failure_type,
            "category": self.category,
            "severity": self.severity,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class FailureClassificationReport:
    """Report summarizing a set of failure classifications."""

    report_id: str = ""
    classification_count: int = 0
    info_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    critical_count: int = 0
    created_at: str = ""
    classifications: list[FailureClassification] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "classification_count": self.classification_count,
            "info_count": self.info_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "critical_count": self.critical_count,
            "created_at": self.created_at,
            "classifications": [c.to_dict() for c in self.classifications],
        }


@dataclass
class FailureClassificationEvidence:
    """Evidence record for a failure classification report."""

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


class FailureClassificationEngine:
    """Manages failure classification reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "failure_classifications"
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

    def create(
        self, classifications: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Create a failure classification report from a list of classifications."""
        classifications = classifications or []

        classification_objects: list[FailureClassification] = []
        for c_data in classifications:
            failure_type = c_data.get("failure_type", "unknown_failure")
            if failure_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid failure_type: {failure_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            category = c_data.get("category", "unknown")
            if category not in _VALID_CATEGORIES:
                raise ValueError(
                    f"Invalid category: {category!r}. "
                    f"Valid: {sorted(_VALID_CATEGORIES)}"
                )
            severity = c_data.get("severity", "error")
            if severity not in _VALID_SEVERITIES:
                raise ValueError(
                    f"Invalid severity: {severity!r}. "
                    f"Valid: {sorted(_VALID_SEVERITIES)}"
                )
            outcome_id = c_data.get("outcome_id", "")
            if not outcome_id:
                raise ValueError(
                    "outcome_id is required for a failure classification"
                )
            classification_objects.append(
                FailureClassification(
                    outcome_id=outcome_id,
                    failure_type=failure_type,
                    category=category,
                    severity=severity,
                    summary=c_data.get("summary", ""),
                    created_at=c_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: chronological by created_at, then outcome_id,
        # then classification_id for stability.
        classification_objects.sort(
            key=lambda c: (c.created_at, c.outcome_id, c.classification_id)
        )

        info = sum(1 for c in classification_objects if c.severity == "info")
        warning = sum(1 for c in classification_objects if c.severity == "warning")
        error = sum(1 for c in classification_objects if c.severity == "error")
        critical = sum(1 for c in classification_objects if c.severity == "critical")

        report = FailureClassificationReport(
            classification_count=len(classification_objects),
            info_count=info,
            warning_count=warning,
            error_count=error,
            critical_count=critical,
            classifications=classification_objects,
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
            raise ValueError(f"Failure classification report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: FailureClassificationReport) -> None:
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

    def _write_evidence(self, report: FailureClassificationReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "classifications": [c.to_dict() for c in report.classifications]
        }
        (evidence_dir / "failure_classification_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "failure_classification_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "failure_classification_summary.md").write_text(
            md, encoding="utf-8"
        )

        evidence = FailureClassificationEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.classification_count} classifications, "
                f"{report.critical_count} critical, "
                f"{report.error_count} error"
            ),
        )

        # A failure classification report passes when no classification is
        # critical or error severity.
        passed = report.critical_count == 0 and report.error_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "classification_count": report.classification_count,
            "info_count": report.info_count,
            "warning_count": report.warning_count,
            "error_count": report.error_count,
            "critical_count": report.critical_count,
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

        lines.append("# Failure Classification Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Severity Counts")
        lines.append("")
        lines.append(f"- Classifications: {data.get('classification_count', 0)}")
        lines.append(f"- Info: {data.get('info_count', 0)}")
        lines.append(f"- Warning: {data.get('warning_count', 0)}")
        lines.append(f"- Error: {data.get('error_count', 0)}")
        lines.append(f"- Critical: {data.get('critical_count', 0)}")
        lines.append("")

        classifications = data.get("classifications", [])

        if classifications:
            category_counts: dict[str, int] = {}
            for c in classifications:
                category = c.get("category", "unknown")
                category_counts[category] = category_counts.get(category, 0) + 1

            lines.append("## Category Counts")
            lines.append("")
            for category in sorted(category_counts):
                lines.append(f"- {category.upper()}: {category_counts[category]}")
            lines.append("")

            lines.append("## Classifications")
            lines.append("")
            for c in classifications:
                failure_type = c.get("failure_type", "").upper()
                category = c.get("category", "").upper()
                severity = c.get("severity", "").upper()
                outcome_id = c.get("outcome_id", "")
                summary = c.get("summary", "")
                line = (
                    f"- [{severity}] [{failure_type}] [{category}] {outcome_id}"
                )
                if summary:
                    line += f" — {summary}"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)
