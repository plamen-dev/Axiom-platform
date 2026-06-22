"""Capability Repair Outcome Framework v1.

Provides deterministic repair outcome recording on top of capability retries.
Records and evaluates the results of repair attempts.

Non-goals: no autonomous repair execution, no schedulers,
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


class CapabilityRepairOutcomeType(str, Enum):
    FULL_RECOVERY = "full_recovery"
    PARTIAL_RECOVERY = "partial_recovery"
    NO_RECOVERY = "no_recovery"
    REGRESSION = "regression"


class CapabilityRepairOutcomeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityRepairOutcome:
    """A repair outcome from a retry attempt."""

    outcome_id: str = ""
    retry_id: str = ""
    outcome_type: str = "no_recovery"
    status: str = "failed"
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
            "retry_id": self.retry_id,
            "outcome_type": self.outcome_type,
            "status": self.status,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityRepairOutcomeReport:
    """Report summarizing repair outcomes."""

    report_id: str = ""
    outcome_count: int = 0
    recovery_count: int = 0
    regression_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "outcome_count": self.outcome_count,
            "recovery_count": self.recovery_count,
            "regression_count": self.regression_count,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityRepairOutcomeEvidence:
    """Evidence bundle for repair outcomes."""

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

_VALID_OUTCOME_TYPES = {t.value for t in CapabilityRepairOutcomeType}
_VALID_STATUSES = {s.value for s in CapabilityRepairOutcomeStatus}


class CapabilityRepairOutcomeEngine:
    """Manages capability repair outcome reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_repair_outcomes"
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
        outcomes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a repair outcome report from a list of outcomes."""
        outcomes = outcomes or []

        outcome_objects: list[CapabilityRepairOutcome] = []
        for o_data in outcomes:
            outcome_type = o_data.get("outcome_type", "no_recovery")
            if outcome_type not in _VALID_OUTCOME_TYPES:
                raise ValueError(
                    f"Invalid outcome_type: {outcome_type!r}. "
                    f"Valid: {sorted(_VALID_OUTCOME_TYPES)}"
                )
            status = o_data.get("status", "failed")
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status!r}. " f"Valid: {sorted(_VALID_STATUSES)}"
                )
            outcome = CapabilityRepairOutcome(
                retry_id=o_data.get("retry_id", ""),
                outcome_type=outcome_type,
                status=status,
                summary=o_data.get("summary", ""),
            )
            outcome_objects.append(outcome)

        # Sort by outcome_type for deterministic ordering:
        # regression first (worst), then no_recovery, partial_recovery, full_recovery
        type_order = {
            "regression": 0,
            "no_recovery": 1,
            "partial_recovery": 2,
            "full_recovery": 3,
        }
        outcome_objects.sort(key=lambda o: (type_order.get(o.outcome_type, 99), o.summary))

        recovery_count = sum(
            1 for o in outcome_objects if o.outcome_type in ("full_recovery", "partial_recovery")
        )
        regression_count = sum(1 for o in outcome_objects if o.outcome_type == "regression")

        report = CapabilityRepairOutcomeReport(
            outcome_count=len(outcome_objects),
            recovery_count=recovery_count,
            regression_count=regression_count,
        )

        evidence = CapabilityRepairOutcomeEvidence(
            report_id=report.report_id,
            summary=self._generate_summary_text(report),
        )

        self._persist(report, outcome_objects, evidence)
        self._write_evidence(report, outcome_objects)

        result = report.to_dict()
        result["outcomes"] = [o.to_dict() for o in outcome_objects]
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
            raise ValueError(f"Repair outcome report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(
        self,
        report: CapabilityRepairOutcomeReport,
        outcomes: list[CapabilityRepairOutcome],
        evidence: CapabilityRepairOutcomeEvidence,
    ) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["outcomes"] = [o.to_dict() for o in outcomes]
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
        report: CapabilityRepairOutcomeReport,
        outcomes: list[CapabilityRepairOutcome],
    ) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "outcomes": [o.to_dict() for o in outcomes],
        }
        (evidence_dir / "capability_repair_outcome_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["outcomes"] = [o.to_dict() for o in outcomes]
        (evidence_dir / "capability_repair_outcome_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(result_data)
        (evidence_dir / "capability_repair_outcome_summary.md").write_text(md, encoding="utf-8")

        passed = report.regression_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "outcome_count": report.outcome_count,
            "recovery_count": report.recovery_count,
            "regression_count": report.regression_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary_text(report: CapabilityRepairOutcomeReport) -> str:
        return (
            f"Repair outcome report: {report.outcome_count} outcomes "
            f"({report.recovery_count} recoveries, "
            f"{report.regression_count} regressions)"
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Repair Outcome Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Outcome Count: {data.get('outcome_count', 0)}")
        lines.append(f"- Recoveries: {data.get('recovery_count', 0)}")
        lines.append(f"- Regressions: {data.get('regression_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        outcomes = data.get("outcomes", [])
        if outcomes:
            lines.append("## Outcomes")
            lines.append("")
            for o in outcomes:
                otype = o.get("outcome_type", "").upper()
                status = o.get("status", "").upper()
                summary = o.get("summary", "")
                lines.append(f"- [{otype}] ({status}) {summary}")
            lines.append("")

        return "\n".join(lines)
