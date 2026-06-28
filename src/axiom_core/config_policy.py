"""Configuration Policy Framework v1.

Provides deterministic policy evaluation capabilities on top of configuration
validation, repair, explanation, execution, rollback, history, diff, and merge.
Governs whether configurations are acceptable against explicit policy constraints.

Non-goals: no doctrine engine, no human approvals, no schedulers, no workflow
engines, no external policy services, no uncontrolled mutation.
"""

from __future__ import annotations

import json
import os
import re
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


class ConfigurationPolicyRuleType(str, Enum):
    REQUIRED_KEY = "required_key"
    FORBIDDEN_KEY = "forbidden_key"
    ALLOWED_VALUES = "allowed_values"
    DENIED_VALUES = "denied_values"
    NON_EMPTY = "non_empty"
    REGEX_MATCH = "regex_match"


class ConfigurationPolicySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationPolicyRule:
    """A single policy rule."""

    rule_id: str = ""
    key_pattern: str = ""
    rule_type: str = ""
    severity: str = ""
    expected_values: list[str] = field(default_factory=list)
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id:
            self.rule_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "key_pattern": self.key_pattern,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "expected_values": self.expected_values,
            "rationale": self.rationale,
        }


@dataclass
class ConfigurationPolicy:
    """A named policy containing rules."""

    policy_id: str = ""
    name: str = ""
    description: str = ""
    rules: list[ConfigurationPolicyRule] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.policy_id:
            self.policy_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationPolicyViolation:
    """A violation produced when a config entry fails a policy rule."""

    violation_id: str = ""
    key: str = ""
    rule_id: str = ""
    severity: str = ""
    message: str = ""
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.violation_id:
            self.violation_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "key": self.key,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "rationale": self.rationale,
        }


@dataclass
class ConfigurationPolicyResult:
    """Result of evaluating a policy against a configuration."""

    result_id: str = ""
    policy_id: str = ""
    config_id: str = ""
    passed: bool = True
    violations: list[ConfigurationPolicyViolation] = field(default_factory=list)
    blocker_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "policy_id": self.policy_id,
            "config_id": self.config_id,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "blocker_count": self.blocker_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationPolicyReport:
    """Report summarizing a policy evaluation."""

    report_id: str = ""
    result_id: str = ""
    policy_summary: str = ""
    policy: ConfigurationPolicy | None = None
    result: ConfigurationPolicyResult | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "result_id": self.result_id,
            "policy_summary": self.policy_summary,
            "policy": self.policy.to_dict() if self.policy else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


