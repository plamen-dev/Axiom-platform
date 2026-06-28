"""Structured Configuration Validation Framework v1.

Validates configuration entries against explicit rules, produces
violation reports, persists results, and generates evidence bundles.

Non-goals: no generalized schema systems, no workflow engines,
no schedulers, no architecture changes.
"""

from __future__ import annotations

import json
import logging
import os
import re as re_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationRuleType(str, Enum):
    REQUIRED_KEY = "required_key"
    ALLOWED_VALUES = "allowed_values"
    NON_EMPTY = "non_empty"
    REGEX_MATCH = "regex_match"
    CUSTOM = "custom"


class ViolationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationRule:
    """A validation rule for configuration entries."""

    rule_id: str = ""
    key_pattern: str = ""
    rule_type: ConfigurationRuleType = ConfigurationRuleType.REQUIRED_KEY
    required: bool = True
    expected_values: list[str] = field(default_factory=list)
    regex_pattern: str = ""
    custom_validator: Callable[[str, str], str | None] | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id:
            self.rule_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "key_pattern": self.key_pattern,
            "rule_type": self.rule_type.value,
            "required": self.required,
            "expected_values": list(self.expected_values),
            "regex_pattern": self.regex_pattern,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationViolation:
    """A single validation violation."""

    violation_id: str = ""
    key: str = ""
    message: str = ""
    severity: ViolationSeverity = ViolationSeverity.ERROR

    def __post_init__(self) -> None:
        if not self.violation_id:
            self.violation_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "key": self.key,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass
class ConfigurationValidationReport:
    """Report produced by validating a configuration against rules."""

    report_id: str = ""
    config_id: str = ""
    valid: bool = True
    violations: list[ConfigurationViolation] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    rules_checked: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "config_id": self.config_id,
            "valid": self.valid,
            "violations": [v.to_dict() for v in self.violations],
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "rules_checked": self.rules_checked,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Validation engine
# ---------------------------------------------------------------------------


class ConfigurationValidator:
    """Validates configuration entries against explicit rules."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._validations_dir = self._artifacts_root / "config_validation"
        self._validations_dir.mkdir(parents=True, exist_ok=True)

    def _safe_validation_path(self, report_id: str) -> Path:
        target = (self._validations_dir / report_id).resolve()
        sandbox = self._validations_dir.resolve()
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

    def validate(
        self,
        config: dict[str, Any],
        rules: list[ConfigurationRule],
    ) -> dict[str, Any]:
        """Validate a configuration against a set of rules."""
        config_id = config.get("config_id", "")
        entries = config.get("entries", [])
        entry_map: dict[str, str] = {}
        for e in entries:
            entry_map[e["key"]] = e["value"]

        violations: list[ConfigurationViolation] = []

        for rule in rules:
            self._apply_rule(rule, entry_map, violations)

        error_count = sum(
            1 for v in violations if v.severity == ViolationSeverity.ERROR
        )
        warning_count = sum(
            1 for v in violations if v.severity == ViolationSeverity.WARNING
        )
        info_count = sum(
            1 for v in violations if v.severity == ViolationSeverity.INFO
        )
        valid = error_count == 0

        report = ConfigurationValidationReport(
            config_id=config_id,
            valid=valid,
            violations=violations,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            rules_checked=len(rules),
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    def _apply_rule(
        self,
        rule: ConfigurationRule,
        entry_map: dict[str, str],
        violations: list[ConfigurationViolation],
    ) -> None:
        """Apply a single rule against the entry map."""
        matching_keys = [
            k for k in entry_map
            if re_mod.fullmatch(rule.key_pattern, k)
        ]

        if rule.rule_type == ConfigurationRuleType.REQUIRED_KEY:
            if not matching_keys:
                violations.append(
                    ConfigurationViolation(
                        key=rule.key_pattern,
                        message=f"Required key missing: {rule.key_pattern}",
                        severity=ViolationSeverity.ERROR,
                    )
                )

        elif rule.rule_type == ConfigurationRuleType.ALLOWED_VALUES:
            for key in matching_keys:
                value = entry_map[key]
                if value not in rule.expected_values:
                    violations.append(
                        ConfigurationViolation(
                            key=key,
                            message=(
                                f"Value '{value}' not in allowed values "
                                f"{rule.expected_values}"
                            ),
                            severity=ViolationSeverity.ERROR,
                        )
                    )

        elif rule.rule_type == ConfigurationRuleType.NON_EMPTY:
            for key in matching_keys:
                value = entry_map[key]
                if not value or not value.strip():
                    violations.append(
                        ConfigurationViolation(
                            key=key,
                            message=f"Value must not be empty for key: {key}",
                            severity=ViolationSeverity.ERROR,
                        )
                    )
            if rule.required and not matching_keys:
                violations.append(
                    ConfigurationViolation(
                        key=rule.key_pattern,
                        message=f"Required key missing: {rule.key_pattern}",
                        severity=ViolationSeverity.ERROR,
                    )
                )

        elif rule.rule_type == ConfigurationRuleType.REGEX_MATCH:
            for key in matching_keys:
                value = entry_map[key]
                if not re_mod.fullmatch(rule.regex_pattern, value):
                    violations.append(
                        ConfigurationViolation(
                            key=key,
                            message=(
                                f"Value '{value}' does not match pattern "
                                f"'{rule.regex_pattern}'"
                            ),
                            severity=ViolationSeverity.ERROR,
                        )
                    )

        elif rule.rule_type == ConfigurationRuleType.CUSTOM:
            for key in matching_keys:
                value = entry_map[key]
                if rule.custom_validator is not None:
                    error = rule.custom_validator(key, value)
                    if error:
                        violations.append(
                            ConfigurationViolation(
                                key=key,
                                message=error,
                                severity=ViolationSeverity.ERROR,
                            )
                        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._validations_dir.exists():
            return reports

        sandbox = self._validations_dir.resolve()
        for entry in self._validations_dir.iterdir():
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
            raise ValueError(f"Validation report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationValidationReport) -> None:
        report_dir = self._safe_validation_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_validation_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(
        self, report: ConfigurationValidationReport,
    ) -> str:
        evidence_dir = self._safe_validation_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report.report_id,
            "config_id": report.config_id,
            "rules_checked": report.rules_checked,
        }
        (evidence_dir / "config_validation_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "config_validation_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_validation_summary.md").write_text(
            md, encoding="utf-8",
        )

        pass_fail = {
            "passed": report.valid,
            "report_id": report.report_id,
            "config_id": report.config_id,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "info_count": report.info_count,
            "rules_checked": report.rules_checked,
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
        valid = data.get("valid", True)
        status = "PASSED" if valid else "FAILED"
        lines.append(f"# Configuration Validation Report ({status})")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Config ID: {data.get('config_id', '')}")
        lines.append(f"- Status: {status}")
        lines.append(f"- Rules checked: {data.get('rules_checked', 0)}")
        lines.append(f"- Errors: {data.get('error_count', 0)}")
        lines.append(f"- Warnings: {data.get('warning_count', 0)}")
        lines.append(f"- Info: {data.get('info_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        violations = data.get("violations", [])
        if violations:
            lines.append("## Violations")
            lines.append("")
            for v in violations:
                sev = v.get("severity", "error").upper()
                lines.append(f"- [{sev}] `{v.get('key', '')}`: {v.get('message', '')}")
            lines.append("")
        else:
            lines.append("## Violations")
            lines.append("")
            lines.append("No violations found.")
            lines.append("")

        return "\n".join(lines)
