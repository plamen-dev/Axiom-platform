"""Configuration Scenario Framework v1.

Provides deterministic configuration scenario evaluation capabilities on top of
configuration policy. Bundles configurations, policies, validation expectations,
and execution intent into named operating scenarios.

Non-goals: no scenario planning engine, no autonomous execution planning,
no schedulers, no workflow engines, no external scenario services.
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


class ConfigurationScenarioExpectationType(str, Enum):
    POLICY_PASS = "policy_pass"
    POLICY_FAIL = "policy_fail"
    VALIDATION_PASS = "validation_pass"
    VALIDATION_FAIL = "validation_fail"
    EXECUTION_SUCCEEDS = "execution_succeeds"
    EXECUTION_FAILS = "execution_fails"
    NO_BLOCKERS = "no_blockers"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationScenarioExpectation:
    """A single expectation within a scenario."""

    expectation_id: str = ""
    expectation_type: str = ""
    expected_value: str = ""
    severity: str = "error"
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.expectation_id:
            self.expectation_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "expectation_type": self.expectation_type,
            "expected_value": self.expected_value,
            "severity": self.severity,
            "rationale": self.rationale,
        }


@dataclass
class ConfigurationScenario:
    """A named operating scenario bundling config, policy, and expectations."""

    scenario_id: str = ""
    name: str = ""
    description: str = ""
    config_id: str = ""
    policy_id: str = ""
    expectations: list[ConfigurationScenarioExpectation] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.scenario_id:
            self.scenario_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "config_id": self.config_id,
            "policy_id": self.policy_id,
            "expectations": [e.to_dict() for e in self.expectations],
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationScenarioResult:
    """Result of evaluating a scenario."""

    result_id: str = ""
    scenario_id: str = ""
    passed: bool = True
    expectation_results: list[dict[str, Any]] = field(default_factory=list)
    blocker_count: int = 0
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
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "expectation_results": self.expectation_results,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationScenarioReport:
    """Report summarizing a scenario evaluation."""

    report_id: str = ""
    scenario_id: str = ""
    scenario_summary: str = ""
    scenario: ConfigurationScenario | None = None
    result: ConfigurationScenarioResult | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "scenario_id": self.scenario_id,
            "scenario_summary": self.scenario_summary,
            "scenario": self.scenario.to_dict() if self.scenario else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Scenario engine
# ---------------------------------------------------------------------------


class ConfigurationScenarioEngine:
    """Evaluates configuration scenarios deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._scenario_dir = self._artifacts_root / "config_scenarios"
        self._scenario_dir.mkdir(parents=True, exist_ok=True)

    def _safe_scenario_path(self, report_id: str) -> Path:
        target = (self._scenario_dir / report_id).resolve()
        sandbox = self._scenario_dir.resolve()
        if not is_within_sandbox(target, sandbox):
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
        scenario: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        policy_result: dict[str, Any] | None = None,
        validation_result: dict[str, Any] | None = None,
        execution_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a scenario evaluation."""
        scenario = scenario or {}
        config = config or {}
        policy_result = policy_result or {}
        validation_result = validation_result or {}
        execution_result = execution_result or {}

        scenario_obj = self._build_scenario(scenario)
        expectation_results = self._evaluate_expectations(
            scenario_obj,
            policy_result,
            validation_result,
            execution_result,
        )

        blocker_count = sum(
            1 for er in expectation_results if not er["met"] and er["severity"] == "blocker"
        )
        warning_count = sum(
            1 for er in expectation_results if not er["met"] and er["severity"] == "warning"
        )

        passed = all(
            er["met"] or er["severity"] in ("warning", "info") for er in expectation_results
        )

        result = ConfigurationScenarioResult(
            scenario_id=scenario_obj.scenario_id,
            passed=passed,
            expectation_results=expectation_results,
            blocker_count=blocker_count,
            warning_count=warning_count,
        )

        summary = (
            f"Scenario '{scenario_obj.name}': "
            f"{'PASSED' if passed else 'FAILED'} — "
            f"{len(expectation_results)} expectations, "
            f"{blocker_count} blockers, {warning_count} warnings."
        )

        report = ConfigurationScenarioReport(
            scenario_id=scenario_obj.scenario_id,
            scenario_summary=summary,
            scenario=scenario_obj,
            result=result,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    @staticmethod
    def _build_scenario(data: dict[str, Any]) -> ConfigurationScenario:
        expectations: list[ConfigurationScenarioExpectation] = []
        for exp_data in data.get("expectations", []):
            expectations.append(
                ConfigurationScenarioExpectation(
                    expectation_id=exp_data.get("expectation_id", ""),
                    expectation_type=exp_data.get("expectation_type", ""),
                    expected_value=exp_data.get("expected_value", ""),
                    severity=exp_data.get("severity", "error"),
                    rationale=exp_data.get("rationale", ""),
                )
            )
        return ConfigurationScenario(
            scenario_id=data.get("scenario_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            config_id=data.get("config_id", ""),
            policy_id=data.get("policy_id", ""),
            expectations=expectations,
        )

    def _evaluate_expectations(
        self,
        scenario: ConfigurationScenario,
        policy_result: dict[str, Any],
        validation_result: dict[str, Any],
        execution_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for exp in sorted(scenario.expectations, key=lambda e: e.expectation_type):
            met = self._check_expectation(
                exp,
                policy_result,
                validation_result,
                execution_result,
            )
            results.append(
                {
                    "expectation_id": exp.expectation_id,
                    "expectation_type": exp.expectation_type,
                    "expected_value": exp.expected_value,
                    "severity": exp.severity,
                    "met": met,
                    "rationale": exp.rationale,
                }
            )

        return results

    @staticmethod
    def _check_expectation(
        exp: ConfigurationScenarioExpectation,
        policy_result: dict[str, Any],
        validation_result: dict[str, Any],
        execution_result: dict[str, Any],
    ) -> bool:
        exp_type = exp.expectation_type

        if exp_type == ConfigurationScenarioExpectationType.POLICY_PASS.value:
            return policy_result.get("passed", False) is True

        if exp_type == ConfigurationScenarioExpectationType.POLICY_FAIL.value:
            return policy_result.get("passed", True) is False

        if exp_type == ConfigurationScenarioExpectationType.VALIDATION_PASS.value:
            return validation_result.get("passed", False) is True

        if exp_type == ConfigurationScenarioExpectationType.VALIDATION_FAIL.value:
            return validation_result.get("passed", True) is False

        if exp_type == ConfigurationScenarioExpectationType.EXECUTION_SUCCEEDS.value:
            status = execution_result.get("status", "")
            return status == "succeeded"

        if exp_type == ConfigurationScenarioExpectationType.EXECUTION_FAILS.value:
            status = execution_result.get("status", "")
            return status == "failed"

        if exp_type == ConfigurationScenarioExpectationType.NO_BLOCKERS.value:
            return policy_result.get("blocker_count", 0) == 0

        return False

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._scenario_dir.exists():
            return reports

        sandbox = self._scenario_dir.resolve()
        for entry in self._scenario_dir.iterdir():
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
            raise ValueError(f"Scenario report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationScenarioReport) -> None:
        report_dir = self._safe_scenario_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_scenario_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationScenarioReport) -> None:
        evidence_dir = self._safe_scenario_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "scenario": report.scenario.to_dict() if report.scenario else {},
        }
        (evidence_dir / "config_scenario_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.result.to_dict() if report.result else {}
        (evidence_dir / "config_scenario_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_scenario_summary.md").write_text(
            md,
            encoding="utf-8",
        )

        passed = report.result.passed if report.result else True
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "scenario_id": report.scenario.scenario_id if report.scenario else "",
            "blocker_count": report.result.blocker_count if report.result else 0,
            "warning_count": report.result.warning_count if report.result else 0,
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

        lines.append("# Configuration Scenario Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Summary: {data.get('scenario_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        result = data.get("result")
        if result:
            lines.append("## Results")
            lines.append("")
            lines.append(f"- Passed: {result.get('passed', False)}")
            lines.append(f"- Blockers: {result.get('blocker_count', 0)}")
            lines.append(f"- Warnings: {result.get('warning_count', 0)}")
            lines.append("")

            exp_results = result.get("expectation_results", [])
            if exp_results:
                lines.append("## Expectations")
                lines.append("")
                for er in exp_results:
                    status = "MET" if er.get("met") else "NOT MET"
                    lines.append(
                        f"- [{er.get('severity', '').upper()}] "
                        f"{er.get('expectation_type', '')}: {status}"
                    )
                    if er.get("rationale"):
                        lines.append(f"  Rationale: {er['rationale']}")
                lines.append("")

        return "\n".join(lines)