class ConfigurationPolicyEngine:
    """Evaluates configuration against policy rules deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._policy_dir = self._artifacts_root / "config_policy"
        self._policy_dir.mkdir(parents=True, exist_ok=True)

    def _safe_policy_path(self, report_id: str) -> Path:
        target = (self._policy_dir / report_id).resolve()
        sandbox = self._policy_dir.resolve()
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

    def check(
        self,
        config: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate a configuration against a policy."""
        config = config or {}
        policy = policy or {}

        config_id = config.get("config_id", "")
        entries = self._extract_entries(config)

        policy_obj = self._build_policy(policy)
        violations = self._evaluate(entries, policy_obj)

        blocker_count = sum(
            1 for v in violations
            if v.severity == ConfigurationPolicySeverity.BLOCKER.value
        )
        error_count = sum(
            1 for v in violations
            if v.severity == ConfigurationPolicySeverity.ERROR.value
        )
        warning_count = sum(
            1 for v in violations
            if v.severity == ConfigurationPolicySeverity.WARNING.value
        )
        info_count = sum(
            1 for v in violations
            if v.severity == ConfigurationPolicySeverity.INFO.value
        )

        passed = blocker_count == 0 and error_count == 0

        result = ConfigurationPolicyResult(
            policy_id=policy_obj.policy_id,
            config_id=config_id,
            passed=passed,
            violations=violations,
            blocker_count=blocker_count,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
        )

        policy_summary = (
            f"Policy '{policy_obj.name}': "
            f"{'PASSED' if passed else 'FAILED'} — "
            f"{blocker_count} blockers, {error_count} errors, "
            f"{warning_count} warnings, {info_count} info."
        )

        report = ConfigurationPolicyReport(
            result_id=result.result_id,
            policy_summary=policy_summary,
            policy=policy_obj,
            result=result,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    @staticmethod
    def _extract_entries(config: dict[str, Any]) -> dict[str, str]:
        entries: dict[str, str] = {}
        for entry in config.get("entries", []):
            key = entry.get("key", "")
            value = entry.get("value", "")
            if key:
                entries[key] = value
        return entries

    @staticmethod
    def _build_policy(policy: dict[str, Any]) -> ConfigurationPolicy:
        rules: list[ConfigurationPolicyRule] = []
        for rule_data in policy.get("rules", []):
            rules.append(ConfigurationPolicyRule(
                rule_id=rule_data.get("rule_id", ""),
                key_pattern=rule_data.get("key_pattern", ""),
                rule_type=rule_data.get("rule_type", ""),
                severity=rule_data.get("severity", "error"),
                expected_values=rule_data.get("expected_values", []),
                rationale=rule_data.get("rationale", ""),
            ))
        return ConfigurationPolicy(
            policy_id=policy.get("policy_id", ""),
            name=policy.get("name", ""),
            description=policy.get("description", ""),
            rules=rules,
        )

    def _evaluate(
        self,
        entries: dict[str, str],
        policy: ConfigurationPolicy,
    ) -> list[ConfigurationPolicyViolation]:
        violations: list[ConfigurationPolicyViolation] = []

        for rule in sorted(policy.rules, key=lambda r: r.key_pattern):
            rule_type = rule.rule_type

            if rule_type == ConfigurationPolicyRuleType.REQUIRED_KEY.value:
                self._check_required_key(entries, rule, violations)
            elif rule_type == ConfigurationPolicyRuleType.FORBIDDEN_KEY.value:
                self._check_forbidden_key(entries, rule, violations)
            elif rule_type == ConfigurationPolicyRuleType.ALLOWED_VALUES.value:
                self._check_allowed_values(entries, rule, violations)
            elif rule_type == ConfigurationPolicyRuleType.DENIED_VALUES.value:
                self._check_denied_values(entries, rule, violations)
            elif rule_type == ConfigurationPolicyRuleType.NON_EMPTY.value:
                self._check_non_empty(entries, rule, violations)
            elif rule_type == ConfigurationPolicyRuleType.REGEX_MATCH.value:
                self._check_regex_match(entries, rule, violations)

        violations.sort(key=lambda v: (v.key, v.rule_id))
        return violations

    @staticmethod
    def _matching_keys(entries: dict[str, str], pattern: str) -> list[str]:
        regex = re.compile(f"^{re.escape(pattern)}$")
        return sorted(k for k in entries if regex.match(k))

    @staticmethod
    def _check_required_key(
        entries: dict[str, str],
        rule: ConfigurationPolicyRule,
        violations: list[ConfigurationPolicyViolation],
    ) -> None:
        pattern = rule.key_pattern
        regex = re.compile(f"^{re.escape(pattern)}$")
        found = any(regex.match(k) for k in entries)
        if not found:
            violations.append(ConfigurationPolicyViolation(
                key=pattern,
                rule_id=rule.rule_id,
                severity=rule.severity,
                message=f"Required key '{pattern}' is missing",
                rationale=rule.rationale,
            ))

    @staticmethod
    def _check_forbidden_key(
        entries: dict[str, str],
        rule: ConfigurationPolicyRule,
        violations: list[ConfigurationPolicyViolation],
    ) -> None:
        pattern = rule.key_pattern
        regex = re.compile(f"^{re.escape(pattern)}$")
        for key in sorted(entries):
            if regex.match(key):
                violations.append(ConfigurationPolicyViolation(
                    key=key,
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=f"Forbidden key '{key}' is present",
                    rationale=rule.rationale,
                ))

    @staticmethod
    def _check_allowed_values(
        entries: dict[str, str],
        rule: ConfigurationPolicyRule,
        violations: list[ConfigurationPolicyViolation],
    ) -> None:
        pattern = rule.key_pattern
        regex = re.compile(f"^{re.escape(pattern)}$")
        for key in sorted(entries):
            if regex.match(key):
                value = entries[key]
                if value not in rule.expected_values:
                    violations.append(ConfigurationPolicyViolation(
                        key=key,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=(
                            f"Key '{key}' has value '{value}' which is not in "
                            f"allowed values: {rule.expected_values}"
                        ),
                        rationale=rule.rationale,
                    ))

    @staticmethod
    def _check_denied_values(
        entries: dict[str, str],
        rule: ConfigurationPolicyRule,
        violations: list[ConfigurationPolicyViolation],
    ) -> None:
        pattern = rule.key_pattern
        regex = re.compile(f"^{re.escape(pattern)}$")
        for key in sorted(entries):
            if regex.match(key):
                value = entries[key]
                if value in rule.expected_values:
                    violations.append(ConfigurationPolicyViolation(
                        key=key,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=(
                            f"Key '{key}' has denied value '{value}'"
                        ),
                        rationale=rule.rationale,
                    ))

    @staticmethod
    def _check_non_empty(
        entries: dict[str, str],
        rule: ConfigurationPolicyRule,
        violations: list[ConfigurationPolicyViolation],
    ) -> None:
        pattern = rule.key_pattern
        regex = re.compile(f"^{re.escape(pattern)}$")
        for key in sorted(entries):
            if regex.match(key):
                value = entries[key]
                if not value or not value.strip():
                    violations.append(ConfigurationPolicyViolation(
                        key=key,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=f"Key '{key}' must not be empty",
                        rationale=rule.rationale,
                    ))

    @staticmethod
    def _check_regex_match(
        entries: dict[str, str],
        rule: ConfigurationPolicyRule,
        violations: list[ConfigurationPolicyViolation],
    ) -> None:
        pattern = rule.key_pattern
        key_regex = re.compile(f"^{re.escape(pattern)}$")
        value_patterns = rule.expected_values
        if not value_patterns:
            return
        value_regex = re.compile(value_patterns[0])
        for key in sorted(entries):
            if key_regex.match(key):
                value = entries[key]
                if not value_regex.fullmatch(value):
                    violations.append(ConfigurationPolicyViolation(
                        key=key,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=(
                            f"Key '{key}' value '{value}' does not match "
                            f"pattern '{value_patterns[0]}'"
                        ),
                        rationale=rule.rationale,
                    ))

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._policy_dir.exists():
            return reports

        sandbox = self._policy_dir.resolve()
        for entry in self._policy_dir.iterdir():
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
            raise ValueError(f"Policy report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationPolicyReport) -> None:
        report_dir = self._safe_policy_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_policy_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationPolicyReport) -> None:
        evidence_dir = self._safe_policy_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "policy": report.policy.to_dict() if report.policy else {},
            "config_id": report.result.config_id if report.result else "",
        }
        (evidence_dir / "config_policy_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.result.to_dict() if report.result else {}
        (evidence_dir / "config_policy_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_policy_summary.md").write_text(
            md, encoding="utf-8",
        )

        passed = report.result.passed if report.result else True
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "policy_id": report.policy.policy_id if report.policy else "",
            "blocker_count": report.result.blocker_count if report.result else 0,
            "error_count": report.result.error_count if report.result else 0,
            "warning_count": report.result.warning_count if report.result else 0,
            "info_count": report.result.info_count if report.result else 0,
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

        lines.append("# Configuration Policy Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Summary: {data.get('policy_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        result = data.get("result")
        if result:
            lines.append("## Counts")
            lines.append("")
            lines.append(f"- Passed: {result.get('passed', False)}")
            lines.append(f"- Blockers: {result.get('blocker_count', 0)}")
            lines.append(f"- Errors: {result.get('error_count', 0)}")
            lines.append(f"- Warnings: {result.get('warning_count', 0)}")
            lines.append(f"- Info: {result.get('info_count', 0)}")
            lines.append("")

            violations = result.get("violations", [])
            if violations:
                lines.append("## Violations")
                lines.append("")
                for v in violations:
                    lines.append(
                        f"- [{v.get('severity', '').upper()}] "
                        f"{v.get('message', '')}"
                    )
                    if v.get("rationale"):
                        lines.append(f"  Rationale: {v['rationale']}")
                lines.append("")

        return "\n".join(lines)
