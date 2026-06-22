"""Configuration Execution Framework v1.

Provides controlled, deterministic execution of configuration actions
(apply valid config, apply repair recommendations, verify-only, no-action)
while preserving evidence, reviewability, and repairability.

Non-goals: no autonomous decision-making, no schedulers, no workflow engines,
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

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationExecutionAction(str, Enum):
    APPLY_VALID_CONFIGURATION = "apply_valid_configuration"
    APPLY_REPAIR_RECOMMENDATIONS = "apply_repair_recommendations"
    VERIFY_ONLY = "verify_only"
    NO_ACTION = "no_action"


class ConfigurationExecutionStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationExecutionRequest:
    """A request to execute configuration actions."""

    request_id: str = ""
    config_id: str = ""
    requested_actions: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "config_id": self.config_id,
            "requested_actions": self.requested_actions,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationExecutionResult:
    """Result of executing configuration actions."""

    result_id: str = ""
    request_id: str = ""
    status: ConfigurationExecutionStatus = ConfigurationExecutionStatus.PENDING
    applied_actions: list[str] = field(default_factory=list)
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
            "request_id": self.request_id,
            "status": self.status.value,
            "applied_actions": self.applied_actions,
            "failed_actions": self.failed_actions,
            "warnings": self.warnings,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationExecutionReport:
    """Report summarizing an execution run."""

    report_id: str = ""
    request_id: str = ""
    execution_summary: str = ""
    status: ConfigurationExecutionStatus = ConfigurationExecutionStatus.PENDING
    request: ConfigurationExecutionRequest | None = None
    result: ConfigurationExecutionResult | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "request_id": self.request_id,
            "execution_summary": self.execution_summary,
            "status": self.status.value,
            "request": self.request.to_dict() if self.request else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Execution engine
# ---------------------------------------------------------------------------


class ConfigurationExecutionEngine:
    """Executes configuration actions deterministically."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._execution_dir = self._artifacts_root / "config_execution"
        self._execution_dir.mkdir(parents=True, exist_ok=True)

    def _safe_execution_path(self, report_id: str) -> Path:
        target = (self._execution_dir / report_id).resolve()
        sandbox = self._execution_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
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

    def execute(
        self,
        config: dict[str, Any] | None = None,
        validation_report: dict[str, Any] | None = None,
        repair_report: dict[str, Any] | None = None,
        actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute configuration actions and produce an execution report."""
        config_id = ""
        if config:
            config_id = config.get("config_id", "")
        elif validation_report:
            config_id = validation_report.get("config_id", "")
        elif repair_report:
            config_id = repair_report.get("config_id", "")

        requested_actions = actions or [ConfigurationExecutionAction.VERIFY_ONLY.value]

        request = ConfigurationExecutionRequest(
            config_id=config_id,
            requested_actions=requested_actions,
        )

        result = self._run_actions(
            request=request,
            config=config,
            validation_report=validation_report,
            repair_report=repair_report,
        )

        summary = self._build_summary(request, result)

        report = ConfigurationExecutionReport(
            request_id=request.request_id,
            execution_summary=summary,
            status=result.status,
            request=request,
            result=result,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    def _run_actions(
        self,
        request: ConfigurationExecutionRequest,
        config: dict[str, Any] | None,
        validation_report: dict[str, Any] | None,
        repair_report: dict[str, Any] | None,
    ) -> ConfigurationExecutionResult:
        applied: list[str] = []
        failed: list[str] = []
        warnings: list[str] = []

        for action_str in request.requested_actions:
            try:
                action = ConfigurationExecutionAction(action_str)
            except ValueError:
                failed.append(action_str)
                warnings.append(f"Unknown action: {action_str}")
                continue

            if action == ConfigurationExecutionAction.NO_ACTION:
                applied.append(action_str)
                continue

            if action == ConfigurationExecutionAction.VERIFY_ONLY:
                success = self._verify_only(config, validation_report)
                if success:
                    applied.append(action_str)
                else:
                    failed.append(action_str)
                    warnings.append("Verification failed: validation has violations.")
                continue

            if action == ConfigurationExecutionAction.APPLY_VALID_CONFIGURATION:
                success = self._apply_valid(config, validation_report)
                if success:
                    applied.append(action_str)
                else:
                    failed.append(action_str)
                    warnings.append(
                        "Cannot apply configuration: validation did not pass."
                    )
                continue

            if action == ConfigurationExecutionAction.APPLY_REPAIR_RECOMMENDATIONS:
                success = self._apply_repair(repair_report)
                if success:
                    applied.append(action_str)
                else:
                    failed.append(action_str)
                    warnings.append(
                        "Cannot apply repairs: no repairable recommendations."
                    )
                continue

        if not failed:
            status = ConfigurationExecutionStatus.SUCCEEDED
        elif not applied:
            status = ConfigurationExecutionStatus.FAILED
        else:
            status = ConfigurationExecutionStatus.PARTIAL_SUCCESS

        return ConfigurationExecutionResult(
            request_id=request.request_id,
            status=status,
            applied_actions=applied,
            failed_actions=failed,
            warnings=warnings,
        )

    def _verify_only(
        self,
        config: dict[str, Any] | None,
        validation_report: dict[str, Any] | None,
    ) -> bool:
        if validation_report is not None:
            return validation_report.get("valid", False)
        if config is not None:
            return True
        return False

    def _apply_valid(
        self,
        config: dict[str, Any] | None,
        validation_report: dict[str, Any] | None,
    ) -> bool:
        if validation_report is None:
            return False
        return validation_report.get("valid", False)

    def _apply_repair(
        self,
        repair_report: dict[str, Any] | None,
    ) -> bool:
        if repair_report is None:
            return False
        return repair_report.get("repairable_count", 0) > 0

    def _build_summary(
        self,
        request: ConfigurationExecutionRequest,
        result: ConfigurationExecutionResult,
    ) -> str:
        total = len(request.requested_actions)
        applied = len(result.applied_actions)
        failed = len(result.failed_actions)
        return (
            f"Execution complete: {applied}/{total} actions succeeded, "
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
        if not self._execution_dir.exists():
            return reports

        sandbox = self._execution_dir.resolve()
        for entry in self._execution_dir.iterdir():
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
            raise ValueError(f"Execution report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationExecutionReport) -> None:
        report_dir = self._safe_execution_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_execution_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationExecutionReport) -> str:
        evidence_dir = self._safe_execution_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report.report_id,
            "request_id": report.request_id,
            "config_id": report.request.config_id if report.request else "",
            "requested_actions": (
                report.request.requested_actions if report.request else []
            ),
        }
        (evidence_dir / "config_execution_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "config_execution_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_execution_summary.md").write_text(
            md, encoding="utf-8",
        )

        pass_fail = {
            "passed": report.status != ConfigurationExecutionStatus.FAILED,
            "report_id": report.report_id,
            "request_id": report.request_id,
            "status": report.status.value,
            "applied_count": (
                len(report.result.applied_actions) if report.result else 0
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

        lines.append("# Configuration Execution Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Request ID: {data.get('request_id', '')}")
        lines.append(f"- Status: {status.upper()}")
        lines.append(f"- Summary: {data.get('execution_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        result = data.get("result")
        if result:
            lines.append("## Execution Result")
            lines.append("")
            applied = result.get("applied_actions", [])
            failed = result.get("failed_actions", [])
            warnings = result.get("warnings", [])
            lines.append(f"- Applied actions: {', '.join(applied) or '(none)'}")
            lines.append(f"- Failed actions: {', '.join(failed) or '(none)'}")
            if warnings:
                lines.append("- Warnings:")
                for w in warnings:
                    lines.append(f"  - {w}")
            lines.append("")

        request = data.get("request")
        if request:
            lines.append("## Execution Request")
            lines.append("")
            lines.append(f"- Config ID: {request.get('config_id', '')}")
            actions = request.get("requested_actions", [])
            lines.append(f"- Requested actions: {', '.join(actions)}")
            lines.append("")

        return "\n".join(lines)
