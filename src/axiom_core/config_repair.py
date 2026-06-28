"""Configuration Repair Recommendation Framework v1.

Generates deterministic, reviewable repair recommendations from
configuration validation violations without applying changes.

Non-goals: no automatic file modification, no patch application,
no approvals, no workflow engines, no schedulers.
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


class ConfigurationRepairAction(str, Enum):
    ADD_MISSING_KEY = "add_missing_key"
    CHANGE_VALUE = "change_value"
    REMOVE_INVALID_KEY = "remove_invalid_key"
    SET_NON_EMPTY_VALUE = "set_non_empty_value"
    NO_ACTION = "no_action"


class ConfigurationRepairReason(str, Enum):
    REQUIRED_KEY_MISSING = "required_key_missing"
    VALUE_NOT_ALLOWED = "value_not_allowed"
    EMPTY_VALUE = "empty_value"
    REGEX_MISMATCH = "regex_mismatch"
    UNKNOWN_OR_UNREPAIRABLE = "unknown_or_unrepairable"
    NO_REPAIR_NEEDED = "no_repair_needed"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationRepairRecommendation:
    """A single repair recommendation linked to a validation violation."""

    recommendation_id: str = ""
    config_id: str = ""
    validation_report_id: str = ""
    action: ConfigurationRepairAction = ConfigurationRepairAction.NO_ACTION
    key: str = ""
    current_value: str = ""
    recommended_value: str = ""
    reason: ConfigurationRepairReason = ConfigurationRepairReason.NO_REPAIR_NEEDED
    rationale: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.recommendation_id:
            self.recommendation_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "config_id": self.config_id,
            "validation_report_id": self.validation_report_id,
            "action": self.action.value,
            "key": self.key,
            "current_value": self.current_value,
            "recommended_value": self.recommended_value,
            "reason": self.reason.value,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationRepairReport:
    """Report containing all repair recommendations for a validation."""

    report_id: str = ""
    config_id: str = ""
    validation_report_id: str = ""
    recommendations: list[ConfigurationRepairRecommendation] = field(
        default_factory=list,
    )
    repairable_count: int = 0
    unrepairable_count: int = 0
    no_action_count: int = 0
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
            "validation_report_id": self.validation_report_id,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "repairable_count": self.repairable_count,
            "unrepairable_count": self.unrepairable_count,
            "no_action_count": self.no_action_count,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Repair recommendation engine
# ---------------------------------------------------------------------------


class ConfigurationRepairEngine:
    """Generates repair recommendations from validation reports."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._repairs_dir = self._artifacts_root / "config_repair_recommendations"
        self._repairs_dir.mkdir(parents=True, exist_ok=True)

    def _safe_repair_path(self, report_id: str) -> Path:
        target = (self._repairs_dir / report_id).resolve()
        sandbox = self._repairs_dir.resolve()
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

    def recommend(
        self,
        validation_report: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate repair recommendations from a validation report."""
        config_id = validation_report.get("config_id", "")
        report_id = validation_report.get("report_id", "")
        violations = validation_report.get("violations", [])
        valid = validation_report.get("valid", True)

        recommendations: list[ConfigurationRepairRecommendation] = []

        if valid and not violations:
            recommendations.append(
                ConfigurationRepairRecommendation(
                    config_id=config_id,
                    validation_report_id=report_id,
                    action=ConfigurationRepairAction.NO_ACTION,
                    reason=ConfigurationRepairReason.NO_REPAIR_NEEDED,
                    rationale="Validation passed with no violations.",
                )
            )
        else:
            entry_map: dict[str, str] = {}
            if config:
                for e in config.get("entries", []):
                    entry_map[e["key"]] = e["value"]

            for violation in violations:
                rec = self._generate_recommendation(
                    violation, config_id, report_id, entry_map,
                )
                recommendations.append(rec)

        repairable_count = sum(
            1 for r in recommendations
            if r.action != ConfigurationRepairAction.NO_ACTION
            and r.reason != ConfigurationRepairReason.UNKNOWN_OR_UNREPAIRABLE
        )
        unrepairable_count = sum(
            1 for r in recommendations
            if r.reason == ConfigurationRepairReason.UNKNOWN_OR_UNREPAIRABLE
        )
        no_action_count = sum(
            1 for r in recommendations
            if r.action == ConfigurationRepairAction.NO_ACTION
            and r.reason != ConfigurationRepairReason.UNKNOWN_OR_UNREPAIRABLE
        )

        repair_report = ConfigurationRepairReport(
            config_id=config_id,
            validation_report_id=report_id,
            recommendations=recommendations,
            repairable_count=repairable_count,
            unrepairable_count=unrepairable_count,
            no_action_count=no_action_count,
        )

        self._persist_report(repair_report)
        self._write_evidence(repair_report)

        return repair_report.to_dict()

    def _generate_recommendation(
        self,
        violation: dict[str, Any],
        config_id: str,
        validation_report_id: str,
        entry_map: dict[str, str],
    ) -> ConfigurationRepairRecommendation:
        """Map a violation to a repair recommendation."""
        message = violation.get("message", "")
        key = violation.get("key", "")
        current_value = entry_map.get(key, "")

        if "Required key missing" in message:
            return ConfigurationRepairRecommendation(
                config_id=config_id,
                validation_report_id=validation_report_id,
                action=ConfigurationRepairAction.ADD_MISSING_KEY,
                key=key,
                current_value="",
                recommended_value="<must_be_set>",
                reason=ConfigurationRepairReason.REQUIRED_KEY_MISSING,
                rationale=f"Key '{key}' is required but missing from configuration.",
            )

        if "not in allowed values" in message:
            return ConfigurationRepairRecommendation(
                config_id=config_id,
                validation_report_id=validation_report_id,
                action=ConfigurationRepairAction.CHANGE_VALUE,
                key=key,
                current_value=current_value,
                recommended_value="<select_from_allowed>",
                reason=ConfigurationRepairReason.VALUE_NOT_ALLOWED,
                rationale=f"Value '{current_value}' for key '{key}' is not allowed.",
            )

        if "must not be empty" in message:
            return ConfigurationRepairRecommendation(
                config_id=config_id,
                validation_report_id=validation_report_id,
                action=ConfigurationRepairAction.SET_NON_EMPTY_VALUE,
                key=key,
                current_value=current_value,
                recommended_value="<must_be_non_empty>",
                reason=ConfigurationRepairReason.EMPTY_VALUE,
                rationale=f"Key '{key}' must have a non-empty value.",
            )

        if "does not match pattern" in message:
            return ConfigurationRepairRecommendation(
                config_id=config_id,
                validation_report_id=validation_report_id,
                action=ConfigurationRepairAction.CHANGE_VALUE,
                key=key,
                current_value=current_value,
                recommended_value="<must_match_pattern>",
                reason=ConfigurationRepairReason.REGEX_MISMATCH,
                rationale=f"Value '{current_value}' for key '{key}' does not match required pattern.",
            )

        return ConfigurationRepairRecommendation(
            config_id=config_id,
            validation_report_id=validation_report_id,
            action=ConfigurationRepairAction.NO_ACTION,
            key=key,
            current_value=current_value,
            recommended_value="",
            reason=ConfigurationRepairReason.UNKNOWN_OR_UNREPAIRABLE,
            rationale=f"Violation cannot be automatically repaired: {message}",
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._repairs_dir.exists():
            return reports

        sandbox = self._repairs_dir.resolve()
        for entry in self._repairs_dir.iterdir():
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
            raise ValueError(f"Repair report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationRepairReport) -> None:
        report_dir = self._safe_repair_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_repair_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationRepairReport) -> str:
        evidence_dir = self._safe_repair_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report.report_id,
            "config_id": report.config_id,
            "validation_report_id": report.validation_report_id,
            "recommendation_count": len(report.recommendations),
        }
        (evidence_dir / "config_repair_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "config_repair_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_repair_summary.md").write_text(
            md, encoding="utf-8",
        )

        has_repairable = report.repairable_count > 0
        pass_fail = {
            "passed": report.unrepairable_count == 0,
            "report_id": report.report_id,
            "config_id": report.config_id,
            "validation_report_id": report.validation_report_id,
            "repairable_count": report.repairable_count,
            "unrepairable_count": report.unrepairable_count,
            "no_action_count": report.no_action_count,
            "has_recommendations": has_repairable,
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
        repairable = data.get("repairable_count", 0)
        unrepairable = data.get("unrepairable_count", 0)
        no_action = data.get("no_action_count", 0)
        total = repairable + unrepairable + no_action

        status = "ALL REPAIRABLE" if unrepairable == 0 and repairable > 0 else (
            "NO ACTION NEEDED" if repairable == 0 and unrepairable == 0
            else "HAS UNREPAIRABLE"
        )

        lines.append(f"# Configuration Repair Report ({status})")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Config ID: {data.get('config_id', '')}")
        lines.append(f"- Validation Report ID: {data.get('validation_report_id', '')}")
        lines.append(f"- Total recommendations: {total}")
        lines.append(f"- Repairable: {repairable}")
        lines.append(f"- Unrepairable: {unrepairable}")
        lines.append(f"- No action: {no_action}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        recommendations = data.get("recommendations", [])
        if recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for rec in recommendations:
                action = rec.get("action", "no_action").upper()
                key = rec.get("key", "")
                rationale = rec.get("rationale", "")
                lines.append(f"- [{action}] `{key}`: {rationale}")
                if rec.get("recommended_value"):
                    lines.append(f"  - Recommended: `{rec['recommended_value']}`")
                if rec.get("current_value"):
                    lines.append(f"  - Current: `{rec['current_value']}`")
            lines.append("")
        else:
            lines.append("## Recommendations")
            lines.append("")
            lines.append("No recommendations generated.")
            lines.append("")

        return "\n".join(lines)
