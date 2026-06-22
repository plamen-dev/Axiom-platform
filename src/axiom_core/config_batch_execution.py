"""Configuration Batch Execution Framework v1.

Provides deterministic batch execution capabilities on top of configuration
scenarios. Executes multiple configuration scenarios as a batch while
preserving deterministic ordering, reviewability, and evidence quality.

Non-goals: no autonomous scheduling, no worker orchestration, no workflow
engines, no external batch systems.
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


class ConfigurationBatchExecutionMode(str, Enum):
    RUN_ALL = "run_all"
    STOP_ON_FAILURE = "stop_on_failure"
    VERIFY_ONLY = "verify_only"


class ConfigurationBatchItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationBatchExecutionItem:
    """A single scenario execution within a batch."""

    item_id: str = ""
    scenario_id: str = ""
    status: str = "pending"
    passed: bool = False
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.item_id:
            self.item_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "scenario_id": self.scenario_id,
            "status": self.status,
            "passed": self.passed,
            "warnings": self.warnings,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationBatchExecutionRequest:
    """Request to execute a batch of scenarios."""

    batch_id: str = ""
    scenario_ids: list[str] = field(default_factory=list)
    execution_mode: str = "run_all"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.batch_id:
            self.batch_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "scenario_ids": self.scenario_ids,
            "execution_mode": self.execution_mode,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationBatchExecutionResult:
    """Result of a batch execution."""

    result_id: str = ""
    batch_id: str = ""
    items: list[ConfigurationBatchExecutionItem] = field(default_factory=list)
    total_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "batch_id": self.batch_id,
            "items": [i.to_dict() for i in self.items],
            "total_count": self.total_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "warning_count": self.warning_count,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationBatchExecutionReport:
    """Report summarizing a batch execution."""

    report_id: str = ""
    batch_id: str = ""
    batch_summary: str = ""
    request: ConfigurationBatchExecutionRequest | None = None
    result: ConfigurationBatchExecutionResult | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "batch_id": self.batch_id,
            "batch_summary": self.batch_summary,
            "request": self.request.to_dict() if self.request else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Batch execution engine
# ---------------------------------------------------------------------------


class ConfigurationBatchExecutionEngine:
    """Executes batches of configuration scenarios deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._batch_dir = self._artifacts_root / "config_batch_execution"
        self._batch_dir.mkdir(parents=True, exist_ok=True)

    def _safe_batch_path(self, report_id: str) -> Path:
        target = (self._batch_dir / report_id).resolve()
        sandbox = self._batch_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    def run(
        self,
        scenario_ids: list[str] | None = None,
        execution_mode: str = "run_all",
        scenarios: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute a batch of scenarios."""
        scenario_ids = scenario_ids or []
        scenarios = scenarios or []

        request = ConfigurationBatchExecutionRequest(
            scenario_ids=scenario_ids,
            execution_mode=execution_mode,
        )

        items = self._execute_batch(scenarios, execution_mode)

        succeeded_count = sum(
            1 for i in items if i.status == ConfigurationBatchItemStatus.SUCCEEDED.value
        )
        failed_count = sum(
            1 for i in items if i.status == ConfigurationBatchItemStatus.FAILED.value
        )
        skipped_count = sum(
            1 for i in items if i.status == ConfigurationBatchItemStatus.SKIPPED.value
        )
        warning_count = sum(len(i.warnings) for i in items)

        result = ConfigurationBatchExecutionResult(
            batch_id=request.batch_id,
            items=items,
            total_count=len(items),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            warning_count=warning_count,
        )

        batch_summary = (
            f"Batch '{request.batch_id}': "
            f"{succeeded_count} succeeded, {failed_count} failed, "
            f"{skipped_count} skipped, {warning_count} warnings "
            f"(mode: {execution_mode})."
        )

        report = ConfigurationBatchExecutionReport(
            batch_id=request.batch_id,
            batch_summary=batch_summary,
            request=request,
            result=result,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    def _execute_batch(
        self,
        scenarios: list[dict[str, Any]],
        execution_mode: str,
    ) -> list[ConfigurationBatchExecutionItem]:
        items: list[ConfigurationBatchExecutionItem] = []
        stop = False

        for scenario_data in scenarios:
            scenario_id = scenario_data.get("scenario_id", str(uuid4()))

            if stop:
                items.append(
                    ConfigurationBatchExecutionItem(
                        scenario_id=scenario_id,
                        status=ConfigurationBatchItemStatus.SKIPPED.value,
                        passed=False,
                    )
                )
                continue

            item = self._execute_single(scenario_data, execution_mode)
            items.append(item)

            if (
                execution_mode == ConfigurationBatchExecutionMode.STOP_ON_FAILURE.value
                and not item.passed
            ):
                stop = True

        return items

    @staticmethod
    def _execute_single(
        scenario_data: dict[str, Any],
        execution_mode: str,
    ) -> ConfigurationBatchExecutionItem:
        scenario_id = scenario_data.get("scenario_id", "")
        expectations = scenario_data.get("expectations", [])
        warnings: list[str] = []

        if execution_mode == ConfigurationBatchExecutionMode.VERIFY_ONLY.value:
            warnings.append("verify_only: scenario not executed, only validated")
            return ConfigurationBatchExecutionItem(
                scenario_id=scenario_id,
                status=ConfigurationBatchItemStatus.SUCCEEDED.value,
                passed=True,
                warnings=warnings,
            )

        passed = True
        for exp in expectations:
            if exp.get("will_fail", False):
                passed = False
                break

        status = (
            ConfigurationBatchItemStatus.SUCCEEDED.value
            if passed
            else ConfigurationBatchItemStatus.FAILED.value
        )

        return ConfigurationBatchExecutionItem(
            scenario_id=scenario_id,
            status=status,
            passed=passed,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._batch_dir.exists():
            return reports

        sandbox = self._batch_dir.resolve()
        for entry in self._batch_dir.iterdir():
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
            raise ValueError(f"Batch report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationBatchExecutionReport) -> None:
        report_dir = self._safe_batch_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_batch_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationBatchExecutionReport) -> None:
        evidence_dir = self._safe_batch_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = report.request.to_dict() if report.request else {}
        (evidence_dir / "config_batch_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.result.to_dict() if report.result else {}
        (evidence_dir / "config_batch_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_batch_summary.md").write_text(
            md,
            encoding="utf-8",
        )

        passed = report.result.failed_count == 0 if report.result else True
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "batch_id": report.batch_id,
            "succeeded_count": report.result.succeeded_count if report.result else 0,
            "failed_count": report.result.failed_count if report.result else 0,
            "skipped_count": report.result.skipped_count if report.result else 0,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Configuration Batch Execution Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Batch ID: {data.get('batch_id', '')}")
        lines.append(f"- Summary: {data.get('batch_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        result = data.get("result")
        if result:
            lines.append("## Counts")
            lines.append("")
            lines.append(f"- Total: {result.get('total_count', 0)}")
            lines.append(f"- Succeeded: {result.get('succeeded_count', 0)}")
            lines.append(f"- Failed: {result.get('failed_count', 0)}")
            lines.append(f"- Skipped: {result.get('skipped_count', 0)}")
            lines.append(f"- Warnings: {result.get('warning_count', 0)}")
            lines.append("")

            items = result.get("items", [])
            if items:
                lines.append("## Items")
                lines.append("")
                for item in items:
                    status = item.get("status", "").upper()
                    lines.append(f"- [{status}] scenario={item.get('scenario_id', '')}")
                    if item.get("warnings"):
                        for w in item["warnings"]:
                            lines.append(f"  Warning: {w}")
                lines.append("")

        return "\n".join(lines)
