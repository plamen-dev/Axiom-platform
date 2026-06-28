"""Configuration Rollback Framework v1.

Provides deterministic rollback capabilities on top of configuration execution.
Allows execution results to be reverted in a traceable and reviewable manner.

Non-goals: no autonomous recovery, no schedulers, no workflow engines,
no external execution, no uncontrolled mutation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationRollbackAction(str, Enum):
    REVERT_APPLIED_CONFIGURATION = "revert_applied_configuration"
    REVERT_REPAIR_APPLICATION = "revert_repair_application"
    VERIFY_ONLY = "verify_only"
    NO_ACTION = "no_action"


class ConfigurationRollbackStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationRollbackRequest:
    """A request to rollback configuration execution actions."""

    rollback_id: str = ""
    execution_result_id: str = ""
    requested_actions: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.rollback_id:
            self.rollback_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rollback_id": self.rollback_id,
            "execution_result_id": self.execution_result_id,
            "requested_actions": self.requested_actions,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationRollbackResult:
    """Result of rolling back configuration actions."""

    result_id: str = ""
    rollback_id: str = ""
    status: ConfigurationRollbackStatus = ConfigurationRollbackStatus.PENDING
    reverted_actions: list[str] = field(default_factory=list)
    failed_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "rollback_id": self.rollback_id,
            "status": self.status.value,
            "reverted_actions": self.reverted_actions,
            "failed_actions": self.failed_actions,
            "warnings": self.warnings,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationRollbackReport:
    """Report summarizing a rollback run."""

    report_id: str = ""
    rollback_id: str = ""
    rollback_summary: str = ""
    status: ConfigurationRollbackStatus = ConfigurationRollbackStatus.PENDING
    request: ConfigurationRollbackRequest | None = None
    result: ConfigurationRollbackResult | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "rollback_id": self.rollback_id,
            "rollback_summary": self.rollback_summary,
            "status": self.status.value,
            "request": self.request.to_dict() if self.request else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Rollback engine
# ---------------------------------------------------------------------------


class ConfigurationRollbackEngine:
    """Rolls back configuration execution actions deterministically."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._rollback_dir = self._artifacts_root / "config_rollback"
        self._rollback_dir.mkdir(parents=True, exist_ok=True)

    def _safe_rollback_path(self, report_id: str) -> Path:
        target = (self._rollback_dir / report_id).resolve()
        sandbox = self._rollback_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def rollback(
        self,
        execution_result: dict[str, Any] | None = None,
        actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Roll back configuration execution actions."""
        execution_result_id = ""
        if execution_result:
            execution_result_id = execution_result.get("result_id", "")

        requested_actions = actions or [ConfigurationRollbackAction.VERIFY_ONLY.value]

        request = ConfigurationRollbackRequest(
            execution_result_id=execution_result_id,
            requested_actions=requested_actions,
        )

        result = self._run_rollback(
            request=request,
            execution_result=execution_result,
        )

        summary = self._build_summary(request, result)

        report = ConfigurationRollbackReport(
            rollback_id=request.rollback_id,
            rollback_summary=summary,
            status=result.status,
            request=request,
            result=result,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    def _run_rollback(
        self,
        request: ConfigurationRollbackRequest,
        execution_result: dict[str, Any] | None,
    ) -> ConfigurationRollbackResult:
        reverted: list[str] = []
        failed: list[str] = []
        warnings: list[str] = []

        applied_actions = []
        if execution_result:
            applied_actions = execution_result.get("applied_actions", [])

        for action_str in request.requested_actions:
            try:
                action = ConfigurationRollbackAction(action_str)
            except ValueError:
                failed.append(action_str)
                warnings.append(f"Unknown rollback action: {action_str}")
                continue

            if action == ConfigurationRollbackAction.NO_ACTION:
                reverted.append(action_str)
                continue

            if action == ConfigurationRollbackAction.VERIFY_ONLY:
                if execution_result is not None:
                    reverted.append(action_str)
                else:
                    failed.append(action_str)
                    warnings.append(
                        "Cannot verify: no execution result provided."
                    )
                continue

            if action == ConfigurationRollbackAction.REVERT_APPLIED_CONFIGURATION:
                if "apply_valid_configuration" in applied_actions:
                    reverted.append(action_str)
                else:
                    failed.append(action_str)
                    warnings.append(
                        "Cannot revert: apply_valid_configuration was not in applied actions."
                    )
                continue

            if action == ConfigurationRollbackAction.REVERT_REPAIR_APPLICATION:
                if "apply_repair_recommendations" in applied_actions:
                    reverted.append(action_str)
                else:
                    failed.append(action_str)
                    warnings.append(
                        "Cannot revert: apply_repair_recommendations was not in applied actions."
                    )
                continue

        if not failed:
            status = ConfigurationRollbackStatus.SUCCEEDED
        elif not reverted:
            status = ConfigurationRollbackStatus.FAILED
        else:
            status = ConfigurationRollbackStatus.PARTIAL_SUCCESS

        return ConfigurationRollbackResult(
            rollback_id=request.rollback_id,
            status=status,
            reverted_actions=reverted,
            failed_actions=failed,
            warnings=warnings,
        )

    def _build_summary(
        self,
        request: ConfigurationRollbackRequest,
        result: ConfigurationRollbackResult,
    ) -> str:
        total = len(request.requested_actions)
        reverted = len(result.reverted_actions)
        failed = len(result.failed_actions)
        return (
            f"Rollback complete: {reverted}/{total} actions reverted, "
            f"{failed} failed. Status: {result.status.value}."
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._rollback_dir.exists():
            return reports

        sandbox = self._rollback_dir.resolve()
        for entry in self._rollback_dir.iterdir():
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
            raise ValueError(f"Rollback report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationRollbackReport) -> None:
        report_dir = self._safe_rollback_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_rollback_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationRollbackReport) -> str:
        evidence_dir = self._safe_rollback_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report.report_id,
            "rollback_id": report.rollback_id,
            "execution_result_id": (
                report.request.execution_result_id if report.request else ""
            ),
            "requested_actions": (
                report.request.requested_actions if report.request else []
            ),
        }
        (evidence_dir / "config_rollback_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "config_rollback_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_rollback_summary.md").write_text(
            md, encoding="utf-8",
        )

        pass_fail = {
            "passed": report.status != ConfigurationRollbackStatus.FAILED,
            "report_id": report.report_id,
            "rollback_id": report.rollback_id,
            "status": report.status.value,
            "reverted_count": (
                len(report.result.reverted_actions) if report.result else 0
            ),
            "failed_count": (
                len(report.result.failed_actions) if report.result else 0
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []
        status = data.get("status", "unknown")

        lines.append("# Configuration Rollback Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Rollback ID: {data.get('rollback_id', '')}")
        lines.append(f"- Status: {status.upper()}")
        lines.append(f"- Summary: {data.get('rollback_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        result = data.get("result")
        if result:
            lines.append("## Rollback Result")
            lines.append("")
            reverted = result.get("reverted_actions", [])
            failed = result.get("failed_actions", [])
            warnings = result.get("warnings", [])
            lines.append(f"- Reverted actions: {', '.join(reverted) or '(none)'}")
            lines.append(f"- Failed actions: {', '.join(failed) or '(none)'}")
            if warnings:
                lines.append("- Warnings:")
                for w in warnings:
                    lines.append(f"  - {w}")
            lines.append("")

        request = data.get("request")
        if request:
            lines.append("## Rollback Request")
            lines.append("")
            lines.append(
                f"- Execution Result ID: {request.get('execution_result_id', '')}"
            )
            actions = request.get("requested_actions", [])
            lines.append(f"- Requested actions: {', '.join(actions)}")
            lines.append("")

        return "\n".join(lines)
