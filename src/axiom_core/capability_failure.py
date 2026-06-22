"""Capability Failure Framework v1.

Provides deterministic failure handling on top of execution reports.
Represents failures and their characteristics explicitly.

Non-goals: no repair execution, no autonomous scheduling,
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

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityFailureType(str, Enum):
    INPUT_FAILURE = "input_failure"
    OUTPUT_FAILURE = "output_failure"
    VALIDATION_FAILURE = "validation_failure"
    EXECUTION_FAILURE = "execution_failure"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"


class CapabilityFailureSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityFailure:
    """A failure that occurred during capability execution."""

    failure_id: str = ""
    report_id: str = ""
    failure_type: str = "execution_failure"
    severity: str = "error"
    message: str = ""
    details: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.failure_id:
            self.failure_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "report_id": self.report_id,
            "failure_type": self.failure_type,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityFailureReport:
    """Report summarizing failures."""

    report_id: str = ""
    failure_count: int = 0
    blocker_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "failure_count": self.failure_count,
            "blocker_count": self.blocker_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityFailureEvidence:
    """Evidence bundle for failures."""

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

_VALID_FAILURE_TYPES = {t.value for t in CapabilityFailureType}
_VALID_SEVERITIES = {s.value for s in CapabilityFailureSeverity}


class CapabilityFailureEngine:
    """Manages capability failure reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_failures"
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
        self,
        failures: list[dict[str, Any]] | None = None,
        report_id: str = "",
    ) -> dict[str, Any]:
        """Create a failure report from a list of failures."""
        failures = failures or []

        failure_objects: list[CapabilityFailure] = []
        for f_data in failures:
            failure_type = f_data.get("failure_type", "execution_failure")
            if failure_type not in _VALID_FAILURE_TYPES:
                raise ValueError(
                    f"Invalid failure_type: {failure_type!r}. "
                    f"Valid: {sorted(_VALID_FAILURE_TYPES)}"
                )
            severity = f_data.get("severity", "error")
            if severity not in _VALID_SEVERITIES:
                raise ValueError(
                    f"Invalid severity: {severity!r}. " f"Valid: {sorted(_VALID_SEVERITIES)}"
                )
            failure = CapabilityFailure(
                report_id=f_data.get("report_id", report_id),
                failure_type=failure_type,
                severity=severity,
                message=f_data.get("message", ""),
                details=f_data.get("details", ""),
            )
            failure_objects.append(failure)

        # Sort by severity (blocker > error > warning > info) then by message
        severity_order = {"blocker": 0, "error": 1, "warning": 2, "info": 3}
        failure_objects.sort(key=lambda f: (severity_order.get(f.severity, 99), f.message))

        blocker_count = sum(1 for f in failure_objects if f.severity == "blocker")
        error_count = sum(1 for f in failure_objects if f.severity == "error")
        warning_count = sum(1 for f in failure_objects if f.severity == "warning")
        info_count = sum(1 for f in failure_objects if f.severity == "info")

        report = CapabilityFailureReport(
            failure_count=len(failure_objects),
            blocker_count=blocker_count,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
        )

        evidence = CapabilityFailureEvidence(
            report_id=report.report_id,
            summary=self._generate_summary_text(report),
        )

        self._persist(report, failure_objects, evidence)
        self._write_evidence(report, failure_objects)

        result = report.to_dict()
        result["failures"] = [f.to_dict() for f in failure_objects]
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
            raise ValueError(f"Failure report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(
        self,
        report: CapabilityFailureReport,
        failures: list[CapabilityFailure],
        evidence: CapabilityFailureEvidence,
    ) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["failures"] = [f.to_dict() for f in failures]
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
        report: CapabilityFailureReport,
        failures: list[CapabilityFailure],
    ) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "failures": [f.to_dict() for f in failures],
        }
        (evidence_dir / "capability_failure_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["failures"] = [f.to_dict() for f in failures]
        (evidence_dir / "capability_failure_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(result_data)
        (evidence_dir / "capability_failure_summary.md").write_text(md, encoding="utf-8")

        passed = report.blocker_count == 0 and report.error_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "failure_count": report.failure_count,
            "blocker_count": report.blocker_count,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "info_count": report.info_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary_text(report: CapabilityFailureReport) -> str:
        return (
            f"Failure report: {report.failure_count} failures "
            f"({report.blocker_count} blockers, "
            f"{report.error_count} errors, "
            f"{report.warning_count} warnings, "
            f"{report.info_count} info)"
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Failure Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Failure Count: {data.get('failure_count', 0)}")
        lines.append(f"- Blockers: {data.get('blocker_count', 0)}")
        lines.append(f"- Errors: {data.get('error_count', 0)}")
        lines.append(f"- Warnings: {data.get('warning_count', 0)}")
        lines.append(f"- Info: {data.get('info_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        failures = data.get("failures", [])
        if failures:
            lines.append("## Failures")
            lines.append("")
            for f in failures:
                sev = f.get("severity", "").upper()
                ftype = f.get("failure_type", "")
                msg = f.get("message", "")
                lines.append(f"- [{sev}] ({ftype}) {msg}")
                details = f.get("details", "")
                if details:
                    lines.append(f"  Details: {details}")
            lines.append("")

        return "\n".join(lines)
